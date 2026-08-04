"""质量审读与正文修订提案的降级契约。"""

import pytest

from application.agents.reflection_node import (
    _quality_gate,
    reflection_node,
    reflection_review_node,
)
from application.agents.revision_node import revision_review_node
from application.errors import RetryableWorkflowError
from application.proposals import proposal_update


def _invalid_review() -> dict:
    return {
        "rubric_scores": {
            "causality": "优秀",
            "continuity": 4,
            "character": 4,
            "scene_function": 4,
            "voice": 4,
            "prose_specificity": 4,
            "ending_effect": 4,
        },
        "word_count_analysis": {
            "total_count": 4000,
            "effective_density": 80,
            "is_valid_word_count": True,
        },
        "issues": [],
    }


class _InvalidReviewLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.prompts: list[str] = []

    async def structured_generate(self, prompt, _schema, **_kwargs):
        self.calls += _kwargs.get("max_attempts", 3)
        self.prompts.append(prompt)
        return _invalid_review()


def test_mixed_rubric_scales_are_rejected() -> None:
    result = _invalid_review()
    result["rubric_scores"] = {
        "causality": 4,
        "continuity": 80,
        "character": 4,
        "scene_function": 4,
        "voice": 4,
        "prose_specificity": 4,
        "ending_effect": 4,
    }
    with pytest.raises(RetryableWorkflowError):
        _quality_gate(result, "正文" * 2000)


def test_declared_ten_point_scale_accepts_scores_across_boundary() -> None:
    result = _invalid_review()
    result["score_scale"] = 10
    result["rubric_scores"] = {
        "causality": 4, "continuity": 8, "character": 7,
        "scene_function": 6, "voice": 5, "prose_specificity": 9,
        "ending_effect": 8,
    }

    gate, _ = _quality_gate(result, "正文" * 2000)

    assert gate["source_score_scale"] == 10
    assert gate["rubric_scores"]["causality"] == pytest.approx(2)
    assert gate["rubric_scores"]["prose_specificity"] == pytest.approx(4.5)


def test_undeclared_cross_boundary_scale_is_rejected() -> None:
    result = _invalid_review()
    result["rubric_scores"]["causality"] = 8

    with pytest.raises(RetryableWorkflowError, match="评分字段格式无效"):
        _quality_gate(result, "正文" * 2000)


@pytest.mark.asyncio
async def test_invalid_review_retries_once_then_offers_manual_fallback() -> None:
    llm = _InvalidReviewLLM()
    state = {
        "current_chapter_index": 0,
        "current_chapter_content": "正文" * 2000,
        "chapter_outlines": [{}],
        "total_outline": {},
        "revision_attempts": 0,
    }
    config = {"configurable": {"llm_config": {"llm_instance": llm}}}

    generated = await reflection_node(state, config)

    assert generated.goto == "reflection_review_node"
    assert generated.update["pending_proposal"]["payload"]["status"] == "unavailable"
    assert llm.calls == 2
    assert len(llm.prompts) == 2
    assert "0-5" in llm.prompts[1] and "causality" in llm.prompts[1]

    review_state = {
        **state,
        **generated.update,
        "pending_proposal_decision": {
            "proposal_id": generated.update["pending_proposal"]["proposal_id"],
            "decision": "accept",
        },
    }
    accepted = await reflection_review_node(review_state, {"configurable": {}})
    assert accepted.goto == "persist_node"
    assert accepted.update["quality_gate"]["decision"] == "user_accepted_without_ai_review"
    assert llm.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(("action", "replacement"), [
    ("accept", None), ("replace", "用户替换的完整修订正文"),
])
async def test_revision_accept_audits_checkpointed_content_without_llm(
    action: str, replacement: str | None,
) -> None:
    issue = {"issue_id": "logic-1", "type": "logic"}
    state = {
        "current_chapter_index": 0, "revision_attempts": 1,
        "revision_history": [{"attempt": 1, "issues_before": []}],
        "reflection_issues": [issue],
    }
    update = proposal_update(
        state,
        "revision",
        {"revised_content": "已保存的修订正文", "preview": "已保存的修订正文"},
        1,
    )
    proposal = update["pending_proposal"]
    decision = {"proposal_id": proposal["proposal_id"], "decision": action}
    if replacement is not None:
        decision["value"] = replacement
    review_state = {**state, **update, "pending_proposal_decision": decision}

    command = await revision_review_node(review_state, {"configurable": {}})

    assert command.goto == "persist_node"
    assert command.update["current_chapter_content"] == (
        replacement or "已保存的修订正文"
    )
    assert command.update["revision_attempts"] == 2
    assert command.update["revision_history"][-1] == {
        "attempt": 2, "issues_before": [issue],
    }


@pytest.mark.asyncio
async def test_reflection_accept_preserves_review_issues() -> None:
    issues = [{"issue_id": "logic-1", "type": "logic"}]
    gate = {
        "decision": "patch", "score": 0.7, "rubric_scores": {},
        "word_count_analysis": {},
    }
    state = {"current_chapter_index": 0}
    update = proposal_update(
        state, "reflection",
        {"status": "ready", "action": "review_reflection_issues", "gate": gate, "issues": issues},
        1,
    )
    proposal = update["pending_proposal"]
    review_state = {
        **state, **update,
        "pending_proposal_decision": {
            "proposal_id": proposal["proposal_id"], "decision": "accept",
        },
    }
    command = await reflection_review_node(review_state, {"configurable": {}})
    assert command.goto == "persist_node"
    assert command.update["reflection_issues"] == issues
