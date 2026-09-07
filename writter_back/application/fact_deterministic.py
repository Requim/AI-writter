"""保守识别直陈事实；对引语、否定、传闻和不完整句子不作硬冲突推断。"""

import json
import re
from typing import Any

from application.story_facts import source_digest, validate_assertions
from service.value_objects.chapter_constraints import ChapterConstraintSet
from service.value_objects.story_fact import FactEvidence, StoryFactAssertion, ValidationReport

UNSAFE_MARKERS = ('"', "“", "”", "‘", "’", "据说", "以为", "自称", "并非", "不是", "假", "谎", "？", "?")


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for child in value.values() for text in _strings(child)]
    if isinstance(value, list):
        return [text for child in value for text in _strings(child)]
    return []


def artifact_sentences(content: str, kind: str) -> list[str]:
    try:
        texts = _strings(json.loads(content)) if kind == "outline" else [content]
    except (ValueError, TypeError):
        return []
    return [part.strip() for value in texts for part in re.split(r"[。！!\n]", _without_quotes(value)) if part.strip()]


def _without_quotes(value: str) -> str:
    result = re.sub(r'“[^”]*”|‘[^’]*’|"[^"]*"', "\n", value, flags=re.DOTALL)
    return "" if any(mark in result for mark in ('"', "“", "”", "‘", "’")) else result


def deterministic_assertions(snapshot: ChapterConstraintSet, content: str, kind: str) -> list[StoryFactAssertion]:
    """只识别主体全名和明确属性句，不从访问祠堂、同姓或转述猜归属。"""
    claims = []
    for sentence in artifact_sentences(content, kind):
        if any(marker in sentence for marker in UNSAFE_MARKERS) or sentence not in content:
            continue
        for entity in snapshot.entities:
            statement = _literal_statement(entity, snapshot, sentence)
            if statement:
                claims.append(StoryFactAssertion(**statement, chapter_number=snapshot.chapter_number,
                    evidence=FactEvidence(source_kind="chapter_draft", source_ref="artifact:" + source_digest(content)[:24],
                        source_version=1, quote=sentence, source_hash=source_digest(content))))
    return claims


def _literal_statement(entity: Any, snapshot: ChapterConstraintSet, sentence: str) -> dict[str, Any] | None:
    name = re.escape(entity.name)
    if entity.kind == "character":
        match = re.fullmatch(name + r"(?:的姓氏是|姓)([\u4e00-\u9fff]{1,4})", sentence)
        if match:
            return {"subject_id": entity.id, "predicate": "surname", "value_text": match[1]}
    if entity.kind == "place":
        for family in snapshot.entities:
            if family.kind == "family" and sentence in {entity.name + "归" + family.name + "所有", entity.name + "属于" + family.name}:
                return {"subject_id": entity.id, "predicate": "ancestral_hall_owner", "object_entity_id": family.id}
    return None


def deterministic_report(snapshot: ChapterConstraintSet, content: str, kind: str) -> ValidationReport:
    """事务内可重新执行的无模型规则。"""
    return validate_assertions(deterministic_assertions(snapshot, content, kind), list(snapshot.fact_heads), draft=content)
