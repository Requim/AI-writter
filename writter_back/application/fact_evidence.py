"""Exact draft evidence is shared by extraction and transactional receipt verification."""

import json
import re
from collections.abc import Iterator
from typing import Any

from application.story_facts import source_digest
from service.value_objects.chapter_constraints import ChapterConstraintSet
from service.value_objects.fact_gate import FactEntityMention
from service.value_objects.story_fact import FactEvidence


def _string_leaves(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, json.dumps(value, ensure_ascii=False)[1:-1]
        return
    items = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
    for key, item in items:
        escaped = str(key).replace("~", "~0").replace("/", "~1")
        yield from _string_leaves(item, path + "/" + escaped)


def literal_leaf_catalog(content: str) -> dict[str, str]:
    """Return decoded string leaves with their exact JSON Pointer locations."""
    return {path: json.loads('"' + text + '"') for path, text in _string_leaves(json.loads(content))}


def outline_mention_catalog(snapshot: ChapterConstraintSet, content: str) -> list[dict[str, str]]:
    try:
        leaves = tuple(_string_leaves(json.loads(content)))
    except json.JSONDecodeError:
        return []
    excluded = ("/plan_context/", "/tactical_context/", "/rolling_plan/", "/goal_contract/")
    leaves = tuple((path, text) for path, text in leaves
        if path and len(path) <= 512 and not path.startswith(excluded))
    grounded = {fact.subject_id for fact in snapshot.active_facts}
    grounded.update(fact.object_entity_id for fact in snapshot.active_facts if fact.object_entity_id)
    catalog = []
    for entity in snapshot.entities:
        if entity.id not in grounded or entity.name not in content:
            continue
        candidates = [(path, text) for path, text in leaves if text.count(entity.name) == 1]
        if candidates:
            path, _ = min(candidates, key=lambda item: (len(item[1]), len(item[0]), item[0]))
            catalog.append({"entity_id": str(entity.id), "quote": entity.name, "quote_path": path})
    return catalog[:100]


def outline_leaf(content: str, path: str) -> str:
    if not path.startswith("/"):
        raise ValueError("结构化引用路径必须为 JSON Pointer")
    if re.search(r"~(?![01])", path):
        raise ValueError("结构化引用路径转义无效")
    value: Any = json.loads(content)
    for raw in path[1:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value[key]
        elif isinstance(value, list) and key.isascii() and key.isdecimal() and str(int(key)) == key:
            value = value[int(key)]
        else:
            raise ValueError("结构化引用路径无效")
    if not isinstance(value, str):
        raise ValueError("结构化引用必须定位字符串叶子")
    return json.dumps(value, ensure_ascii=False)[1:-1]


def draft_evidence(content: str, kind: str, quote: str, path: str | None) -> FactEvidence:
    evidence_text = content
    if path is not None:
        if kind != "outline":
            raise ValueError("正文引用不能使用细纲结构化路径")
        evidence_text = outline_leaf(content, path)
    if not quote or evidence_text.count(quote) != 1 or quote not in content:
        raise ValueError("引用原文不存在或不唯一")
    reference = "artifact:" + source_digest(content)[:24]
    if path is not None:
        reference += ":path:" + source_digest(path)[:24]
    return FactEvidence(source_kind="chapter_draft", source_ref=reference,
        source_version=1, quote=quote, source_hash=source_digest(content))


def validate_mentions(snapshot: ChapterConstraintSet, content: str, kind: str,
                      mentions: tuple[FactEntityMention, ...]) -> None:
    entities = {entity.id: entity for entity in snapshot.entities}
    grounded_ids = {fact.subject_id for fact in snapshot.active_facts}
    grounded_ids.update(fact.object_entity_id for fact in snapshot.active_facts if fact.object_entity_id)
    for mention in mentions:
        entity = entities.get(mention.entity_id)
        if entity is None or entity.id not in grounded_ids or entity.name not in mention.evidence.quote:
            raise ValueError("实体提及缺少已确认实体与原名证据")
        expected = draft_evidence(content, kind, mention.evidence.quote, mention.quote_path)
        if mention.evidence != expected:
            raise ValueError("实体提及证据与实际稿件不匹配")
