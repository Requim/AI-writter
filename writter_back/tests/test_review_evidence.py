from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.review_evidence import repair_goal_quotes


def contract():
    return {"requirements": [{"id": "event-1", "expected": "递交申请并收到回执"}]}


@pytest.mark.asyncio
async def test_invalid_citation_is_rechecked_without_changing_prose_or_quality():
    content = "他递交申请。\n她盖章，交还回执。"
    row = {"id": "event-1", "status": "passed", "evidence": "他递交申请……交还回执。"}
    fixed = {**row, "evidence": content, "reason": "申请与回执均有动作"}
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value={"goal_checks": [fixed]}))
    original = {"goal_checks": [row], "rubric_scores": {"continuity": 4}}
    result = await repair_goal_quotes(llm, original, content, contract())
    assert result["goal_checks"] == [fixed]
    assert result["rubric_scores"] == original["rubric_scores"]
    assert original["goal_checks"] == [row]
    llm.structured_generate.assert_awaited_once()
    assert content in llm.structured_generate.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["passed", "failed", "unknown"])
async def test_valid_evidence_and_real_goal_failures_are_not_overridden(status):
    result = {"goal_checks": [{"id": "event-1", "status": status, "evidence": "原文"}]}
    llm = SimpleNamespace(structured_generate=AsyncMock())
    assert await repair_goal_quotes(llm, result, "原文", contract()) is result
    llm.structured_generate.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_repair_does_not_invent_pass():
    row = {"id": "event-1", "status": "passed", "evidence": "不存在"}
    result = {"goal_checks": [row]}
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value={"goal_checks": []}))
    assert await repair_goal_quotes(llm, result, "当前正文", contract()) == result
