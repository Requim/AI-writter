"""Opening facts must reach their authorized scene rather than a hidden appendix."""

from copy import deepcopy
from importlib import import_module

import pytest

from application.agents.chapter_outline_node import _validated_outline
from application.creative.development import _pilot_context
from application.creative.runtime import _prose_outline
from application.prompts.chapter_writer_prompts import build_first_scene_prompt


def total():
    return {"reader_quality_version": 1, "total_chapters": 3,
            "author_config": {"author_mode": "autonomous_v1"},
            "main_characters": [{"character_id": "c1", "name": "陈宁"}]}


def outline():
    facts = [
        ("who", "陈宁是外卖员"), ("goal", "他来拿寄存的车钥匙"),
        ("obstacle", "车已被卖，房租今天到期"), ("hook", "能改过去，但会失去共同记忆"),
    ]
    return {
        "chapter_number": 1, "title": "钥匙", "chapter_goal": "决定是否改掉过去的一次选择",
        "reader_quality_version": 1, "chapter_intent": {
            "primary_function": "discovery", "expected_effect": "理解记忆代价",
            "subsequent_role": "下一章执行选择"},
        "entry_state": {"goal": "拿回钥匙"}, "exit_state": {"choice": "回拨电话"},
        "state_delta": "陈宁决定回拨那通错过的电话",
        "ending_mode": "choice", "estimated_word_count": 4200,
        "scenes": [{"scene_index": 1, "location": "旧出租屋", "character_ids": ["c1"],
                    "characters": ["陈宁"], "function": "discovery", "purpose": "拿回钥匙",
                    "scene_goal": "拿回钥匙", "events": {"entry": "上门拿钥匙", "result": "面对选择"},
                    "state_change": "决定回拨电话",
                    "allowed_information": [fact for _, fact in facts], "action_requirements": []}],
        "reader_entry": {
            "everyday_problem": "拿车钥匙却得知车被卖了",
            "required_information": [{"purpose": purpose, "fact": fact, "scene_index": 1}
                                     for purpose, fact in facts],
            "deferred_information": ["三年前分手的真正原因"],
        },
    }


def test_outline_rejects_entry_fact_not_authorized_in_first_scene():
    value = outline()
    value["scenes"][0]["allowed_information"].pop()
    with pytest.raises(RuntimeError, match="读者入场"):
        _validated_outline(value, 1, total())


def test_natural_assignment_keeps_hard_facts_and_separates_creative_freedom():
    value = outline()
    api = import_module("application.reader_entry")
    assignment = api.writing_assignment(value, value["scenes"][0])
    assert "陈宁是外卖员" in assignment
    assert "车已被卖，房租今天到期" in assignment
    assert "三年前分手的真正原因" not in assignment
    assert "创作空间" in assignment


def test_first_scene_consumes_new_assignment_without_leaking_deferred_truth():
    value = outline()
    prompt = build_first_scene_prompt(
        value["scenes"][0], value, "romance", "拿回钥匙", 1, "钥匙", "",
        4200, 1, {}, "", creative_brief={})
    assert "本场眼前要办的事" in prompt
    assert "陈宁是外卖员" in prompt
    assert "三年前分手的真正原因" not in prompt


def test_prose_projection_keeps_reader_entry_and_drops_deferred_answers():
    value = outline()
    value["reader_entry"]["deferred_information"] = ["幕后真相：林雨有隐藏身份"]
    projected = _prose_outline(value)
    assert projected["reader_quality_version"] == 1
    assert projected["reader_entry"]["required_information"]
    assert "隐藏身份" not in str(projected)


def test_new_pilot_gets_core_premise_and_public_rules_without_ending_truth():
    candidate = {
        "brief": {"core_premise": "每次改过去会失去共同记忆",
                  "reader_entry": {"everyday_problem": "拿车钥匙",
                                   "must_understand": ["只能改自己的选择"],
                                   "deferred_information": ["幕后隐藏身份"]},
                  "secret_ending": "最终失去全部记忆"},
        "engine": {"conflict_nodes": []}, "narrative_mode": "stable",
    }
    context = _pilot_context(candidate, reader_quality_version=1)
    assert context["core_premise"] == "每次改过去会失去共同记忆"
    assert "只能改自己的选择" in str(context)
    assert "幕后隐藏身份" not in str(context)
    assert "最终失去全部记忆" not in str(context)


def test_legacy_pilot_context_retains_its_existing_contract():
    candidate = {"brief": {"core_premise": "旧流程未提供的规则"},
                 "engine": {"conflict_nodes": []}, "narrative_mode": "stable"}
    assert "core_premise" not in _pilot_context(candidate)


