"""独立低温度审校与确定性规则合并；模型不决定硬冲突或事实权威。"""

import json
import logging
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, ValidationError
from config import settings
from application.fact_prompt_binding import FactBoundLLM

from application.fact_deterministic import deterministic_assertions
from application.prompts.template_loader import render_prompt
from application.story_facts import source_digest, validate_assertions
from service.value_objects.chapter_constraints import ChapterConstraintSet
from service.value_objects.fact_gate import FACT_EXTRACTION_VERSION, FactGateReport
from service.value_objects.story_fact import FactContract, FactEvidence, FactStatement, StoryFactAssertion


class ExtractedClaim(FactContract):
    subject_id: UUID
    predicate: Literal["surname", "family", "ancestral_hall_owner", "location", "life_status"]
    object_entity_id: UUID | None = None
    value_text: str | None = None
    quote: str = Field(min_length=1, max_length=2000)


class FactExtraction(FactContract):
    coverage: Literal["complete", "partial", "unknown"]
    claims: tuple[ExtractedClaim, ...] = Field(max_length=100)
    unresolved: tuple[str, ...] = Field(max_length=50)


FACT_EXTRACTION_SHAPE = {"coverage": "string", "claims": "array", "unresolved": "array"}
FACT_EXTRACTION_ATTEMPTS = 3


def _extraction_prompt(snapshot: ChapterConstraintSet, content: str, kind: str) -> str:
    constraints = json.dumps({"snapshot_digest": snapshot.digest, "snapshot": snapshot.model_dump(mode="json")},
                             ensure_ascii=False)
    prompt = render_prompt("fact_judge.txt", constraints=constraints, kind=kind, content=content)
    return prompt + "\n只输出符合以下 JSON Schema 的业务数据，不要输出 Schema 本身：\n" + json.dumps(
        FactExtraction.model_json_schema(), ensure_ascii=False)


def _base(snapshot: ChapterConstraintSet, content: str, kind: str) -> dict[str, Any]:
    return {"tenant_id": snapshot.tenant_id, "novel_id": snapshot.novel_id,
        "chapter_number": snapshot.chapter_number, "artifact_kind": kind,
        "artifact_hash": source_digest(content), "snapshot_digest": snapshot.digest,
        "extraction_version": FACT_EXTRACTION_VERSION}


def _assertion(claim: ExtractedClaim, snapshot: ChapterConstraintSet, content: str) -> StoryFactAssertion:
    if content.count(claim.quote) != 1:
        raise ValueError("断言引用原文不存在或不唯一")
    ids = {item.id for item in snapshot.entities}
    if claim.subject_id not in ids or (claim.object_entity_id and claim.object_entity_id not in ids):
        raise ValueError("断言引用未知实体")
    evidence = FactEvidence(source_kind="chapter_draft", source_ref="artifact:" + source_digest(content)[:24],
        source_version=1, quote=claim.quote, source_hash=source_digest(content))
    statement = FactStatement(**claim.model_dump(exclude={"quote"}), evidence=evidence)
    return StoryFactAssertion(**statement.model_dump(), chapter_number=snapshot.chapter_number)


def _merge(snapshot: ChapterConstraintSet, content: str, kind: str, extraction: FactExtraction,
           literals: list[StoryFactAssertion]) -> FactGateReport:
    claims = [_assertion(claim, snapshot, content) for claim in extraction.claims]
    checked = validate_assertions(claims + literals, list(snapshot.fact_heads), draft=content)
    findings = tuple(item.model_copy(update={"severity": "unknown", "code": "semantic_conflict"})
        if item.severity == "hard_conflict" else item for item in checked.findings)
    reasons = list(extraction.unresolved)
    if extraction.coverage != "complete":
        reasons.append("全文事实覆盖尚未确认")
    if not snapshot.active_facts:
        reasons.append("本章没有适用的已确认事实")
    if not claims and not literals:
        reasons.append("没有获得可核对的明确事实断言")
    return FactGateReport(**_base(snapshot, content, kind),
        status="unknown" if findings or reasons else "pass", coverage=extraction.coverage,
        assertions=tuple(claims + literals), findings=findings, reasons=tuple(reasons))


async def _extract_report(
    snapshot: ChapterConstraintSet,
    content: str,
    kind: str,
    llm: Any,
    literals: list[StoryFactAssertion],
) -> FactGateReport:
    prompt = _extraction_prompt(snapshot, content, kind)
    feedback = ""
    for _attempt in range(FACT_EXTRACTION_ATTEMPTS):
        raw = await llm.structured_generate(
            prompt=prompt + feedback,
            schema=FACT_EXTRACTION_SHAPE,
            temperature=0.0,
            max_attempts=1,
        )
        try:
            extraction = FactExtraction.model_validate(raw)
            return _merge(snapshot, content, kind, extraction, literals)
        except ValidationError as exc:
            feedback = (
                "\n上一轮事实抽取结果无效，请只返回修正后的完整 JSON。"
                f"校验错误：{str(exc)[:1200]}"
            )
    raise ValueError("事实抽取结果连续多次不符合业务契约")


async def evaluate_facts(snapshot: ChapterConstraintSet, content: str, kind: str, llm: Any) -> FactGateReport:
    """失败、空报告和证据不足返回未知；高置信度硬冲突仅来自保守规则。"""
    literals = deterministic_assertions(snapshot, content, kind)
    checked = validate_assertions(literals, list(snapshot.fact_heads), draft=content)
    if checked.status == "blocked":
        return FactGateReport(**_base(snapshot, content, kind), status="blocked", coverage="partial",
            assertions=tuple(literals), findings=checked.findings, reasons=("存在与已确认事实不符的明确陈述",))
    if settings.FACT_REVIEW_MODE == "human_only":
        return FactGateReport(**_base(snapshot, content, kind), status="unknown", coverage="partial",
            assertions=tuple(literals), findings=checked.findings, reasons=("当前启用强制人工事实审核",))
    if not snapshot.active_facts:
        return FactGateReport(**_base(snapshot, content, kind), status="unknown", coverage="unknown",
            assertions=tuple(literals), findings=checked.findings,
            reasons=("本章缺少已确认的事实基线；请先登记并确认角色事实，或核对当前稿件后明确接受。"
                     "仅重新调用模型不能补足作者确认。",))
    try:
        if isinstance(llm, FactBoundLLM):
            llm = llm.delegate
        if llm is None or len(content) > 40000 or len(snapshot.model_dump_json()) > 60000:
            raise ValueError("审校输入不可用或超过预算")
        return await _extract_report(snapshot, content, kind, llm, literals)
    except Exception as exc:
        detail = type(exc).__name__
        if isinstance(exc, ValidationError):
            detail = "; ".join(
                ".".join(str(part) for part in error["loc"]) + ":" + error["type"]
                for error in exc.errors()
            )
        logging.getLogger("uvicorn").warning(
            "事实提取失败 | kind=%s exception=%s detail=%s", kind, type(exc).__name__, detail[:500]
        )
        return FactGateReport(**_base(snapshot, content, kind), status="unknown", coverage="unknown",
            assertions=tuple(literals), findings=checked.findings,
            reasons=("事实审校未获得有效的完整证据，请人工复核",))
