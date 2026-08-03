"""Evidence-based chapter review with a server-owned quality gate."""

import hashlib
import json
import logging
from typing import Any, Literal, Self

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from application.continuity import build_story_bible
from application.errors import QualityGateReviewRequired, RetryableWorkflowError
from application.prompts.reflection_prompts import (
    AGGREGATION_SCHEMA,
    CHUNK_REFLECTION_SCHEMA,
    REFLECTION_SCHEMA,
    build_aggregation_prompt,
    build_chunk_reflection_prompt,
    build_reflection_prompt,
    split_into_chunks,
)
from application.prompts.version import PROMPT_VERSION
from application.proposals import (
    proposal_update,
    proposal_matches,
    request_decision,
    require_proposal,
    unpack_decision,
)
from application.schemas.agent_state import NovelAgentState
from application.streaming import emit_workflow_event
from service.ports.llm_service import LLMService

logger = logging.getLogger("uvicorn")
REVIEW_CHUNK_THRESHOLD = 8000
QUALITY_PASS_SCORE = 0.8
MIN_EFFECTIVE_DENSITY = 70.0
HARD_FAILURE_TYPES = {"logic", "power_system", "character", "consistency"}
RUBRIC_FIELDS = (
    "causality", "continuity", "character", "scene_function", "voice",
    "prose_specificity", "ending_effect",
)
SUPPORTED_SCORE_SCALES = {5, 10, 100}
REVIEW_SCORE_CONTRACT = """
【评分契约】
- causality、continuity、character、scene_function、voice、prose_specificity、ending_effect
  七项必须全部使用 0-5 的 JSON 数值，禁止百分制、十分制、字符串或混合量纲。
- score_scale 必须是 JSON 整数 5，用于声明七项评分采用同一量纲。
- 合法示例：{"causality": 4.2, "continuity": 3.8, "character": 4.0,
  "scene_function": 3.6, "voice": 4.1, "prose_specificity": 3.9,
  "ending_effect": 4.3, "score_scale": 5}。
"""


def _normalize_issues(value: object) -> list[dict]:
    """Sanitize untrusted nested issue values before set/dict operations."""
    if isinstance(value, dict):
        candidates = [value]
    elif isinstance(value, list):
        candidates = [item for item in value if isinstance(item, dict)]
    else:
        return []
    normalized = []
    for issue in candidates:
        clean = dict(issue)
        location = clean.get("location")
        if isinstance(location, list):
            location = "；".join(item for item in location if isinstance(item, str))
        if "location" in clean:
            clean["location"] = location if isinstance(location, str) else ""
        severity = clean.get("severity")
        if "severity" in clean:
            clean["severity"] = (
                severity
                if isinstance(severity, str) and severity in {"high", "medium", "low"}
                else "low"
            )
        normalized.append(clean)
    return normalized


