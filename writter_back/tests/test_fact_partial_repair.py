"""Unresolved draft assertions require revision, not identical rechecks."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langgraph.types import Command

from application.fact_gate_workflow import check_fact_artifact, fact_review_node
from tests.test_fact_gate import config, setup_gate


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,node", [
    ("outline", "chapter_outline_node"), ("body", "revision_node"),
])
async def test_partial_semantic_report_routes_back_to_draft_repair(kind, node):
    snapshot = setup_gate()
    content = json.dumps({"summary": "辛家祖祠的归属说不清。"}, ensure_ascii=False)
    reason = "稿件提及祠堂归属但主体不明确，无法核对。"
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value={
        "coverage": "partial", "claims": [], "mentions": [], "unresolved": [reason],
    }))
    cfg = config(snapshot, llm)
    cfg["configurable"]["auto_mode"] = True
    pending = await check_fact_artifact(
        {}, cfg, content, kind, Command(goto="chapter_writer_node"),
    )
    result = await fact_review_node(pending.update, cfg)
    assert result.goto == node
    feedback = (result.update["chapter_outline_feedback"] if kind == "outline"
                else result.update["user_decision"]["instructions"])
    assert reason in feedback and content in feedback
    assert "未确认" in feedback and "删除" in feedback
    assert result.update["pending_proposal"] is None
    assert not result.update.get("fact_acknowledgements")
    assert result.update["automatic_recovery"]["attempts"][f"事实审校:{kind}"] == 1
    llm.structured_generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalid_extraction_still_rechecks_without_rewriting_draft():
    cfg = config(setup_gate(), SimpleNamespace(structured_generate=AsyncMock(return_value={})))
    cfg["configurable"]["auto_mode"] = True
    pending = await check_fact_artifact(
        {}, cfg, "原稿保留", "outline", Command(goto="chapter_writer_node"),
    )
    result = await fact_review_node(pending.update, cfg)
    assert result.goto == "fact_review_node"
    assert result.update["fact_artifact"]["content"] == "原稿保留"
    assert result.update["automatic_recovery"]["attempts"]["事实提取:outline"] == 1
