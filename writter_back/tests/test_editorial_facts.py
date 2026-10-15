"""Concrete textual mistakes must not disappear behind a high model score."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.agents.reflection_node import _generate_valid_review, _quality_gate
from application.prompts.template_loader import reset_prompt_snapshot, set_prompt_snapshot


def review():
    return {
        "passed": True, "overall_quality_score": .96,
        "word_count_analysis": {
            "total_count": 100, "effective_density": 90, "is_valid_word_count": True,
        },
        "issues": [],
    }


@pytest.mark.parametrize("text", [
    "她写：已查阅，一致性待复核。\n\n六个字。",
    "他记下：不要开门。五个字。",
    "她写下：请勿触碰，原件封存。\n7个字。",
    "昨天签出时，确认单上只有六个字：已查阅，一致性待复核。",
])
def test_high_score_does_not_accept_wrong_count_of_explicit_written_text(text):
    gate, issues = _quality_gate(review(), text)
    assert gate["decision"] == "patch"
    finding = next(item for item in issues if item.get("source") == "server_text_count")
    assert finding["priority_action"] == "must_fix"
    assert finding["evidence_valid"] and finding["evidence"] in text


@pytest.mark.parametrize("text", [
    "她写：已查阅，一致性待复核。\n\n九个字。",
    "他记下：不要开门。四个字。",
    "她写下：请勿触碰，原件封存。\n8个字。",
    "“他记下：不要开门。五个字。”她复述了那句错误的话。",
    "她想了六个字，最后没有写出来。",
    "她写：ABC-12。六个字。",
    "确认单上只有九个字：已查阅，一致性待复核。",
])
def test_count_check_does_not_infer_counts_or_correct_character_dialogue(text):
    gate, issues = _quality_gate(review(), text)
    assert gate["decision"] == "pass" and not issues


@pytest.mark.asyncio
async def test_copyediting_contract_is_added_even_with_legacy_prompt_snapshot():
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value=review()))
    token = set_prompt_snapshot({"reflection/editorial_checks.txt": "旧审读模板"})
    try:
        await _generate_valid_review(llm, "当前正文", {"issues": "array"})
    finally:
        reset_prompt_snapshot(token)
    prompt = llm.structured_generate.await_args.args[0]
    assert "动作状态" in prompt and "逐字复算" in prompt
    assert "不能编造" in prompt and "原文" in prompt
    llm.structured_generate.assert_awaited_once()
