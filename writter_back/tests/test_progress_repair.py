"""New evidence may unlock a bounded repair, never more physical spend."""

from copy import deepcopy
from dataclasses import replace

import pytest
from sqlalchemy import select

from api.dependencies import get_tenant_context
from api.main import app
from application.goal_contract import evaluate_goals, fingerprint
from infrastructure.database.creative_models import CreativeSessionModel
from tests.test_scoped_goal_repair import seeded_repair
from tests.test_goal_contract import report_for


def progress_fixture():
    from tests.test_quality_budget_accounting import staged_quality_state

    state = staged_quality_state()
    state.update(revision_attempts=7)
    state["revision_history"] += [{"attempt": n, "goal_contract_id": state["chapter_outlines"][0]["goal_contract"]["id"],
        "before_hash": fingerprint(f"old-{n}"), "after_hash": fingerprint(f"new-{n}"),
        "issues_before": [{"type": "old", "evidence": f"old finding {n}"}]} for n in (6, 7)]
    body = state["current_chapter_content"]
    issue = {"issue_id": "new", "type": "editorial_action_state", "evidence": body[:10],
        "evidence_valid": True, "priority_action": "must_fix", "issue_resolved": False}
    gate = {"chapter_number": 1, "decision": "patch", "score": 0.92,
        "word_count_analysis": {"is_valid_word_count": True, "effective_density": 88},
        "goal_acceptance": evaluate_goals(state, report_for(state), body), "issues": [issue]}
    return state, gate


def progress_request(gate):
    return {"expected_version": 2, "expected_total": 400, "expected_spent": 63,
        "mode": "progress_v1", "chapter": 1, "event_sequence": 123,
        "content_hash": gate["goal_acceptance"]["content_hash"],
        "contract_id": gate["goal_acceptance"]["contract_id"],
        "reason": "Approved evidence-led repairs within unchanged limits."}


async def progress_seed(client, repository, context, novel, monkeypatch):
    from infrastructure.database.runtime_models import WorkflowEventModel

    creative, _, _ = await seeded_repair(client, repository, context, novel, monkeypatch)
    state, gate = progress_fixture()
    async with repository.async_session.begin() as session:
        row = await session.scalar(select(CreativeSessionModel).where(CreativeSessionModel.novel_id == novel.id))
        row.counters = {"chapter:1": 63, "preparation": 60, "review": 44}
        row.limits = {**row.limits, "chapter_extension": {
            "chapter": 1, "chapter_hard": 72, "control_id": "a" * 64}}
        event = await session.get(WorkflowEventModel, (context.tenant_id, novel.id, 123))
        event.payload = {"type": "quality", "node": "reflection_node", "data": gate}
    return creative, state, gate


async def activate_progress(client, novel, payload, key="progress"):
    return await client.put(f"/api/v1/novels/{novel}/creative/repair-policy",
        json=payload, headers={"Idempotency-Key": key})


@pytest.mark.asyncio
async def test_progress_activation_never_changes_limits_or_counters(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative, _, gate = await progress_seed(async_client, repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    before = await creative.get_session(tenant, novel)
    response = await activate_progress(async_client, novel, progress_request(gate))
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["limits"] == before["limits"] and saved["counters"] == before["counters"]
    assert saved["version"] == 3
    assert (await activate_progress(async_client, novel, progress_request(gate))).json() == saved
    assert (await activate_progress(async_client, novel,
        {**progress_request(gate), "expected_version": 3}, key="stack")).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"expected_spent": 62}, {"expected_total": 401}, {"content_hash": "f" * 64},
    {"event_sequence": 124}, {"chapter_hard": 80}, {"unlimited": True},
])
async def test_progress_policy_rejects_stale_or_extra_allowances(
    async_client, repository, tenant_context, sample_novel, monkeypatch, change,
):
    creative, _, gate = await progress_seed(async_client, repository, tenant_context, sample_novel, monkeypatch)
    before = await creative.get_session(str(tenant_context.tenant_id), str(sample_novel.id))
    response = await activate_progress(async_client, sample_novel.id, {**progress_request(gate), **change})
    assert response.status_code in {409, 422}
    assert await creative.get_session(str(tenant_context.tenant_id), str(sample_novel.id)) == before


