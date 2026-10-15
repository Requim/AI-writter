"""Catch opaque-title ranking and newly created book version regressions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.routers.novel_router import NovelCreateRequest, _creation_outline_and_progress
from api.routers.workflow_router import _seed_creative_input, _seed_initial_input
from application.agents.title_generator_node import _normalize_candidates, title_generator_node
from service.value_objects.outline import Outline
from service.value_objects.progress import Progress


def market_candidate(title, hook=8, clarity=8, **extra):
    return {"title": title, "score_version": "reader-first-v1", "hook_strength": hook,
            "promise_clarity": clarity, "audience_fit": 8, "memorability": 8,
            "naturalness": 8, "hint": "外卖员只能重来七次，每次都会失去一段记忆",
            **extra}


def test_new_titles_rank_legible_promise_ahead_of_opaque_imagery():
    result = _normalize_candidates({"candidates": [
        market_candidate("余声", hook=2, clarity=1, total_score=999),
        market_candidate("我能重来七次，但她会忘了我", hook=9, clarity=9, total_score=1),
    ]}, reader_quality_version=1)
    assert result[0]["title"] == "我能重来七次，但她会忘了我"
    assert result[0]["total_score"] == 86
    assert result[0]["score_max"] == 100
    assert result[1]["total_score"] == 41


def test_new_length_policy_accepts_grounded_long_title_without_changing_legacy():
    title = "重来七次以后我终于知道她为什么没有等我一起回家"
    assert len(title) > 16
    result = _normalize_candidates({"candidates": [market_candidate(title)]},
                                   reader_quality_version=1)
    assert result[0]["title"] == title
    assert _normalize_candidates({"candidates": [market_candidate(title)]}) == []


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -1, 11, None])
def test_invalid_market_scores_cannot_win_with_provider_total(value):
    result = _normalize_candidates({"candidates": [
        market_candidate("错误候选", hook=value, total_score=999),
        market_candidate("我能重来七次"),
    ]}, reader_quality_version=1)
    assert result[0]["title"] == "我能重来七次"
    assert result[1]["total_score"] == 0


@pytest.mark.asyncio
async def test_new_title_node_uses_market_prompt_without_discarding_story():
    llm = AsyncMock()
    llm.structured_generate.return_value = {"candidates": [market_candidate("我能重来七次")]}
    result = await title_generator_node({
        "reader_quality_version": 1, "novel_type": "romance",
        "creative_brief": {"core_premise": "每次重来都会失去一段共同记忆"},
    }, {"configurable": {"llm_config": {"llm_instance": llm}}})
    assert result.update["pending_proposal"]["payload"][0]["total_score"] == 80
    prompt = llm.structured_generate.call_args.args[0]
    assert "每次重来都会失去一段共同记忆" in prompt
    assert "promise_clarity" in prompt


def test_creation_stamps_version_even_without_planning_or_model_input():
    outline, _ = _creation_outline_and_progress(NovelCreateRequest(novel_type="romance"))
    assert outline is not None
    assert outline.reader_quality_version == 1


def test_existing_novel_cannot_be_upgraded_by_client_workflow_input():
    novel = SimpleNamespace(novel_type="romance", title="旧书", summary=None,
                            progress=Progress(), total_outline=Outline())
    data = {"reader_quality_version": 1}
    _seed_initial_input(data, novel)
    assert data["reader_quality_version"] == 0


@pytest.mark.asyncio
async def test_client_cannot_supply_reader_pass_receipt():
    data = {"reader_comprehension_receipt": {"status": "passed"},
            "reader_quality_version": 99}
    await _seed_creative_input(data, None, SimpleNamespace(), SimpleNamespace(), "unused")
    assert "reader_comprehension_receipt" not in data
    assert "reader_quality_version" not in data
