"""章节保留姓名池的校验与消费测试。"""

import pytest

from application.naming import NamingValidationError, build_candidate_pool
from application.reserved_names import (
    consume_reserved_introductions,
    hydrate_reserved_introductions,
)


def _total_outline() -> dict:
    pool = build_candidate_pool(
        tenant_id="tenant", novel_id="novel", proposal_version=1,
        prompt_version="2026-08-03.2", count=24,
    )
    return {
        "main_characters": [{"character_id": "lead", "name": "顾清扬"}],
        "creative_brief": {
            "naming_policy": {"reserve_pool": [item.to_dict() for item in pool]}
        },
    }


def _introduction(candidate_id: str) -> dict:
    return {
        "new_long_term_characters": [{
            "character_id": "witness-2", "candidate_id": candidate_id,
            "role_type": "long_term_supporting",
            "profile": {
                "identity": "旧案证人", "story_function": "推动真相第二阶梯",
                "relationship_anchor": "欠主角父亲一份人情",
            },
        }]
    }


def test_reserved_name_is_hydrated_then_consumed_from_total_outline() -> None:
    total = _total_outline()
    stored = total["creative_brief"]["naming_policy"]["reserve_pool"][0]
    outline = hydrate_reserved_introductions(_introduction(stored["candidate_id"]), total)
    character = outline["new_long_term_characters"][0]
    updated = consume_reserved_introductions(total, outline)
    remaining = updated["creative_brief"]["naming_policy"]["reserve_pool"]
    assert character["name"] == stored["name"]
    assert character["source"]["quote"] == stored["source"]["quote"]
    assert character in updated["main_characters"]
    assert len(remaining) == 23


def test_unknown_or_consumed_reserved_candidate_is_rejected() -> None:
    with pytest.raises(NamingValidationError, match="不存在或已消费"):
        hydrate_reserved_introductions(_introduction("stale-candidate"), _total_outline())


def test_chapter_without_new_long_term_character_does_not_consume_pool() -> None:
    total = _total_outline()
    outline = hydrate_reserved_introductions({}, total)
    updated = consume_reserved_introductions(total, outline)
    reserve = updated["creative_brief"]["naming_policy"]["reserve_pool"]
    assert len(reserve) == 24
    assert outline["new_long_term_characters"] == []
