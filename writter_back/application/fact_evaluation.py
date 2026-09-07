"""独立低温度审校与确定性规则合并；模型不决定硬冲突或事实权威。"""

import json
from typing import Any, Literal
from uuid import UUID

from pydantic import Field
from application.fact_prompt_binding import FactBoundLLM

from application.fact_deterministic import deterministic_assertions
from application.prompts.template_loader import render_prompt
from application.story_facts import source_digest, validate_assertions
from service.value_objects.chapter_constraints import ChapterConstraintSet
from service.value_objects.fact_gate import FactGateReport
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


def _base(snapshot: ChapterConstraintSet, content: str, kind: str) -> dict[str, Any]:
    return {"tenant_id": snapshot.tenant_id, "novel_id": snapshot.novel_id,
        "chapter_number": snapshot.chapter_number, "artifact_kind": kind,
        "artifact_hash": source_digest(content), "snapshot_digest": snapshot.digest}


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


async def evaluate_facts(snapshot: ChapterConstraintSet, content: str, kind: str, llm: Any) -> FactGateReport:
    """失败、空报告和证据不足返回未知；高置信度硬冲突仅来自保守规则。"""
    literals = deterministic_assertions(snapshot, content, kind)
    checked = validate_assertions(literals, list(snapshot.fact_heads), draft=content)
    if checked.status == "blocked":
        return FactGateReport(**_base(snapshot, content, kind), status="blocked", coverage="partial",
            assertions=tuple(literals), findings=checked.findings, reasons=("存在与已确认事实不符的明确陈述",))
    try:
        if isinstance(llm, FactBoundLLM):
            llm = llm.delegate
        if llm is None or len(content) > 40000 or len(snapshot.model_dump_json()) > 60000:
            raise ValueError("审校输入不可用或超过预算")
        constraints = json.dumps({"snapshot_digest": snapshot.digest, "snapshot": snapshot.model_dump(mode="json")}, ensure_ascii=False)
        prompt = render_prompt("fact_judge.txt", constraints=constraints, kind=kind, content=content)
        raw = await llm.structured_generate(prompt=prompt, schema=FactExtraction.model_json_schema(),
            temperature=0.0, max_attempts=1)
        return _merge(snapshot, content, kind, FactExtraction.model_validate(raw), literals)
    except Exception:
        return FactGateReport(**_base(snapshot, content, kind), status="unknown", coverage="unknown",
            assertions=tuple(literals), findings=checked.findings,
            reasons=("事实审校未获得有效的完整证据，请人工复核",))
