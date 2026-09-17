"""通过真实适配器校验事实提取契约，不依赖伪造的直接通过报告。"""
import hashlib
import json
from unittest.mock import AsyncMock

import pytest
from langgraph.types import Command

from application.errors import AutomaticRecoveryExhausted
from application.fact_evaluation import FactExtraction, evaluate_facts
from application.fact_gate_workflow import check_fact_artifact, fact_review_node
from application.fact_archive_guard import verify_fact_receipt
from application.prompts.template_loader import set_prompt_snapshot, reset_prompt_snapshot
from infrastructure.llm.base import structured_result_errors
from infrastructure.llm.openai_adapter import OpenAIAdapter
from service.value_objects.fact_gate import FACT_EXTRACTION_VERSION, FactGateReport
from tests.test_fact_gate import config, setup_gate


def response(snapshot):
    return {"coverage": "complete", "claims": [{
        "subject_id": str(snapshot.entities[0].id), "predicate": "ancestral_hall_owner",
        "object_entity_id": str(snapshot.entities[1].id), "quote": "辛家祖祠归辛家所有。",
    }], "unresolved": []}


def adapter(raw):
    value = OpenAIAdapter("test-key", "test-model", 1.0)
    value._stream_structured_response = AsyncMock(return_value=(json.dumps(raw), "stop"))
    return value


@pytest.mark.asyncio
async def test_real_adapter_accepts_data_instead_of_demanding_schema_keywords():
    snapshot = setup_gate()
    raw = response(snapshot)
    assert "properties 缺失" in structured_result_errors(raw, FactExtraction.model_json_schema())
    llm = adapter(raw)
    token = set_prompt_snapshot({"fact_judge.txt": "旧快照：$constraints $content $kind"})
    try:
        report = await evaluate_facts(snapshot, "辛家祖祠归辛家所有。", "outline", llm)
    finally:
        reset_prompt_snapshot(token)
    assert report.status == "pass"
    assert report.extraction_version == FACT_EXTRACTION_VERSION
    verify_fact_receipt(snapshot, report, "辛家祖祠归辛家所有。")
    prompt = llm._stream_structured_response.call_args.args[0][0]["content"]
    assert "旧快照" in prompt and '"required"' in prompt and '"unresolved"' in prompt
    llm._stream_structured_response.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["enum", "entity", "quote", "empty"])
async def test_protocol_fix_does_not_bypass_semantic_validation(mutation):
    snapshot = setup_gate()
    raw = response(snapshot)
    if mutation == "enum":
        raw["claims"][0]["predicate"] = "unsupported"
    if mutation == "entity":
        raw["claims"][0]["subject_id"] = "not-a-uuid"
    if mutation == "quote":
        raw["claims"][0]["quote"] = "不存在的引用"
    if mutation == "empty":
        raw = {}
    report = await evaluate_facts(snapshot, "辛家祖祠归辛家所有。", "outline", adapter(raw))
    assert report.status == "unknown"


@pytest.mark.asyncio
async def test_legacy_exhausted_failure_rechecks_once_then_keeps_new_budget():
    snapshot = setup_gate()
    cfg = config(snapshot)
    cfg["configurable"]["auto_mode"] = True
    pending = await check_fact_artifact({}, cfg, "他推开门。", "outline", Command(goto="chapter_writer_node"))
    state = {**pending.update, "automatic_recovery": {
        "chapter": 0, "attempts": {"事实审校:outline": 2, "质量审读": 1}}}
    for raw in (state["fact_reports"]["outline"], state["pending_proposal"]["payload"]["report"]):
        raw.pop("extraction_version", None)
    result = await fact_review_node(state, cfg)
    assert result.goto == "fact_review_node"
    assert result.update["fact_reports"]["outline"]["extraction_version"] == FACT_EXTRACTION_VERSION
    assert result.update["automatic_recovery"]["attempts"] == {"质量审读": 1}
    next_state = {**state, **result.update, "automatic_recovery": state["automatic_recovery"]}
    with pytest.raises(AutomaticRecoveryExhausted):
        await fact_review_node(next_state, cfg)


@pytest.mark.asyncio
async def test_legacy_exhausted_checkpoint_recovers_through_real_adapter_without_ack():
    snapshot = setup_gate()
    cfg = config(snapshot)
    cfg["configurable"]["auto_mode"] = True
    content = "辛家祖祠归辛家所有。"
    pending = await check_fact_artifact({}, cfg, content, "outline", Command(
        goto="chapter_writer_node", update={"chapter_outline_feedback": None}))
    state = {**pending.update, "automatic_recovery": {
        "chapter": 0, "attempts": {"事实审校:outline": 2}}}
    for raw in (state["fact_reports"]["outline"], state["pending_proposal"]["payload"]["report"]):
        raw.pop("extraction_version", None)
    cfg["configurable"]["llm_config"]["llm_instance"] = adapter(response(snapshot))
    result = await fact_review_node(state, cfg)
    assert result.goto == "chapter_writer_node"
    assert result.update["pending_proposal"] is None
    assert result.update["fact_artifact"] is None
    assert not result.update["fact_acknowledgements"]
    report = FactGateReport.model_validate(result.update["fact_reports"]["outline"])
    verify_fact_receipt(snapshot, report, content)


def test_legacy_report_digest_keeps_existing_human_acknowledgements_valid():
    from application.fact_evaluation import _base
    raw = {**_base(setup_gate(), "原稿", "outline"), "status": "unknown", "coverage": "unknown",
           "assertions": [], "findings": [], "reasons": [], "rule_version": "fact-gate-v1"}
    raw.pop("extraction_version")
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    assert FactGateReport.model_validate(raw).digest == digest
