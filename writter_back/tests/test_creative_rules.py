"""六项能力的确定性边界，不将模型或静态测试视为真实读者验证。"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from application.creative.errors import CreativePause
from application.creative.evidence import content_hash, validate_character_transition, verify_evidence
from application.creative.feedback import evaluate_experiment, feedback_hypotheses
from application.creative.policy import choose_route, select_candidate, validate_replan
from application.creative.projection import project_context
from application.creative.scenes import validate_scene_contract
from infrastructure.database.creative_repository import increment_budget
from service.value_objects.creative import AuthorConfiguration, BudgetLimits, CharacterNarrative, TextEvidence
from service.value_objects.reader_feedback import BlindJudgment, FeedbackExperiment, ReaderFeedback


def evidence(start=0):
    text = "归档正文第一段，归档正文第二段。"
    return TextEvidence(
        chapter_id=uuid4(), chapter_version=1, chapter_number=1,
        content_hash=content_hash(text), start=start, end=start + 2, quote=text[start:start + 2],
    )


@pytest.mark.parametrize("chapters", [1, 4, 5, 6, 200])
def test_default_budget_formula(chapters):
    limits = BudgetLimits().resolved(chapters)
    assert limits["total"] == 80 + 40 * chapters
    assert limits["review"] == 20 + 8 * chapters


def test_budget_unknown_requests_are_not_refunded():
    limits = BudgetLimits(preparation=1).resolved(1)
    counters = increment_budget(limits, {}, "preparation")
    with pytest.raises(CreativePause, match="耗尽"):
        increment_budget(limits, counters, "preparation")
    assert counters == {"preparation": 1}


def test_search_debits_both_pools_atomically():
    limits = BudgetLimits(search=1, preparation_search=1).resolved(1)
    counters = increment_budget(limits, {}, "preparation_search")
    assert counters == {"search": 1, "preparation_search": 1}
    with pytest.raises(CreativePause):
        increment_budget(limits, counters, "search")


def test_reader_projection_never_contains_future_or_secrets():
    result = project_context("reader", {
        "truth": "凶手秘密", "novel_plan": {"ending": "未发生"},
        "reader_state": {"known": ["门锁坏了"], "secret": "凶手秘密"},
        "chapters": [{"status": "draft", "content": "草稿秘密"}, {"status": "completed", "content": "归档正文"}],
    })
    assert result == {"reader_state": {"known": ["门锁坏了"]}, "chapters": [{"content": "归档正文"}]}


def test_scene_projection_is_id_scoped_and_drops_secret_fields():
    result = project_context("scene", {
        "characters": [
            {"character_id": "one", "name": "同名", "secret": "秘密一"},
            {"character_id": "two", "name": "同名", "secret": "秘密二"},
        ], "secret": "全书秘密",
    }, character_ids=("one",))
    assert result["characters"] == [{"character_id": "one", "name": "同名"}]
    assert "秘密" not in str(result)


@pytest.mark.parametrize("function", ["setup", "aftermath", "relationship", "discovery"])
def test_quiet_chapter_does_not_require_tactics_or_reversal(function):
    outline = {
        "chapter_number": 1, "chapter_goal": "整理失去亲人的情绪",
        "chapter_intent": {"primary_function": function, "expected_effect": "接受失落", "subsequent_role": "愿意求助"},
        "scenes": [{"function": function, "purpose": "接受失落", "state_change": "愿意求助"}],
        "entry_state": {"feeling": "拒绝"}, "exit_state": {"feeling": "接受"}, "state_delta": "关系靠近",
    }
    assert validate_scene_contract(outline, 1) == []


def test_no_route_is_a_valid_result():
    assert choose_route([]) == {"status": "no_feasible_route"}
    with pytest.raises(ValueError):
        choose_route([{}, {}, {}])


def test_confirmed_death_cannot_be_reversed_by_rumor():
    previous = CharacterNarrative(character_id="a", name="甲", life_status="dead")
    changed = previous.model_copy(update={"life_status": "alive", "evidence": [evidence()]})
    with pytest.raises(CreativePause, match="死亡"):
        validate_character_transition(previous, changed)


def test_archived_evidence_checks_version_and_quote():
    proof = evidence()
    chapter = {
        "id": str(proof.chapter_id), "version": 1, "chapter_index": 0,
        "content": "归档正文第一段，归档正文第二段。", "status": "completed",
    }
    verify_evidence(proof, chapter)
    with pytest.raises(ValueError, match="不同章节版本"):
        verify_evidence(proof, {**chapter, "version": 2})
    with pytest.raises(ValueError, match="草稿"):
        verify_evidence(proof, {**chapter, "status": "draft"})


@pytest.mark.parametrize("chapter,total", [(1, 1), (1, 4), (1, 5), (2, 6), (196, 200)])
def test_last_five_chapters_freeze_ending(chapter, total):
    with pytest.raises(CreativePause, match="结局"):
        validate_replan(chapter=chapter, total=total, ending_changes=0, changes_ending=True, accepted_windows=[])


def test_one_comment_and_duplicate_readers_do_not_trigger_experiment():
    item = ReaderFeedback(source="human_reader", reader_id="one", issue_key="slow", category="pace", comment="慢", evidence=[evidence()])
    report = feedback_hypotheses([item, item, item])[0]
    assert report["independent_readers"] == 1
    assert not report["auto_experiment_eligible"]


def test_three_independent_readers_and_two_locations_trigger_only_candidate():
    items = [ReaderFeedback(
        source="human_reader", reader_id=str(i), issue_key="slow", category="pace",
        comment="慢", evidence=[evidence(i)],
    ) for i in range(3)]
    result = feedback_hypotheses(items)[0]
    assert result["auto_experiment_eligible"]
    assert result["status"] == "candidate"


def experiment():
    judgments = [BlindJudgment(evaluator_id="model", source="model", order=order, winner="B", reason="更连贯") for order in ("AB", "BA")]
    return FeedbackExperiment(
        issue_key="slow", factor="缩短重复内心独白", scene_id="scene1", hypothesis_ids=["h1"],
        created_after_chapter=5, variant_a="原始样稿", variant_b="单因素样稿",
        quality_pass=True, judgments=judgments,
    )


def test_model_support_is_not_human_verification_and_expires():
    trial = evaluate_experiment(experiment(), 5)
    assert trial.status == "model_supported_trial"
    assert (trial.trial_start, trial.trial_end) == (6, 10)
    assert evaluate_experiment(trial, 10).status == "revoked"


def test_human_majority_requires_three_distinct_readers():
    trial = experiment()
    humans = [BlindJudgment(evaluator_id=str(i), source="human", order="AB", winner="B" if i < 2 else "A", reason="追读") for i in range(3)]
    assert evaluate_experiment(trial.model_copy(update={"judgments": trial.judgments + humans}), 6).status == "human_supported"
    duplicate = [humans[0]] * 3
    assert evaluate_experiment(trial.model_copy(update={"judgments": trial.judgments + duplicate}), 6).status != "human_supported"


def test_configuration_rejects_oversized_sources():
    with pytest.raises(ValueError):
        AuthorConfiguration(sources=[{
            "title": "资料", "text": "文" * 50001, "category": "traceable_fact",
            "observed_at": datetime.now(timezone.utc), "applicable_scope": "背景",
        }])


def test_selection_has_stable_ties_and_never_uses_market_scores():
    base = {
        "quality_pass": True, "hard_constraints_pass": True,
        "scores": dict(continue_reading=80, clarity=80, payoff=80, sustainability=80),
        "evaluation_source": "blind_pilot_and_independent_plan",
    }
    assert select_candidate([{**base, "index": 2}, {**base, "index": 1}])["index"] == 1
    with pytest.raises(ValueError):
        select_candidate([{**base, "index": 1, "evaluation_source": "model_market_guess"}])
