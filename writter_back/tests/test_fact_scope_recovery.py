"""A scope-contract migration rechecks evidence without resetting spent repair."""

from copy import deepcopy
import hashlib

import pytest
from langgraph.types import Command

from application.errors import AutomaticRecoveryExhausted
from application.fact_evaluation import _extraction_prompt
from application.fact_gate_workflow import check_fact_artifact, fact_review_node
from application.orchestrator import NovelOrchestrator
from application.prompts.template_loader import reset_prompt_snapshot, set_prompt_snapshot
from tests.test_fact_gate import config, judge, setup_gate


async def _old_partial():
    value, body = setup_gate(), "辛家祖祠归辛家所有。残缺签收页的来源仍待查。"
    cfg = config(value, judge(value, coverage="partial", unresolved=["签收页来源尚未查清"]))
    cfg["configurable"]["auto_mode"] = True
    pending = await check_fact_artifact({}, cfg, body, "body", Command(goto="reflection_node"))
    state = pending.update
    report = deepcopy(state["fact_reports"]["body"])
    report["extraction_version"] = "fact-extraction-v4"
    state["fact_reports"]["body"] = report
    state["pending_proposal"]["payload"]["report"] = report
    state["automatic_recovery"] = {
        "chapter": 0, "attempts": {"事实审校:body": 2, "事实提取:body": 1, "质量审读": 1},
    }
    cfg["configurable"]["llm_config"]["llm_instance"] = judge(value)
    return value, body, cfg, state


@pytest.mark.asyncio
async def test_old_partial_rechecks_with_remaining_extraction_budget_not_new_prose_repairs():
    _value, body, cfg, state = await _old_partial()
    before = deepcopy(state)
    result = await fact_review_node(state, cfg)
    assert result.goto == "reflection_node"
    assert result.update["fact_reports"]["body"]["status"] == "pass"
    assert result.update["fact_reports"]["body"]["artifact_hash"] == hashlib.sha256(body.encode()).hexdigest()
    assert result.update["fact_reports"]["body"]["extraction_version"] == "fact-extraction-v5"
    assert result.update["automatic_recovery"]["attempts"] == {
        "事实审校:body": 2, "事实提取:body": 2, "质量审读": 1,
    }
    assert not result.update["fact_acknowledgements"] and state == before


@pytest.mark.asyncio
async def test_old_partial_cache_does_not_block_new_scope_evaluation():
    _value, body, cfg, state = await _old_partial()
    result = await check_fact_artifact(state, cfg, body, "body", Command(goto="reflection_node"))
    assert result.goto == "reflection_node"
    assert result.update["fact_reports"]["body"]["extraction_version"] == "fact-extraction-v5"
    assert result.update["fact_reports"]["body"]["status"] == "pass"
    assert result.update["fact_acknowledgements"] == {}


@pytest.mark.asyncio
async def test_explicit_protocol_migration_retry_keeps_all_spent_counters():
    _value, _body, _cfg, state = await _old_partial()
    before = deepcopy(state)
    assert NovelOrchestrator._reset_fact_retry_budget(state, "fact_review_node") == {}
    assert state == before


@pytest.mark.asyncio
async def test_new_scope_uncertainty_still_stops_at_existing_semantic_repair_limit():
    value, _body, cfg, state = await _old_partial()
    cfg["configurable"]["llm_config"]["llm_instance"] = judge(
        value, coverage="partial", unresolved=["已登记祠堂归属的实际断言无法确认"],
    )
    fresh = await fact_review_node(state, cfg)
    assert fresh.goto == "fact_review_node"
    updated = {**state, **fresh.update}
    assert updated["automatic_recovery"]["attempts"]["事实审校:body"] == 2
    with pytest.raises(AutomaticRecoveryExhausted, match="事实审校"):
        await fact_review_node(updated, cfg)
    assert not updated.get("fact_acknowledgements")


def test_old_frozen_judge_does_not_restore_out_of_scope_mystery_requirements():
    token = set_prompt_snapshot({
        "fact_judge.txt": "EVERY_UNSOLVED_PLOT_CLUE_MUST_BE_UNRESOLVED $constraints $kind $content",
    })
    try:
        prompt = _extraction_prompt(setup_gate(), "纸页来源仍待查。", "body")
    finally:
        reset_prompt_snapshot(token)
    assert "EVERY_UNSOLVED_PLOT_CLUE_MUST_BE_UNRESOLVED" not in prompt
    assert "纸页来源仍待查。" in prompt and "surname" in prompt and "life_status" in prompt
