"""书名的文学导向、候选契约与旧快照兼容性回归。"""
import pytest
from unittest.mock import AsyncMock

from application.agents.title_generator_node import (
    _normalize_candidates, title_generator_node, title_review_node,
)
from application.prompts.title_prompts import build_title_prompt


def candidate(title, literary=8, **extra):
    return {"title": title, "literary_quality": literary, "specificity": 8,
            "audience_fit": 8, "memorability": 8, **extra}


def test_literary_scores_override_model_total_without_rewarding_length():
    result = _normalize_candidates({"candidates": [
        candidate("一场改变所有人命运的调查", literary=2, total_score=999),
        candidate("余灯", literary=9, total_score=1),
    ]})
    assert result[0]["title"] == "余灯"
    assert result[0]["total_score"] == 84
    assert result[1]["total_score"] == 56


def test_short_titles_and_common_words_are_not_rejected():
    names = ["渡", "余灯", "旧车站", "归来", "月" * 17]
    result = _normalize_candidates({"candidates": [candidate(name) for name in names]})
    assert [item["title"] for item in result] == ["余灯", "旧车站", "归来"]


def test_candidates_are_unwrapped_deduplicated_and_require_string_titles():
    result = _normalize_candidates({"candidates": [
        candidate("《余灯》"), candidate("余灯"), candidate(123),
        candidate({"name": "余灯"}), candidate("旧站\n说明"), None,
    ]})
    assert [item["title"] for item in result] == ["余灯"]


@pytest.mark.parametrize("value", ["NaN", float("inf"), -1, 11, "bad", None])
def test_invalid_dimension_cannot_win_with_fabricated_total(value):
    result = _normalize_candidates({"candidates": [
        candidate("失效评分", literary=value, total_score=999),
        candidate("正常候选"),
    ]})
    assert result[0]["title"] == "正常候选"
    assert result[1]["total_score"] == 0


def test_partial_new_scores_do_not_fall_back_to_untrusted_total():
    result = _normalize_candidates({"candidates": [
        {"title": "遗漏评分", "literary_quality": 9, "total_score": 999},
        {"title": "旧版候选", "total_score": 32},
    ]})
    assert result[0]["title"] == "旧版候选"
    assert result[1]["total_score"] == 0


@pytest.mark.parametrize("genre", ["现实", "悬疑", "言情", "科幻", "奇幻"])
def test_prompt_preserves_genre_and_story_without_fixed_example_titles(genre):
    prompt = build_title_prompt(genre, {"core_conflict": "女儿接管即将关闭的修表铺"})
    assert genre in prompt and "女儿接管即将关闭的修表铺" in prompt
    assert "允许 2-3 字书名" in prompt
    assert "literary_quality" in prompt and "memorability" in prompt
    assert "不是所有题材都要变成古风诗句" in prompt
    assert "不得为了名字另编情节" in prompt
    assert "4-16 个汉字" not in prompt


@pytest.mark.asyncio
async def test_user_title_is_preserved_without_model_calls():
    result = await title_generator_node({"title": "渡"}, {"configurable": {}})
    assert result.goto == "summary_node"


@pytest.mark.asyncio
async def test_automatic_selection_uses_recomputed_score_and_persists_story_hint():
    llm = AsyncMock()
    llm.structured_generate.return_value = {"candidates": [
        candidate("修表铺的危机与最后的选择", literary=2, total_score=100),
        candidate("余灯", literary=9, hint="修表铺闭店后仍亮着的灯映照父女未解的心事"),
    ]}
    state = {"novel_type": "现实", "creative_brief": {"core_conflict": "父女面对修表铺闭店"}}
    config = {"configurable": {"auto_mode": True, "llm_config": {"llm_instance": llm}}}
    generated = await title_generator_node(state, config)
    accepted = await title_review_node({**state, **generated.update}, config)
    assert generated.goto == "title_review_node"
    assert accepted.goto == "metadata_persist_node"
    assert accepted.update["title"] == "余灯"
    assert accepted.update["title_story_hint"] == "修表铺闭店后仍亮着的灯映照父女未解的心事"
    llm.structured_generate.assert_awaited_once()
