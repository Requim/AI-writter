"""审读输出与修订反馈的跨节点契约。"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.agents.reflection_node import _generate_valid_review
from application.agents.revision_node import _full_revision_prompt, _generate_full
from application.prompts.reflection_prompts import AGGREGATION_SCHEMA, build_aggregation_prompt
from infrastructure.llm.base import structured_result_errors
from tests.test_quality_review_proposals import _invalid_review


def test_aggregation_example_matches_server_schema():
    prompt = build_aggregation_prompt([], "正文", {}, [], "", 2)
    example = json.loads(prompt[prompt.index('{\n  "score_scale"'):])
    assert structured_result_errors(example, AGGREGATION_SCHEMA) == []


@pytest.mark.asyncio
async def test_review_includes_schema_even_with_legacy_prompt():
    result = _invalid_review()
    result["rubric_scores"]["causality"] = 4
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value=result))
    await _generate_valid_review(llm, "旧提示词未声明战术字段", AGGREGATION_SCHEMA)
    prompt = llm.structured_generate.await_args.args[0]
    assert '"tactical_fulfillment"' in prompt
    assert '"exit_hook_established"' in prompt


def test_directed_revision_receives_unresolved_evidence():
    state = {
        "user_decision": {"instructions": "全文修订"},
        "reflection_issues": [
            {"issue_id": "paper-1", "description": "同一栏印刷与手写互斥",
             "evidence": "这一栏印的是", "priority_action": "must_fix"},
            {"issue_id": "fixed-1", "issue_resolved": True, "description": "已解决"},
        ],
    }
    prompt, _, _ = _full_revision_prompt(state, "当前正文", {}, "", "")
    assert "paper-1" in prompt
    assert "这一栏印的是" in prompt
    assert "fixed-1" not in prompt


@pytest.mark.asyncio
async def test_full_revision_separates_prose_from_review(monkeypatch):
    collect = AsyncMock(return_value="修订正文")
    monkeypatch.setitem(_generate_full.__globals__, "collect_streamed_text", collect)
    monkeypatch.setitem(_generate_full.__globals__, "emit_workflow_event", lambda *_: None)
    assert await _generate_full(object(), "生成正文", 0.5, 1) == "修订正文"
    instruction = collect.await_args.kwargs["system_prompt"]
    assert "不输出 JSON" in instruction
    assert "goal_checks" in instruction
