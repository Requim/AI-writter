"""Structured evidence must identify a leaf without weakening body or receipt guards."""

import json

import pytest
from langgraph.types import Command

from application.fact_archive_guard import verify_fact_receipt
from application.fact_evaluation import evaluate_facts
from application.fact_gate_workflow import check_fact_artifact, fact_review_node
from application.automatic_recovery import AutomaticRecoveryExhausted
from service.value_objects.fact_gate import FACT_EXTRACTION_VERSION, FactGateBlockedError
from tests.test_fact_gate import config, judge, setup_gate


def outlined_judge(snapshot, quote, path):
    llm = judge(snapshot, quote)
    llm.structured_generate.return_value["claims"][0]["quote_path"] = path
    return llm


@pytest.mark.asyncio
async def test_repeated_outline_quote_is_grounded_at_one_exact_json_leaf():
    snapshot = setup_gate()
    text = "辛家祖祠归辛家所有。"
    content = json.dumps({"summary": text, "scenes": [{"result": text}]}, ensure_ascii=False)
    report = await evaluate_facts(snapshot, content, "outline", outlined_judge(snapshot, text, "/scenes/0/result"))
    assert report.status == "pass"
    verify_fact_receipt(snapshot, report, content)
    with pytest.raises(FactGateBlockedError):
        verify_fact_receipt(snapshot, report, content.replace('"summary"', '"changed_summary"'))


@pytest.mark.asyncio
async def test_json_pointer_escaped_keys_resolve_without_searching_other_leaves():
    snapshot = setup_gate()
    text = "辛家祖祠归辛家所有。"
    content = json.dumps({"a/b~c": text, "summary": text}, ensure_ascii=False)
    report = await evaluate_facts(snapshot, content, "outline", outlined_judge(snapshot, text, "/a~1b~0c"))
    assert report.status == "pass"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/missing", "/scenes/-1/result", "/scenes/00/result", "/scenes", "/bad~2key"])
async def test_invalid_outline_path_never_falls_back_to_global_quote_search(path):
    snapshot = setup_gate()
    text = "辛家祖祠归辛家所有。"
    content = json.dumps({"scenes": [{"result": text}]}, ensure_ascii=False)
    report = await evaluate_facts(snapshot, content, "outline", outlined_judge(snapshot, text, path))
    assert report.status == "unknown"


@pytest.mark.asyncio
async def test_duplicate_inside_selected_leaf_stays_unknown():
    snapshot = setup_gate()
    text = "辛家祖祠归辛家所有。"
    content = json.dumps({"summary": text * 2}, ensure_ascii=False)
    report = await evaluate_facts(snapshot, content, "outline", outlined_judge(snapshot, text, "/summary"))
    assert report.status == "unknown"


@pytest.mark.asyncio
async def test_body_cannot_use_outline_path_to_bypass_unique_quote_requirement():
    snapshot = setup_gate()
    text = "辛家祖祠归辛家所有。"
    report = await evaluate_facts(snapshot, text * 2, "body", outlined_judge(snapshot, text, "/summary"))
    assert report.status == "unknown"


@pytest.mark.asyncio
async def test_empty_complete_extraction_still_cannot_claim_fact_pass():
    snapshot = setup_gate()
    report = await evaluate_facts(snapshot, "他推开门。", "outline", judge(snapshot, claims=[]))
    assert report.status == "unknown"
    with pytest.raises(FactGateBlockedError):
        verify_fact_receipt(snapshot, report, "他推开门。")


@pytest.mark.asyncio
async def test_protocol_upgrade_rechecks_exhausted_old_failure_once_without_resetting_attempts():
    snapshot = setup_gate()
    cfg = config(snapshot)
    cfg["configurable"]["auto_mode"] = True
    pending = await check_fact_artifact({}, cfg, "他推开门。", "outline", Command(goto="chapter_writer_node"))
    state = {**pending.update, "automatic_recovery": {
        "chapter": 0, "attempts": {"事实提取:outline": 3, "质量审读": 1}}}
    for raw in (state["fact_reports"]["outline"], state["pending_proposal"]["payload"]["report"]):
        raw["extraction_version"] = "fact-extraction-v2"
    result = await fact_review_node(state, cfg)
    assert result.goto == "fact_review_node"
    assert result.update["fact_reports"]["outline"]["extraction_version"] == FACT_EXTRACTION_VERSION
    assert result.update.get("automatic_recovery", state["automatic_recovery"]) == state["automatic_recovery"]
    with pytest.raises(AutomaticRecoveryExhausted):
        await fact_review_node({**state, **result.update}, cfg)