def test_conflicting_entry_cannot_authorize_an_explicitly_deferred_fact():
    value = deepcopy(outline())
    value["reader_entry"]["deferred_information"] = ["能改过去，但会失去共同记忆"]
    with pytest.raises(RuntimeError, match="读者入场"):
        _validated_outline(value, 1, total())


def test_assisted_writer_and_revision_hide_new_deferred_answers():
    from application.agents.chapter_writer_node import _draft_context
    from application.agents.revision_node import _revision_outline
    from application.prompts.chapter_writer_prompts import build_chapter_writer_prompt
    value = total()
    value["author_config"] = {"author_mode": "assisted"}
    value["creative_brief"] = {"core_premise": "拿回钥匙",
                              "reader_entry": outline()["reader_entry"]}
    current = {"total_outline": value, "chapter_outlines": [outline()], "reader_quality_version": 1}
    draft = _draft_context(current, "")
    prompt = build_chapter_writer_prompt(
        draft.outline, "romance", "钥匙", "", story_bible=draft.story_bible,
        creative_brief=draft.total_outline["creative_brief"])
    revised_outline, revised_total, _, _ = _revision_outline(current)
    for material in (prompt, str(revised_outline), str(revised_total)):
        assert "三年前分手的真正原因" not in material
    assert "陈宁是外卖员" in prompt
    assert value["creative_brief"]["reader_entry"]["deferred_information"]


@pytest.mark.parametrize("version", [0, 1])
def test_assisted_context_uses_shared_deferred_boundary_for_duplicate_secrets(version):
    from application.agents.chapter_writer_node import _draft_context
    from application.agents.revision_node import _revision_outline
    value = total()
    secret = "三年前分手的真正原因"
    other_secret = "林雨其实是匿名债权人"
    value["main_plot"] = {"ending": "最后才揭晓：" + secret, "choice": "回拨电话"}
    value["creative_brief"] = {
        "secret_ending": secret,
        "reader_entry": {"deferred_information": [other_secret]},
        "core_premise": "只能改自己的选择",
    }
    chapter = outline()
    chapter["future_clue"] = other_secret
    original = deepcopy(value)
    current = {"total_outline": value, "chapter_outlines": [chapter], "reader_quality_version": version}
    draft = _draft_context(current, "")
    revised_outline, revised_total, _, _ = _revision_outline(current)
    for material in (str(draft.outline), str(draft.total_outline), draft.story_bible,
                     str(revised_outline), str(revised_total)):
        if version == 1:
            assert secret not in material and other_secret not in material
    assert "只能改自己的选择" in str(draft.total_outline)
    assert "回拨电话" in str(revised_total)
    assert value == original
    if version == 0:
        assert secret in str(draft.total_outline) and other_secret in str(draft.outline)


def test_cross_context_deferred_fact_conflict_returns_to_review():
    from application.agents.chapter_writer_node import _draft_context
    from application.errors import RetryableWorkflowError
    value = total()
    value["creative_brief"] = {"reader_entry": {"deferred_information": ["陈宁是外卖员"]}}
    with pytest.raises(RetryableWorkflowError, match="信息边界"):
        _draft_context({"total_outline": value, "chapter_outlines": [outline()],
                        "reader_quality_version": 1}, "")


@pytest.mark.parametrize("number", [2, 10])
def test_later_authorized_reveal_is_not_permanently_blocked_by_opening_brief(number):
    from application.agents.chapter_writer_node import _draft_context
    from application.agents.revision_node import _revision_outline
    value = total()
    secret = "林雨其实是匿名债权人"
    value["creative_brief"] = {"reader_entry": {"deferred_information": [secret]}}
    chapter = {"chapter_number": number, "scenes": [{"allowed_information": [secret]}]}
    current = {"total_outline": value, "chapter_outlines": [chapter],
               "reader_quality_version": 1, "current_chapter_index": number - 1}
    draft = _draft_context(current, "")
    revised, _, _, _ = _revision_outline(current)
    assert secret in str(draft.outline) and secret in str(revised)


def test_later_unauthorized_future_answer_stays_hidden_in_story_bible():
    from application.agents.chapter_writer_node import _draft_context
    value = total()
    secret = "林雨其实是匿名债权人"
    value["creative_brief"] = {"reader_entry": {"deferred_information": [secret]}}
    value["main_plot"] = {"ending": "第十章才揭晓：" + secret}
    current = {"total_outline": value, "chapter_outlines": [{
        "chapter_number": 4, "scenes": [{"allowed_information": ["陈宁来拿钥匙"]}]}],
        "reader_quality_version": 1, "current_chapter_index": 3}
    assert secret not in _draft_context(current, "").story_bible