@pytest.mark.asyncio
async def test_only_scoped_owner_can_activate_progress_repairs(
    async_client, repository, tenant_context, other_tenant_context, sample_novel, monkeypatch,
):
    _, _, gate = await progress_seed(async_client, repository, tenant_context, sample_novel, monkeypatch)
    app.dependency_overrides[get_tenant_context] = lambda: replace(tenant_context, role="member")
    assert (await activate_progress(async_client, sample_novel.id, progress_request(gate))).status_code == 403
    app.dependency_overrides[get_tenant_context] = lambda: other_tenant_context
    assert (await activate_progress(async_client, sample_novel.id, progress_request(gate))).status_code == 404


def test_fresh_evidence_allows_local_repair_without_resetting_old_fact_attempts():
    from application.creative.progress_repair import progress_repair_command

    state, gate = progress_fixture()
    before = deepcopy(state)
    command = progress_repair_command(state, gate, {"version": 1, "mode": "progress_v1"}, available=9)
    assert command.goto == "revision_node"
    assert command.update["quality_gate"]["decision"] == "patch"
    recovery = command.update["automatic_recovery"]
    assert recovery["attempts"] == {**before["automatic_recovery"]["attempts"], "质量审读": 7}
    assert recovery["quality_accounting"]["completed"] == 6
    assert recovery["quality_revision_baseline"] == 0
    assert state == before


@pytest.mark.parametrize("mutation", ["unchanged", "unresolved", "stale", "goals", "capacity", "unapproved"])
def test_progress_repair_stops_without_new_evidence_or_sufficient_physical_budget(mutation):
    from application.creative.progress_repair import progress_repair_command
    from application.creative.errors import CreativePause

    state, gate = progress_fixture()
    policy, available = {"version": 1, "mode": "progress_v1"}, 9
    match mutation:
        case "unchanged":
            entry = state["revision_history"][-1]
            entry.update(before_hash=fingerprint(state["current_chapter_content"]),
                after_hash=fingerprint(state["current_chapter_content"]))
        case "unresolved":
            state["revision_history"][-1]["issues_before"] = gate["issues"]
        case "stale":
            gate["goal_acceptance"]["content_hash"] = "f" * 64
        case "goals":
            gate["goal_acceptance"]["status"] = "blocked"
        case "capacity":
            available = 8
        case _:
            policy = None
    with pytest.raises(CreativePause):
        progress_repair_command(state, gate, policy, available=available)


