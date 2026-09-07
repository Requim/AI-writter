"""事实编译与最小确定性校验；本模块不负责自由文本关系抽取。"""

import hashlib
import json
from typing import Any
from uuid import UUID, uuid5

from service.value_objects.story_fact import (
    CanonicalFact, FactEvidence, StoryEntity, StoryFactAssertion, StoryFactVersion,
    ValidationFinding, ValidationReport,
)


def source_digest(content: str) -> str:
    """对原始证据内容计算摘要，防止复用旧稿的断言。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def compile_confirmed_fact(statement: dict, *, source_kind: str, source_ref: str,
                           source_version: int, source_content: str, quote: str, confirmed: bool) -> CanonicalFact:
    """从调用方已确认的显式结构化事实编译证据；不猜测未给出的关系。"""
    if confirmed is not True or source_kind not in {"character_design", "novel_plan", "human_confirmation"}:
        raise ValueError("只允许编译已确认的设定来源")
    if not quote.strip() or quote not in source_content:
        raise ValueError("证据原文不在已确认来源中")
    evidence = FactEvidence(source_kind=source_kind, source_ref=source_ref, source_version=source_version,
                            quote=quote, source_hash=source_digest(source_content))
    return CanonicalFact.model_validate({**statement, "evidence": evidence})


def compile_character_surnames(novel_id: UUID, design: dict, *, source_ref: str,
                               source_version: int, confirmed: bool) -> tuple[list[StoryEntity], list[CanonicalFact]]:
    """只编译已确认角色的显式姓氏；跳过旧数据推断姓氏及缺失字段。"""
    if confirmed is not True:
        raise ValueError("角色设定尚未确认")
    content = json.dumps(design, ensure_ascii=False, sort_keys=True)
    entities, facts = [], []
    seen = set()
    for character in design.get("characters", []):
        if not _explicit_character(character):
            continue
        key = character["character_id"].strip()
        if key in seen:
            raise ValueError("角色ID重复，无法编译规范事实")
        seen.add(key)
        entity = StoryEntity(id=uuid5(novel_id, "character:" + key), entity_key="character:" + key,
                             kind="character", name=character["name"])
        fact = compile_confirmed_fact({"subject_id": entity.id, "predicate": "surname", "value_text": character["surname"]},
            source_kind="character_design", source_ref=source_ref, source_version=source_version,
            source_content=content, quote=json.dumps(character, ensure_ascii=False, sort_keys=True), confirmed=True)
        entities.append(entity)
        facts.append(fact)
    return entities, facts


def _explicit_character(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("origin_type") == "legacy_import":
        return False
    return all(isinstance(value.get(key), str) and value[key].strip() for key in ("character_id", "name", "surname"))


def _finding(assertion: StoryFactAssertion, fact: StoryFactVersion | None,
             code: str, message: str, *, hard: bool = False) -> ValidationFinding:
    return ValidationFinding(code=code, severity="hard_conflict" if hard else "unknown",
        assertion_id=assertion.id, fact_id=fact.id if fact else None, fact_version=fact.version if fact else None,
        message=message, expected_evidence=fact.evidence if fact else None, actual_evidence=assertion.evidence)


def _check_assertion(assertion: StoryFactAssertion, facts: list[StoryFactVersion], draft: str) -> ValidationFinding | None:
    if assertion.evidence.source_hash != source_digest(draft) or assertion.evidence.quote not in draft:
        return _finding(assertion, None, "evidence_mismatch", "断言证据与当前正文不一致")
    candidates = [fact for fact in facts if (fact.subject_id, fact.predicate) == (assertion.subject_id, assertion.predicate)]
    if not candidates:
        return _finding(assertion, None, "canonical_fact_missing", "尚无对应的已确认事实")
    version = max(fact.version for fact in candidates)
    latest = [fact for fact in candidates if fact.version == version]
    if len(latest) != 1:
        return _finding(assertion, None, "ambiguous_fact_version", "规范事实版本不唯一")
    fact = latest[0]
    chapter = assertion.chapter_number
    if fact.status != "confirmed" or chapter < fact.valid_from_chapter or (fact.valid_to_chapter and chapter > fact.valid_to_chapter):
        return _finding(assertion, fact, "canonical_fact_inactive", "规范事实已撤回或不适用于本章")
    if (assertion.object_entity_id, assertion.value_text) != (fact.object_entity_id, fact.value_text):
        return _finding(assertion, fact, "canonical_fact_conflict", "正文明确断言与已确认事实不符", hard=True)
    return None


def validate_assertions(assertions: list[StoryFactAssertion], facts: list[StoryFactVersion], *, draft: str) -> ValidationReport:
    """校验显式断言与最新事实；无断言或无依据保持未知，不宣称整章一致。"""
    findings = tuple(item for assertion in assertions if (item := _check_assertion(assertion, facts, draft)))
    status = "blocked" if any(item.severity == "hard_conflict" for item in findings) else "unknown" if findings or not assertions else "pass"
    return ValidationReport(status=status, findings=findings, checked_assertions=len(assertions))