def _parse_model_number(value: object, *, percentage_scale: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("expected numeric value")
    if not isinstance(value, str):
        return float(value)
    normalized = value.strip().replace("％", "%")
    is_percentage = normalized.endswith("%")
    parsed = float(normalized[:-1].strip() if is_percentage else normalized)
    return parsed / 100 if is_percentage and percentage_scale else parsed


def _parse_model_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise ValueError("expected boolean value")


def _parse_score_scale(value: object) -> int | None:
    if value is None:
        return None
    parsed = _parse_model_number(value)
    if parsed not in SUPPORTED_SCORE_SCALES:
        raise ValueError("score_scale must be 5, 10, or 100")
    return int(parsed)


def _parse_rubric_scores(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError("rubric_scores must be an object")
    return {key: _parse_model_number(value.get(key)) for key in RUBRIC_FIELDS}


def _infer_score_scale(scores: list[float]) -> int:
    bands = set()
    for score in scores:
        if score < 0 or score > 100:
            raise ValueError("rubric score must be between 0 and 100")
        bands.add(5 if score <= 5 else 10 if score <= 10 else 100)
    if len(bands) != 1:
        raise ValueError("mixed or ambiguous rubric score scales")
    return bands.pop()


def _resolve_score_scale(scores: list[float], declared: object) -> int:
    scale = _parse_score_scale(declared)
    if scale is None:
        return _infer_score_scale(scores)
    if any(score < 0 or score > scale for score in scores):
        raise ValueError("rubric score exceeds declared score_scale")
    return scale


def _rubric_audit(result: dict, source_scale: int | None) -> dict[str, Any]:
    """Keep the provider's original scoring scale for later diagnosis."""
    raw = result.get("rubric_scores")
    if not isinstance(raw, dict):
        return {"source_score_scale": None, "raw_rubric_scores": {}}
    return {
        "source_score_scale": source_scale,
        "raw_rubric_scores": _parse_rubric_scores(raw),
    }


class _WordCountAnalysis(BaseModel):
    total_count: int = Field(ge=0)
    effective_density: float = Field(ge=0, le=100)
    is_valid_word_count: bool

    @field_validator("effective_density", mode="before")
    @classmethod
    def parse_effective_density(cls, value: object) -> object:
        return _parse_model_number(value)

    @field_validator("is_valid_word_count", mode="before")
    @classmethod
    def parse_is_valid_word_count(cls, value: object) -> bool:
        return _parse_model_bool(value)


class _RubricScores(BaseModel):
    causality: float = Field(ge=0, le=5)
    continuity: float = Field(ge=0, le=5)
    character: float = Field(ge=0, le=5)
    scene_function: float = Field(ge=0, le=5)
    voice: float = Field(ge=0, le=5)
    prose_specificity: float = Field(ge=0, le=5)
    ending_effect: float = Field(ge=0, le=5)

class _ReflectionMetrics(BaseModel):
    passed: bool | None = None
    overall_quality_score: float | None = Field(default=None, ge=0, le=1)
    rubric_scores: _RubricScores | None = None
    score_scale: Literal[5, 10, 100] | None = None
    word_count_analysis: _WordCountAnalysis

    @model_validator(mode="before")
    @classmethod
    def normalize_rubric_scale(cls, value: object) -> object:
        if not isinstance(value, dict) or value.get("rubric_scores") is None:
            return value
        parsed = _parse_rubric_scores(value["rubric_scores"])
        scale = _resolve_score_scale(list(parsed.values()), value.get("score_scale"))
        factor = scale / 5
        normalized = dict(value)
        normalized["score_scale"] = scale
        normalized["rubric_scores"] = {
            key: score / factor for key, score in parsed.items()
        }
        if scale != 5:
            logger.warning("【反思检查节点】归一化模型评分量纲 | source_scale=%s", scale)
        return normalized

    @field_validator("passed", mode="before")
    @classmethod
    def parse_passed(cls, value: object) -> bool | None:
        return None if value is None else _parse_model_bool(value)

    @field_validator("overall_quality_score", mode="before")
    @classmethod
    def parse_quality_score(cls, value: object) -> object:
        return None if value is None else _parse_model_number(value, percentage_scale=True)

    @model_validator(mode="after")
    def require_score_source(self) -> Self:
        if self.rubric_scores is None and self.overall_quality_score is None:
            raise ValueError("rubric_scores or overall_quality_score is required")
        return self


def _validate_reflection_metrics(result: dict) -> _ReflectionMetrics:
    try:
        return _ReflectionMetrics.model_validate(result)
    except ValidationError as exc:
        fields = [".".join(str(part) for part in error["loc"]) for error in exc.errors()]
        logger.warning("【反思检查节点】评分字段格式无效 | 字段=%s", ",".join(fields))
        detail = ",".join(fields[:12])
        raise RetryableWorkflowError(f"章节质量审读失败：评分字段格式无效 ({detail})") from exc


def _quality_score(metrics: _ReflectionMetrics) -> float:
    if metrics.rubric_scores is None:
        return float(metrics.overall_quality_score or 0)
    values = metrics.rubric_scores.model_dump().values()
    return sum(values) / (len(values) * 5)


def _issue_id(issue: dict) -> str:
    supplied = issue.get("issue_id")
    if isinstance(supplied, str) and supplied.strip():
        return supplied.strip()[:80]
    source = "|".join(str(issue.get(key, "")) for key in ("type", "evidence", "location"))
    return f"issue-{hashlib.sha1(source.encode('utf-8')).hexdigest()[:12]}"


def _annotate_issues(issues: list[dict], content: str) -> list[dict]:
    annotated = []
    for raw in issues:
        issue = dict(raw)
        severity = issue.get("severity", "low")
        if not isinstance(severity, str) or severity not in {"high", "medium", "low"}:
            severity = "low"
        issue_type = issue.get("type", "unknown")
        if not isinstance(issue_type, str) or not issue_type.strip():
            issue_type = "unknown"
        priority = issue.get("priority_action")
        if not isinstance(priority, str) or priority not in {"must_fix", "optional", "can_ignore"}:
            priority = {"high": "must_fix", "medium": "optional"}.get(severity, "can_ignore")
        evidence = str(issue.get("evidence", "") or "").strip()
        issue.update(
            issue_id=_issue_id(issue),
            type=issue_type,
            severity=severity,
            priority_action=priority,
            issue_resolved=issue.get("issue_resolved") is True,
            evidence=evidence,
            evidence_valid=bool(evidence and evidence in content),
        )
        annotated.append(issue)
    return annotated


async def _review_chunks(
    llm: LLMService, content: str, context: dict[str, Any]
) -> list[dict]:
    chunks = split_into_chunks(content)
    results = []
    for chunk in chunks:
        prompt = build_chunk_reflection_prompt(
            chunk["text"], chunk["chunk_index"], len(chunks), chunk["start"], chunk["end"],
            context["chapter_outline"], context["main_characters"], context["memory_context"],
            context["story_bible"],
        )
        result = await llm.structured_generate(prompt, CHUNK_REFLECTION_SCHEMA, temperature=0.1)
        issues = _normalize_issues(result.get("issues") if isinstance(result, dict) else None)
        for issue in issues:
            issue.update(_chunk=chunk["chunk_index"], _chunk_range=f"{chunk['start']}-{chunk['end']}")
        results.append({**chunk, "issues": issues})
    return results


async def _generate_valid_review(
    llm: LLMService, prompt: str, schema: dict[str, Any]
) -> dict:
    """Retry one business-contract failure with explicit scale feedback."""
    last_error: RetryableWorkflowError | None = None
    for attempt in range(2):
        result = await llm.structured_generate(
            prompt, schema, temperature=0.1, max_attempts=1
        )
        if not isinstance(result, dict) or not result:
            last_error = RetryableWorkflowError("章节质量审读失败：模型未返回有效结果")
        else:
            try:
                _validate_reflection_metrics(result)
                return result
            except RetryableWorkflowError as exc:
                last_error = exc
        if attempt == 0:
            prompt += (
                "\n\n【格式纠正】上一次评分不符合契约。七项 rubric 必须全部使用 JSON 数值 0-5，"
                f"score_scale 必须为整数 5，不得混用百分制或文本；错误：{last_error}。"
                "只重新输出完整 JSON。"
            )
    raise last_error or RetryableWorkflowError("章节质量审读失败：结果无效")


def _merge_issues(primary: object, chunks: list[dict]) -> list[dict]:
    merged = _normalize_issues(primary)
    seen = {str(issue.get("evidence") or issue.get("location") or "") for issue in merged}
    for chunk in chunks:
        for issue in chunk.get("issues", []):
            key = str(issue.get("evidence") or issue.get("location") or "")
            if key and key not in seen:
                merged.append(issue)
                seen.add(key)
    return merged


async def _review_content(
    llm: LLMService,
    content: str,
    context: dict[str, Any],
    previous: list[dict],
) -> dict:
    if len(content) <= REVIEW_CHUNK_THRESHOLD:
        prompt = build_reflection_prompt(
            content, context["chapter_outline"], context["main_characters"],
            context["memory_context"], len(content), context["story_bible"], previous,
        ) + REVIEW_SCORE_CONTRACT
        result = await _generate_valid_review(llm, prompt, REFLECTION_SCHEMA)
    else:
        chunks = await _review_chunks(llm, content, context)
        prompt = build_aggregation_prompt(
            chunks, content, context["chapter_outline"], context["main_characters"],
            context["memory_context"], len(content), context["story_bible"], previous,
        ) + REVIEW_SCORE_CONTRACT
        result = await _generate_valid_review(llm, prompt, AGGREGATION_SCHEMA)
        result["issues"] = _merge_issues(result.get("issues"), chunks)
    return result


def _quality_gate(result: dict, content: str) -> tuple[dict, list[dict]]:
    metrics = _validate_reflection_metrics(result)
    audit = _rubric_audit(result, metrics.score_scale)
    issues = _annotate_issues(_normalize_issues(result.get("issues")), content)
    score = _quality_score(metrics)
    hard_failures = result.get("hard_failures", [])
    if not isinstance(hard_failures, list):
        hard_failures = []
    hard_ids = {item.strip() for item in hard_failures if isinstance(item, str) and item.strip()}
    blocking = [
        issue for issue in issues
        if issue["priority_action"] == "must_fix" and not issue["issue_resolved"] and issue["evidence_valid"]
    ]
    hard = any(issue["issue_id"] in hard_ids or issue.get("type") in HARD_FAILURE_TYPES for issue in blocking)
    words = metrics.word_count_analysis
    passed = score >= QUALITY_PASS_SCORE and words.effective_density >= MIN_EFFECTIVE_DENSITY
    passed = passed and words.is_valid_word_count and not blocking
    if passed:
        decision = "pass"
    elif not blocking:
        decision = "human_review"
    else:
        decision = "refactor" if hard or score < 0.55 or words.effective_density < 50 else "patch"
    gate = {
        "decision": decision, "score": score,
        "rubric_scores": metrics.rubric_scores.model_dump() if metrics.rubric_scores else {},
        "word_count_analysis": words.model_dump(), "hard_failures": sorted(hard_ids),
        "prompt_version": PROMPT_VERSION,
        **audit,
    }
    return gate, issues


def _choice_command(choice: Any, issues: list[dict], gate: dict) -> Command:
    if choice == "accept":
        return Command(
            goto="persist_node",
            update={
                "quality_gate": {**gate, "decision": "user_accepted"},
                "quality_results": [{**gate, "decision": "user_accepted"}],
                "pending_proposal": None,
                "pending_proposal_decision": None,
            },
        )
    if choice == "regenerate":
        return Command(
            goto="chapter_writer_node",
            update={"pending_proposal": None, "pending_proposal_decision": None},
        )
    instructions = choice if isinstance(choice, str) and choice not in {"revise", ""} else None
    return Command(
        goto="revision_node",
        update={
            "quality_gate": gate,
            "reflection_issues": issues,
            "user_decision": {"action": "revise", "instructions": instructions},
            "pending_proposal": None,
            "pending_proposal_decision": None,
        },
    )


def _review_payload(action: str, state: NovelAgentState, gate: dict, issues: list[dict]) -> dict:
    exhausted = action == "quality_gate_exhausted"
    needs_evidence = action == "quality_gate_human_review"
    message = "质量证据与分项评分不一致，请人工复核" if needs_evidence else "质量闸门未通过，请审阅证据后决定"
    if exhausted:
        message = "自动修订已达上限，请人工决定接受、重写或继续修订"
    return {
        "action": action,
        "message": message,
        "chapter_number": state.get("current_chapter_index", 0) + 1,
        "quality_score": gate["score"],
        "rubric_scores": gate["rubric_scores"],
        "source_score_scale": gate.get("source_score_scale"),
        "word_count_analysis": gate["word_count_analysis"],
        "quality_decision": gate["decision"],
        "issues": issues,
    }


def _direct_rewrite_revision(gate: dict, issues: list[dict]) -> Command:
    labels = {
        "causality": "因果链",
        "continuity": "连续性",
        "character": "人物一致性",
        "scene_function": "场景功能",
        "voice": "叙事声音",
        "prose_specificity": "语言具体度",
        "ending_effect": "结尾效力",
    }
    scores = gate.get("rubric_scores", {})
    weakest = sorted(
        ((key, value) for key, value in scores.items() if isinstance(value, (int, float))),
        key=lambda item: item[1],
    )[:3]
    focus = "、".join(f"{labels.get(key, key)}（{value:.1f}/5）" for key, value in weakest)
    instruction = "本章质量门禁未通过且缺少可安全局修的原文证据，请进行全文质量重构。"
    if focus:
        instruction += f"优先提升：{focus}。"
    return Command(
        goto="revision_node",
        update={
            "quality_gate": {**gate, "decision": "refactor", "source_decision": gate["decision"]},
            "reflection_issues": issues,
            "user_decision": {"action": "revise", "instructions": instruction},
        },
    )


def _review_context(state: NovelAgentState) -> tuple[str, dict[str, Any]]:
    content = str(state.get("current_chapter_content") or "")
    outlines = state.get("chapter_outlines") or []
    outline = outlines[-1] if outlines and isinstance(outlines[-1], dict) else {}
    total_raw = state.get("total_outline", {})
    if isinstance(total_raw, str):
        try:
            total_raw = json.loads(total_raw)
        except ValueError:
            total_raw = {}
    total = total_raw if isinstance(total_raw, dict) else {}
    context = {
        "chapter_outline": outline,
        "main_characters": total.get("main_characters", []),
        "memory_context": state.get("memory_context", ""),
        "story_bible": build_story_bible(total),
    }
    return content, context


def _reflection_proposal(
    state: NovelAgentState, action: str, gate: dict, issues: list[dict]
) -> Command:
    payload = {"status": "ready", "action": action, "gate": gate, "issues": issues}
    update = proposal_update(
        state, "reflection", payload, state.get("current_chapter_index", 0) + 1
    )
    return Command(goto="reflection_review_node", update=update)


def _unavailable_proposal(state: NovelAgentState, reason: str) -> Command:
    payload = {"status": "unavailable", "reason": reason}
    update = proposal_update(
        state, "reflection", payload, state.get("current_chapter_index", 0) + 1
    )
    return Command(goto="reflection_review_node", update=update)


def _manual_action(auto_mode: bool, gate: dict) -> str:
    if auto_mode and gate["decision"] == "human_review":
        return "quality_gate_human_review"
    return "quality_gate_exhausted" if auto_mode else "review_reflection_issues"


async def reflection_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["persist_node", "revision_node", "reflection_review_node"]]:
    """Generate one quality result; manual decisions run in a separate node."""
    chapter = state.get("current_chapter_index", 0) + 1
    if proposal_matches(state, "reflection", chapter):
        return Command(goto="reflection_review_node")
    llm = config["configurable"].get("llm_config", {}).get("llm_instance")
    if not llm:
        raise RetryableWorkflowError("章节质量审读失败：LLM 不可用")
    emit_workflow_event(
        "status", {"status": "started", "message": "正在执行章节质量审读"},
        "reflection_node",
    )
    content, context = _review_context(state)
    try:
        result = await _review_content(llm, content, context, state.get("reflection_issues", []))
    except RetryableWorkflowError as exc:
        if config["configurable"].get("direct_rewrite", False):
            raise QualityGateReviewRequired(str(exc)) from exc
        return _unavailable_proposal(state, str(exc))
    gate, issues = _quality_gate(result, content)
    gate["chapter_number"] = chapter
    logger.info("【反思检查节点】评分审计 | scale=%s raw=%s", gate.get("source_score_scale"), gate.get("raw_rubric_scores"))
    emit_workflow_event(
        "quality", {**gate, "issues": issues, "attempt": state.get("revision_attempts", 0)},
        "reflection_node",
    )
    if gate["decision"] == "pass":
        return Command(
            goto="persist_node",
            update={
                "quality_gate": gate,
                "quality_results": [gate],
                "reflection_issues": issues,
            },
        )
    return _route_quality_result(state, config, gate, issues)


def _route_quality_result(
    state: NovelAgentState, config: RunnableConfig, gate: dict, issues: list[dict]
) -> Command:
    values = config["configurable"]
    attempts = state.get("revision_attempts", 0)
    maximum = values.get("max_reflection_loops", 5)
    if values.get("auto_mode", False) and gate["decision"] in {"patch", "refactor"} and attempts < maximum:
        return _choice_command("revise", issues, gate)
    if values.get("direct_rewrite", False):
        if attempts < maximum:
            return _direct_rewrite_revision(gate, issues)
        raise QualityGateReviewRequired("章节重写已达到自动修订上限，且仍未通过质量门禁")
    action = _manual_action(values.get("auto_mode", False), gate)
    return _reflection_proposal(state, action, gate, issues)


def _unavailable_choice(choice: Any, reason: str, chapter: int) -> Command:
    if choice in {"retry", "regenerate_review"}:
        return Command(
            goto="reflection_node",
            update={"pending_proposal": None, "pending_proposal_decision": None},
        )
    if choice == "regenerate":
        return Command(
            goto="chapter_writer_node",
            update={"pending_proposal": None, "pending_proposal_decision": None},
        )
    gate = {
        "decision": "user_accepted_without_ai_review",
        "review_error": reason,
        "prompt_version": PROMPT_VERSION,
        "chapter_number": chapter,
    }
    return Command(
        goto="persist_node",
        update={
            "quality_gate": gate,
            "quality_results": [gate],
            "pending_proposal": None,
            "pending_proposal_decision": None,
        },
    )


async def reflection_review_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["persist_node", "revision_node", "chapter_writer_node", "reflection_node"]]:
    """Collect a decision about an already checkpointed quality proposal."""
    del config
    chapter = state.get("current_chapter_index", 0) + 1
    proposal = require_proposal(state, "reflection", chapter)
    payload = proposal["payload"] if isinstance(proposal["payload"], dict) else {}
    if payload.get("status") == "unavailable":
        fields = {
            "action": "quality_review_unavailable",
            "message": "AI 审读结果无法解析，请选择重新审读、接受未审读草稿或重写正文",
            "review_unavailable_reason": payload.get("reason", "结构化结果无效"),
        }
    else:
        fields = _review_payload(payload.get("action", "review_reflection_issues"), state, payload["gate"], payload["issues"])
    choice = unpack_decision(request_decision(state, proposal, **fields), proposal)
    if payload.get("status") == "unavailable":
        return _unavailable_choice(
            choice, str(payload.get("reason") or ""), chapter
        )
    return _choice_command(choice, payload["issues"], payload["gate"])
