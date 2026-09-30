"""题材策略审核与下游传播回归测试。"""

from unittest.mock import AsyncMock

import pytest

from application.agents.genre_strategy_node import genre_strategy_node, genre_strategy_review_node
from application.prompts.creative_brief_prompts import normalize_creative_brief
from application.prompts.genre_strategy import genre_strategy_block
from application.prompts.genre_strategy_prompts import GENRE_STRATEGY_SCHEMA, validate_genre_strategy
from application.proposals import proposal_update


def strategy():
    return {key: ["专属策略标记"] if kind == "array" else "专属策略标记"
            for key, kind in GENRE_STRATEGY_SCHEMA.items()}


@pytest.mark.parametrize("invalid", [None, [], {}, {"reader_promise": 123}])
def test_invalid_strategy_is_rejected(invalid):
    assert validate_genre_strategy(invalid)


@pytest.mark.asyncio
async def test_invalid_llm_output_does_not_silently_fallback():
    llm = AsyncMock()
    llm.structured_generate.return_value = {}
    with pytest.raises(RuntimeError, match="无效字段"):
        await genre_strategy_node({"novel_type": "suspense"}, {
            "configurable": {"llm_config": {"llm_instance": llm}, "auto_mode": True},
        })


@pytest.mark.parametrize("stage", [
    "creative_brief", "outline", "chapter_outline", "chapter_writer", "reflection",
])
def test_strategy_survives_normalization_and_enters_prompt(stage):
    brief = normalize_creative_brief({"genre_strategy": strategy()})
    assert brief["genre_strategy"] == strategy()
    assert "专属策略标记" in genre_strategy_block("suspense", brief, stage)


@pytest.mark.asyncio
async def test_automatic_review_reuses_saved_proposal_without_llm():
    state = {"novel_type": "suspense", "workflow_schema_version": 5}
    state.update(proposal_update(state, "genre_strategy", strategy()))
    result = await genre_strategy_review_node(state, {"configurable": {"auto_mode": True}})
    assert result.goto == "creative_brief_node"
    assert result.update["genre_strategy"] == strategy()
    assert result.update["pending_proposal"] is None


@pytest.mark.asyncio
async def test_existing_proposal_is_not_regenerated():
    state = {"novel_type": "suspense", "workflow_schema_version": 5}
    state.update(proposal_update(state, "genre_strategy", strategy()))
    llm = AsyncMock()
    result = await genre_strategy_node(state, {"configurable": {"llm_config": {"llm_instance": llm}}})
    assert result.goto == "genre_strategy_review_node"
    llm.structured_generate.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_checkpoint_gets_static_strategy_without_llm():
    result = await genre_strategy_node({
        "novel_type": "suspense",
        "workflow_schema_version": 5,
        "creative_brief": {"core_premise": "旧作品"},
    }, {"configurable": {"llm_config": {"llm_instance": AsyncMock()}}})
    assert result.goto == "creative_brief_node"
    assert result.update["genre_strategy"]["reader_promise"]


@pytest.mark.asyncio
async def test_enabled_strategy_does_not_use_legacy_fallback_with_creation_brief():
    llm = AsyncMock()
    llm.structured_generate.return_value = strategy()
    result = await genre_strategy_node({
        "novel_type": "suspense", "workflow_schema_version": 5,
        "genre_strategy_enabled": True,
        "creative_brief": {"core_premise": "新作品"},
    }, {"configurable": {"llm_config": {"llm_instance": llm}}})
    assert result.goto == "genre_strategy_review_node"
    llm.structured_generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_strategy_receives_book_scale_and_user_boundaries():
    llm = AsyncMock()
    llm.structured_generate.return_value = strategy()
    await genre_strategy_node({
        "novel_type": "suspense", "genre_strategy_enabled": True,
        "target_total_chapters": 1, "target_total_words": 3000,
        "creative_brief": {
            "core_premise": "借阅册调包误会",
            "content_boundaries": ["一章内收束"],
            "author_secret": "禁止泄漏的规划秘密",
        },
    }, {"configurable": {"llm_config": {"llm_instance": llm}}})
    prompt = llm.structured_generate.call_args.kwargs["prompt"]
    assert '"target_total_chapters": 1' in prompt
    assert "借阅册调包误会" in prompt and "一章内收束" in prompt
    assert "终章不得强制" in prompt
    assert "禁止泄漏的规划秘密" not in prompt
