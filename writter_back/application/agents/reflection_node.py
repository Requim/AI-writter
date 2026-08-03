"""Evidence-based chapter review with a server-owned quality gate."""

import hashlib
import json
import logging
from typing import Any, Literal, Self

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt
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
from application.schemas.agent_state import NovelAgentState
from application.streaming import emit_workflow_event
from service.ports.llm_service import LLMService

logger = logging.getLogger("uvicorn")
REVIEW_CHUNK_THRESHOLD = 8000
QUALITY_PASS_SCORE = 0.8
MIN_EFFECTIVE_DENSITY = 70.0
HARD_FAILURE_TYPES = {"logic", "power_system", "character", "consistency"}


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


def _parse_model_number(value: object, *, percentage_scale: bool = False) -> object:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("expected numeric value")
    if not isinstance(value, str):
        return value
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

    @field_validator("*", mode="before")
    @classmethod
    def parse_score(cls, value: object) -> object:
        return _parse_model_number(value)


class _ReflectionMetrics(BaseModel):
    passed: bool | None = None
    overall_quality_score: float | None = Field(default=None, ge=0, le=1)
    rubric_scores: _RubricScores | None = None
    word_count_analysis: _WordCountAnalysis

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
        raise RetryableWorkflowError("章节质量审读失败：模型返回的评分字段格式无效") from exc


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
        )
        result = await llm.structured_generate(prompt, REFLECTION_SCHEMA, temperature=0.1)
    else:
        chunks = await _review_chunks(llm, content, context)
        prompt = build_aggregation_prompt(
            chunks, content, context["chapter_outline"], context["main_characters"],
            context["memory_context"], len(content), context["story_bible"], previous,
        )
        result = await llm.structured_generate(prompt, AGGREGATION_SCHEMA, temperature=0.1)
        if isinstance(result, dict):
            result["issues"] = _merge_issues(result.get("issues"), chunks)
    if not isinstance(result, dict) or not result:
        raise RetryableWorkflowError("章节质量审读失败：模型未返回有效结果")
    return result


def _quality_gate(result: dict, content: str) -> tuple[dict, list[dict]]:
    metrics = _validate_reflection_metrics(result)
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
    }
    return gate, issues


def _choice_command(choice: Any, issues: list[dict], gate: dict) -> Command:
    if choice == "accept":
        return Command(goto="persist_node", update={"quality_gate": {**gate, "decision": "user_accepted"}})
    if choice == "regenerate":
        return Command(goto="chapter_writer_node")
    instructions = choice if isinstance(choice, str) and choice not in {"revise", ""} else None
    return Command(
        goto="revision_node",
        update={
            "quality_gate": gate,
            "reflection_issues": issues,
            "user_decision": {"action": "revise", "instructions": instructions},
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


async def reflection_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["persist_node", "revision_node", "chapter_writer_node"]]:
    """审读正文并由服务端基于证据执行质量闸门。"""
    content = state.get("current_chapter_content", "")
    outline = state.get("chapter_outlines", [{}])[-1] if state.get("chapter_outlines") else {}
    total_raw = state.get("total_outline", {})
    if isinstance(total_raw, str):
        try:
            total_raw = json.loads(total_raw)
        except ValueError:
            total_raw = {}
    total = total_raw if isinstance(total_raw, dict) else {}
    llm = config["configurable"].get("llm_config", {}).get("llm_instance")
    if not llm:
        raise RetryableWorkflowError("章节质量审读失败：LLM 不可用")
    context = {
        "chapter_outline": outline, "main_characters": total.get("main_characters", []),
        "memory_context": state.get("memory_context", ""), "story_bible": build_story_bible(total),
    }
    result = await _review_content(llm, content, context, state.get("reflection_issues", []))
    gate, issues = _quality_gate(result, content)
    emit_workflow_event(
        "quality", {**gate, "issues": issues, "attempt": state.get("revision_attempts", 0)}, "reflection_node"
    )
    if gate["decision"] == "pass":
        return Command(goto="persist_node", update={"quality_gate": gate, "reflection_issues": issues})
    auto_mode = config["configurable"].get("auto_mode", False)
    attempts = state.get("revision_attempts", 0)
    max_attempts = config["configurable"].get("max_reflection_loops", 5)
    if auto_mode and gate["decision"] in {"patch", "refactor"} and attempts < max_attempts:
        return _choice_command("revise", issues, gate)
    direct_rewrite = config["configurable"].get("direct_rewrite", False)
    if direct_rewrite:
        if attempts < max_attempts:
            return _direct_rewrite_revision(gate, issues)
        raise QualityGateReviewRequired("章节重写已达到自动修订上限，且仍未通过质量门禁")
    if auto_mode and gate["decision"] == "human_review":
        action = "quality_gate_human_review"
    else:
        action = "quality_gate_exhausted" if auto_mode else "review_reflection_issues"
    choice = interrupt(_review_payload(action, state, gate, issues))
    return _choice_command(choice, issues, gate)