@pytest.mark.asyncio
async def test_nine_call_progress_cycle_respects_hard_cap_and_never_refills_closed_source(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    from application.creative.errors import CreativePause

    creative, _, gate = await progress_seed(async_client, repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    assert (await activate_progress(async_client, novel, progress_request(gate))).status_code == 200
    held = await creative.begin_budget_round(tenant, novel, "chapter:1", "new-source", "repair_progress")
    assert held["size"] == held["remaining"] == 9
    for _ in range(9):
        await creative.reserve(tenant, novel, "chapter:1", "revision_node")
    with pytest.raises(CreativePause):
        await creative.reserve(tenant, novel, "chapter:1", "revision_node")
    await creative.release_budget_round(tenant, novel, "chapter:1")
    with pytest.raises(CreativePause):
        await creative.begin_budget_round(tenant, novel, "chapter:1", "new-source", "repair_progress")
    assert (await creative.get_session(tenant, novel))["counters"]["chapter:1"] == 72


@pytest.mark.asyncio
@pytest.mark.parametrize("old_hold", [True, False])
async def test_trusted_progress_runtime_replays_and_opens_only_nine_calls(
    async_client, repository, tenant_context, sample_novel, monkeypatch, old_hold,
):
    from application.creative.runtime import creative_node_scope, run_creative_node
    from application.agents.revision_node import _accept_revision
    from service.ports.model_meter import active_model_meter

    creative, state, gate = await progress_seed(async_client, repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    result = await activate_progress(async_client, novel, progress_request(gate))
    state["creative_session_id"] = result.json()["id"]
    # Replay must remain possible when the old review hold has only nine calls.
    async with repository.async_session.begin() as session:
        row = await session.scalar(select(CreativeSessionModel).where(CreativeSessionModel.novel_id == sample_novel.id))
        hold = {"id": "old", "bucket": "chapter:1",
            "source": "old", "purpose": "repair_local", "remaining": 9, "size": 15, "status": "active"}
        row.limits = {**row.limits, "round": hold} if old_hold else row.limits
    config = {"configurable": {"creative_repository": creative, "tenant_id": tenant, "novel_id": novel}}

    def unexpected_provider(state, config):
        raise AssertionError("Must replay only the persisted failed review, never call the provider.")

    command = await run_creative_node("reflection_node", unexpected_provider, True, state, config)
    assert command.goto == "revision_node"
    assert "current_chapter_content" not in command.update
    next_state = {**state, **command.update}
    async with creative_node_scope("revision_node", next_state, config) as (projected, scoped):
        assert scoped["configurable"]["_local_only_repair"] is True
        await active_model_meter.get().reserve()
        accepted = _accept_revision(projected, state["current_chapter_content"] + "修复", auto_mode=True)
    assert accepted.goto == "reflection_node"
    assert accepted.update["revision_history"][-1]["quality_repair_progress"] == command.update["quality_gate"]["repair_progress"]
    saved = await creative.get_session(tenant, novel)
    assert saved["counters"]["chapter:1"] == 64
    assert saved["limits"]["round"]["purpose"] == "repair_progress"
    assert saved["limits"]["round"]["remaining"] == 8


@pytest.mark.asyncio
async def test_progress_postprocess_uses_existing_review_pool_and_releases_chapter_hold(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    from application.creative.runtime import run_creative_node
    from service.ports.model_meter import active_model_meter

    creative, state, gate = await progress_seed(async_client, repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    response = await activate_progress(async_client, novel, progress_request(gate))
    async with repository.async_session.begin() as session:
        row = await session.scalar(select(CreativeSessionModel).where(CreativeSessionModel.novel_id == sample_novel.id))
        row.limits = {**row.limits, "review": 60, "total": 500}
    state.update(creative_session_id=response.json()["id"], current_chapter_index=1)
    await creative.begin_budget_round(tenant, novel, "chapter:1", "postprocess source", "repair_progress")

    async def postprocess(current, config):
        meter = active_model_meter.get()
        assert meter.bucket == "review"
        await meter.reserve()
        return {"postprocessed": True}

    config = {"configurable": {"creative_repository": creative, "tenant_id": tenant, "novel_id": novel}}
    assert await run_creative_node("creative_postprocess_node", postprocess, True, state, config) == {"postprocessed": True}
    saved = await creative.get_session(tenant, novel)
    assert saved["counters"] == {"chapter:1": 63, "preparation": 60, "review": 45}
    assert saved["limits"]["round"]["status"] == "released"


@pytest.mark.asyncio
async def test_caller_cannot_enable_progress_policy_in_runtime(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    from application.creative.runtime import creative_node_scope
    from service.ports.model_meter import active_model_meter

    creative, state, _ = await progress_seed(async_client, repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    state.update(creative_session_id=(await creative.get_session(tenant, novel))["id"], current_chapter_index=1)
    config = {"configurable": {"creative_repository": creative, "tenant_id": tenant, "novel_id": novel,
        "_repair_progress_policy": {"mode": "progress_v1"}}}
    async with creative_node_scope("creative_postprocess_node", state, config) as (_, scoped):
        assert scoped["configurable"]["_repair_progress_policy"] is None
        assert active_model_meter.get().bucket == "chapter:1"


@pytest.mark.asyncio
@pytest.mark.parametrize("node_name", ["reflection_node", "persist_node"])
async def test_progress_independent_review_uses_review_pool_at_unchanged_chapter_ceiling(
    async_client, repository, tenant_context, sample_novel, monkeypatch, node_name,
):
    from application.creative.runtime import creative_node_scope
    from service.ports.model_meter import active_model_meter

    creative, state, gate = await progress_seed(async_client, repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    response = await activate_progress(async_client, novel, progress_request(gate))
    state.update(creative_session_id=response.json()["id"], current_chapter_content="Changed manuscript.")
    async with repository.async_session.begin() as session:
        row = await session.scalar(select(CreativeSessionModel).where(CreativeSessionModel.novel_id == sample_novel.id))
        row.limits = {**row.limits, "review": 60, "total": 500}
        row.counters = {**row.counters, "chapter:1": 72}
    before = await creative.get_session(tenant, novel)
    config = {"configurable": {"creative_repository": creative, "tenant_id": tenant, "novel_id": novel}}
    async with creative_node_scope(node_name, state, config):
        meter = active_model_meter.get()
        assert meter.bucket == "review"
        await meter.reserve()
    saved = await creative.get_session(tenant, novel)
    assert saved["limits"]["chapter_extension"] == before["limits"]["chapter_extension"]
    assert saved["limits"]["total"] == before["limits"]["total"]
    assert saved["counters"] == {**before["counters"], "review": 45}
    if node_name == "reflection_node":
        assert saved["limits"]["round"]["bucket"] == "review"
        assert saved["limits"]["round"]["purpose"] == "review"


@pytest.mark.asyncio
async def test_successful_progress_postprocess_closes_review_hold_without_refilling_it(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    from application.creative.runtime import run_creative_node

    creative, state, gate = await progress_seed(async_client, repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    response = await activate_progress(async_client, novel, progress_request(gate))
    async with repository.async_session.begin() as session:
        row = await session.scalar(select(CreativeSessionModel).where(CreativeSessionModel.novel_id == sample_novel.id))
        row.limits = {**row.limits, "review": 60, "total": 500}
    await creative.begin_budget_round(tenant, novel, "review", "fresh body", "review")
    state.update(creative_session_id=response.json()["id"], current_chapter_index=1)
    config = {"configurable": {"creative_repository": creative, "tenant_id": tenant, "novel_id": novel}}
    await run_creative_node("creative_postprocess_node", lambda current: {}, False, state, config)
    saved = await creative.get_session(tenant, novel)
    assert saved["limits"]["round"]["status"] == "released"


def test_legacy_editorial_protocol_replay_preserves_exhausted_counts_and_is_one_use():
    from application.creative.progress_repair import editorial_legacy_replay

    state, _ = progress_fixture()
    state["automatic_recovery"]["attempts"]["审读重试"] = 2
    state["pending_proposal"] = {"kind": "reflection", "chapter_number": 1,
        "proposal_id": "failed", "payload": {"status": "unavailable",
            "reason": "Editorial action validation failed: action predecessor is missing"}}
    original = deepcopy(state)
    command = editorial_legacy_replay(state, {"mode": "progress_v1"})
    assert command.goto == "reflection_node"
    assert "current_chapter_content" not in command.update
    assert command.update["automatic_recovery"]["attempts"] == state["automatic_recovery"]["attempts"]
    assert command.update["automatic_recovery"]["quality_revision_baseline"] == 0
    resumed = {**state, **command.update, "pending_proposal": state["pending_proposal"]}
    assert editorial_legacy_replay(resumed, {"mode": "progress_v1"}) is None
    assert state == original


@pytest.mark.parametrize("mutation", ["unapproved", "literary", "chapter", "not_failed"])
def test_protocol_replay_never_overrides_unapproved_or_other_review_failures(mutation):
    from application.creative.progress_repair import editorial_legacy_replay

    state, _ = progress_fixture()
    state["pending_proposal"] = {"kind": "reflection", "chapter_number": 1,
        "proposal_id": "failed", "payload": {"status": "unavailable",
            "reason": "Editorial action validation failed: missing action coverage"}}
    policy = {"mode": "progress_v1"}
    match mutation:
        case "unapproved":
            policy = None
        case "literary":
            state["pending_proposal"]["payload"]["reason"] = "Literary scoring unavailable"
        case "chapter":
            state["pending_proposal"]["chapter_number"] = 2
        case _:
            state["pending_proposal"]["payload"]["status"] = "ready"
    assert editorial_legacy_replay(state, policy) is None
