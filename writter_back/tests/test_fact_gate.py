"""事实门禁的证据、失败关闭与人工确认边界。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langgraph.types import Command

from application.fact_evaluation import evaluate_facts
from application.fact_archive_guard import verify_fact_receipt, archive_fact_guard
from application.fact_gate_workflow import check_fact_artifact
from application.errors import QualityGateReviewRequired
from service.value_objects.fact_gate import FactGateBlockedError
from service.value_objects.story_fact import StoryEntity
from tests.test_chapter_constraints import snapshot


def setup_gate():
    value = snapshot(chapter_number=1)
    lu = StoryEntity(entity_key="lu", kind="family", name="陆家")
    return value.model_copy(update={"entities": (*value.entities, lu)})


def judge(value, content="辛家祖祠归辛家所有", **changes):
    raw = {"coverage": "complete", "claims": [{"subject_id": str(value.entities[0].id),
        "predicate": "ancestral_hall_owner", "object_entity_id": str(value.entities[1].id),
        "quote": content}], "unresolved": []}
    return SimpleNamespace(structured_generate=AsyncMock(return_value={**raw, **changes}))


def config(value, llm=None):
    store = SimpleNamespace(capture_constraints=AsyncMock(return_value=value), assert_constraints_current=AsyncMock())
    return {"configurable": {"story_fact_repository": store, "tenant_id": str(value.tenant_id),
        "novel_id": str(value.novel_id), "tenant_context": SimpleNamespace(user_id=uuid4()),
        "llm_config": {"llm_instance": llm}}}


@pytest.mark.asyncio
async def test_literal_conflict_needs_no_model_and_retains_dual_evidence():
    value = setup_gate()
    llm = judge(value)
    report = await evaluate_facts(value, "辛家祖祠归陆家所有。", "body", llm)
    assert report.status == "blocked"
    assert report.findings[0].expected_evidence.quote == "辛家祖祠归辛家所有"
    assert report.findings[0].actual_evidence.quote == "辛家祖祠归陆家所有"
    llm.structured_generate.assert_not_called()
    with pytest.raises(FactGateBlockedError):
        verify_fact_receipt(value, report, "辛家祖祠归陆家所有。", {"report_digest": report.digest})


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["辛远走进陆氏祠堂。", "据说辛家祖祠归陆家所有。",
    "“辛家祖祠归陆家所有。辛远姓陆。”", "他以为辛家祖祠归陆家所有。", "辛家祖祠不是陆家的。"])
async def test_visit_quotation_and_belief_never_become_hard_conflicts(content):
    report = await evaluate_facts(setup_gate(), content, "body", None)
    assert report.status == "unknown"
    assert not report.assertions


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"claims": []}, {"coverage": "partial"}, {"unresolved": ["指代不明"]},
    {"coverage": "invalid"}, {"claims": [{"subject_id": str(uuid4()), "predicate": "surname", "value_text": "辛", "quote": "不存在"}]}])
async def test_incomplete_or_malformed_extraction_is_unknown(changes):
    value = setup_gate()
    report = await evaluate_facts(value, "他推开门。", "body", judge(value, **changes))
    assert report.status == "unknown"
    with pytest.raises(FactGateBlockedError):
        verify_fact_receipt(value, report, "他推开门。")


@pytest.mark.asyncio
async def test_grounded_pass_is_bound_to_full_body_scope_and_snapshot():
    value, content = setup_gate(), "辛家祖祠归辛家所有。"
    report = await evaluate_facts(value, content, "body", judge(value))
    assert report.status == "pass"
    verify_fact_receipt(value, report, content)
    for altered, body in [(value, content + "新增"), (value.model_copy(update={"novel_id": uuid4()}), content)]:
        with pytest.raises(FactGateBlockedError):
            verify_fact_receipt(altered, report, body)
    with pytest.raises(FactGateBlockedError):
        verify_fact_receipt(value, report.model_copy(update={"coverage": "partial"}), content)


@pytest.mark.asyncio
async def test_unknown_acknowledgement_binds_exact_report():
    value, content = setup_gate(), "他推开门。"
    report = await evaluate_facts(value, content, "body", None)
    ack = {"report_digest": report.digest, "reviewed_by": str(uuid4()), "proposal_id": str(uuid4())}
    verify_fact_receipt(value, report, content, ack)
    with pytest.raises(FactGateBlockedError):
        verify_fact_receipt(value, report.model_copy(update={"reasons": ("证据改变",)}), content, ack)


@pytest.mark.asyncio
async def test_cancellation_propagates():
    value = setup_gate()
    llm = SimpleNamespace(structured_generate=AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await evaluate_facts(value, "他推开门。", "body", llm)


@pytest.mark.asyncio
async def test_same_artifact_retry_reuses_report_but_new_snapshot_does_not():
    value, content = setup_gate(), "他推开门。"
    llm = judge(value)
    cfg = config(value, llm)
    first = await check_fact_artifact({}, cfg, content, "body", Command(goto="router_agent"))
    second = await check_fact_artifact(first.update, cfg, content, "body", Command(goto="router_agent"))
    assert second.goto == "fact_review_node"
    assert llm.structured_generate.await_count == 1
    changed = value.model_copy(update={"fact_heads": ()})
    cfg["configurable"]["story_fact_repository"].capture_constraints.return_value = changed
    await check_fact_artifact(first.update, cfg, content, "body", Command(goto="router_agent"))
    assert llm.structured_generate.await_count == 2


@pytest.mark.asyncio
async def test_direct_rewrite_cannot_archive_unknown():
    cfg = config(setup_gate())
    cfg["configurable"]["direct_rewrite"] = True
    with pytest.raises(QualityGateReviewRequired):
        await check_fact_artifact({}, cfg, "他推开门。", "body", Command(goto="reflection_node"))


@pytest.mark.asyncio
async def test_archive_callback_uses_callers_session_and_actual_body():
    value, content = setup_gate(), "辛家祖祠归辛家所有。"
    report = await evaluate_facts(value, content, "body", judge(value))
    store = config(value)["configurable"]["story_fact_repository"]
    guard = archive_fact_guard(store, str(value.tenant_id), str(value.novel_id), value, report, None)
    session = object()
    await guard(session, SimpleNamespace(chapter_index=0, content=content))
    assert store.assert_constraints_current.call_args.args[0] is session
    with pytest.raises(FactGateBlockedError):
        await guard(session, SimpleNamespace(chapter_index=0, content=content + "改稿"))
    assert store.assert_constraints_current.await_count == 1


@pytest.mark.asyncio
async def test_semantic_conflict_is_unknown_not_hard():
    value, content = setup_gate(), "这座祖祠的真正主人是陆家。"
    llm = judge(value, content)
    llm.structured_generate.return_value["claims"][0]["object_entity_id"] = str(value.entities[-1].id)
    report = await evaluate_facts(value, content, "body", llm)
    assert report.status == "unknown"
    assert report.findings[0].severity == "unknown"
    assert report.findings[0].code == "semantic_conflict"


@pytest.mark.asyncio
async def test_manual_outline_input_must_pass_fact_gate():
    from application.agents.chapter_outline_node import chapter_outline_node
    from tests.test_workflow_flow import _chapter_outline_result, _manual_workflow_input
    outline = _chapter_outline_result()
    outline["summary"] = "辛家祖祠归陆家所有。"
    state = {**_manual_workflow_input(), "chapter_outlines_input": outline}
    command = await chapter_outline_node(state, config(setup_gate()))
    assert command.goto == "fact_review_node"
    assert command.update["fact_reports"]["outline"]["status"] == "blocked"
    assert "chapter_outlines" not in command.update


@pytest.mark.asyncio
async def test_surname_conflict_and_quoted_surname_boundary():
    from datetime import datetime, timezone
    from service.value_objects.story_fact import StoryFactVersion
    from tests.test_story_facts import evidence
    person = StoryEntity(entity_key="hero", kind="character", name="辛远")
    fact = StoryFactVersion(id=uuid4(), subject_id=person.id, predicate="surname", value_text="辛",
        version=1, created_at=datetime.now(timezone.utc), evidence=evidence("辛远姓辛"))
    value = setup_gate().model_copy(update={"entities": (person,), "fact_heads": (fact,)})
    assert (await evaluate_facts(value, "辛远姓陆。", "body", None)).status == "blocked"
    assert (await evaluate_facts(value, "“辛远姓陆。”", "body", None)).status == "unknown"
