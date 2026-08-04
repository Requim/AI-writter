"""章节新增长期角色时的保留姓名校验与消费。"""

from __future__ import annotations

from typing import Any, Mapping

from application.naming import NamingValidationError, hydrate_candidate


def _policy(outline: Mapping[str, Any]) -> dict[str, Any]:
    brief = outline.get("creative_brief")
    brief = brief if isinstance(brief, Mapping) else {}
    policy = brief.get("naming_policy")
    return dict(policy) if isinstance(policy, Mapping) else {}


def _reserve_index(outline: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    reserve = _policy(outline).get("reserve_pool", [])
    values = reserve if isinstance(reserve, list) else []
    return {
        str(item.get("candidate_id")): dict(item)
        for item in values if isinstance(item, Mapping) and item.get("candidate_id")
    }


def _profile(value: Any, character_id: str) -> dict[str, str]:
    raw = value if isinstance(value, Mapping) else {}
    fields = ("identity", "story_function", "relationship_anchor")
    profile = {field: str(raw.get(field, "")).strip() for field in fields}
    missing = [field for field, item in profile.items() if not item]
    if missing:
        raise NamingValidationError([f"新增长期角色 {character_id} profile 缺少: {', '.join(missing)}"])
    return profile


def hydrate_reserved_introductions(
    chapter_outline: Mapping[str, Any], total_outline: Mapping[str, Any],
) -> dict[str, Any]:
    """根据当前总纲保留池回填新增长期角色，拒绝模型自造姓名。"""
    result = dict(chapter_outline)
    raw_items = result.get("new_long_term_characters", [])
    values = raw_items if isinstance(raw_items, list) else []
    reserve = _reserve_index(total_outline)
    existing = {
        str(item.get("character_id")) for item in total_outline.get("main_characters", [])
        if isinstance(item, Mapping)
    }
    hydrated = [_hydrate_introduction(item, reserve, existing) for item in values]
    ids = [item["character_id"] for item in hydrated]
    candidate_ids = [item["candidate_id"] for item in hydrated]
    if len(ids) != len(set(ids)) or len(candidate_ids) != len(set(candidate_ids)):
        raise NamingValidationError(["新增长期角色重复使用 character_id 或保留姓名"])
    result["new_long_term_characters"] = hydrated
    return result


def _hydrate_introduction(
    value: Any, reserve: Mapping[str, dict[str, Any]], existing: set[str],
) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {}
    character_id = str(raw.get("character_id", "")).strip()
    candidate_id = str(raw.get("candidate_id", "")).strip()
    stored = reserve.get(candidate_id)
    if not character_id or character_id in existing:
        raise NamingValidationError([f"新增长期角色 character_id 无效: {character_id}"])
    if stored is None:
        raise NamingValidationError([f"保留姓名不存在或已消费: {candidate_id}"])
    candidate = hydrate_candidate({"surname": stored.get("surname"), "source_id": stored.get("source_id")})
    return {
        "character_id": character_id, "candidate_id": candidate_id,
        "role_type": str(raw.get("role_type") or "long_term_supporting"),
        "name": candidate.name, "surname": candidate.surname,
        "origin_type": "classical_source", "source_id": candidate.source.source_id,
        "source": candidate.source.attribution(), "profile": _profile(raw.get("profile"), character_id),
    }


def consume_reserved_introductions(
    total_outline: Mapping[str, Any], chapter_outline: Mapping[str, Any],
) -> dict[str, Any]:
    """接受章节细纲时从保留池移除姓名，并加入规范化角色表。"""
    introductions = chapter_outline.get("new_long_term_characters", [])
    values = introductions if isinstance(introductions, list) else []
    if not values:
        return dict(total_outline)
    consumed = {str(item.get("candidate_id")) for item in values if isinstance(item, Mapping)}
    result = dict(total_outline)
    brief = dict(result.get("creative_brief") or {})
    policy = _policy(result)
    reserve = policy.get("reserve_pool", [])
    policy["reserve_pool"] = [
        item for item in reserve if isinstance(item, Mapping)
        and str(item.get("candidate_id")) not in consumed
    ]
    brief["naming_policy"] = policy
    result["creative_brief"] = brief
    characters = list(result.get("main_characters") or [])
    result["main_characters"] = [*characters, *[dict(item) for item in values]]
    return result
