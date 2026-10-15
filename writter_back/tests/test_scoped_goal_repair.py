"""One owner-authorized goal repair never resets historical accounting."""

from copy import deepcopy
from dataclasses import replace

import pytest

from api.dependencies import get_tenant_context
from api.main import app
from application.goal_contract import evaluate_goals, fingerprint
from infrastructure.database.creative_models import CreativeSessionModel
from infrastructure.database.runtime_models import WorkflowEventModel
from sqlalchemy import select
from service.value_objects.creative_budget import budget_capacity
from tests.test_elastic_budget import activate, set_counters
from tests.test_goal_contract import report_for
from tests.test_quality_budget_accounting import staged_quality_state
from tests.test_creative_budget_grants import seed_book


def repair_fixture():
    state = staged_quality_state()
    state["revision_attempts"] = 6
    state["revision_history"].append({
        "attempt": 6, "issues_before": [{"priority_action": "must_fix"}],
        "goal_contract_id": state["chapter_outlines"][0]["goal_contract"]["id"],
    })
    raw = report_for(state)
    raw["goal_checks"][0].update(status="failed", reason="Original page not explicitly established.")
    gate = {"decision": "human_review", "score": 0.92, "hard_failures": [],
        "chapter_number": 1, "goal_review_required": True, "attempt": 6, "issues": [],
        "word_count_analysis": {"is_valid_word_count": True, "effective_density": 88},
        "goal_acceptance": evaluate_goals(state, raw, state["current_chapter_content"])}
    return state, gate


def repair_request(gate):
    return {"expected_version": 2, "expected_total": 400, "expected_spent": 57,
        "chapter": 1, "chapter_hard": 72, "additional_goal_repairs": 1,
        "content_hash": gate["goal_acceptance"]["content_hash"],
        "contract_id": gate["goal_acceptance"]["contract_id"],
        "goal_id": "ch1:must:1", "event_sequence": 123,
        "reason": "Owner approved one bounded goal repair."}


async def seeded_repair(client, repository, context, novel, monkeypatch):
    creative = await seed_book(repository, context, novel, monkeypatch)
    async with repository.async_session.begin() as session:
        row = await session.scalar(select(CreativeSessionModel).where(
            CreativeSessionModel.tenant_id == context.tenant_id, CreativeSessionModel.novel_id == novel.id))
        row.limits = {**row.limits, "total": 400}
    assert (await activate(client, novel.id, total=400)).status_code == 200
    await set_counters(repository, context, novel, {"chapter:1": 57, "preparation": 60, "review": 44})
    state, gate = repair_fixture()
    async with repository.async_session.begin() as session:
        session.add(WorkflowEventModel(tenant_id=context.tenant_id, novel_id=novel.id,
            sequence=123, run_id=novel.id,
            payload={"type": "quality", "node": "reflection_node", "data": gate}))
    return creative, state, gate


async def authorize(client, novel, payload, key="one-goal-repair"):
    return await client.put(f"/api/v1/novels/{novel}/creative/goal-repair",
        json=payload, headers={"Idempotency-Key": key})


@pytest.mark.asyncio
async def test_authorized_goal_repair_preserves_total_counters_and_is_idempotent(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative, _, gate = await seeded_repair(async_client, repository, tenant_context, sample_novel, monkeypatch)
    before = await creative.get_session(str(tenant_context.tenant_id), str(sample_novel.id))
    response = await authorize(async_client, sample_novel.id, repair_request(gate))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["limits"]["total"] == 400
    assert result["limits"]["policy"] == before["limits"]["policy"]
    assert result["counters"] == before["counters"]
    assert result["version"] == 3
    assert (await authorize(async_client, sample_novel.id, repair_request(gate))).json() == result
    duplicate = await authorize(async_client, sample_novel.id,
        {**repair_request(gate), "expected_version": 3}, "duplicate")
    assert duplicate.status_code == 409
    assert budget_capacity(result["limits"], result["counters"], "chapter:1") == 15
    assert budget_capacity(result["limits"], {"preparation": 60, "review": 44, "chapter:2": 64}, "chapter:2") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"chapter": 2}, {"chapter_hard": 73}, {"additional_goal_repairs": 2},
    {"expected_total": 401}, {"expected_spent": 56}, {"event_sequence": 124},
    {"content_hash": "f" * 64}, {"contract_id": "f" * 64}, {"goal_id": "ch1:must:2"},
])
async def test_goal_repair_rejects_scope_or_evidence_changes(
    async_client, repository, tenant_context, sample_novel, monkeypatch, change,
):
    creative, _, gate = await seeded_repair(async_client, repository, tenant_context, sample_novel, monkeypatch)
    before = await creative.get_session(str(tenant_context.tenant_id), str(sample_novel.id))
    response = await authorize(async_client, sample_novel.id, {**repair_request(gate), **change})
    assert response.status_code in {409, 422}
    assert await creative.get_session(str(tenant_context.tenant_id), str(sample_novel.id)) == before


@pytest.mark.asyncio
async def test_goal_repair_requires_owner_and_scoped_book(
    async_client, repository, tenant_context, other_tenant_context, sample_novel, monkeypatch,
):
    _, _, gate = await seeded_repair(async_client, repository, tenant_context, sample_novel, monkeypatch)
    app.dependency_overrides[get_tenant_context] = lambda: replace(tenant_context, role="member")
    assert (await authorize(async_client, sample_novel.id, repair_request(gate))).status_code == 403
    app.dependency_overrides[get_tenant_context] = lambda: other_tenant_context
    assert (await authorize(async_client, sample_novel.id, repair_request(gate))).status_code == 404


def test_scoped_replay_routes_one_local_repair_without_changing_body_or_fact_counts():
    from application.creative.scoped_goal_repair import goal_repair_command

    state, gate = repair_fixture()
    control = {**repair_request(gate), "id": fingerprint("approved"), "gate": gate}
    before = deepcopy(state)
    command = goal_repair_command(state, control)
    assert command.goto == "revision_node"
    assert "current_chapter_content" not in command.update
    assert command.update["quality_gate"]["goal_acceptance"]["status"] == "blocked"
    assert command.update["quality_gate"]["decision"] == "patch"
    issues = command.update["reflection_issues"]
    assert len(issues) == 1 and issues[0]["issue_id"] == "ch1:must:1"
    assert issues[0]["evidence"] in state["current_chapter_content"]
    assert command.update["automatic_recovery"]["attempts"] == {
        **before["automatic_recovery"]["attempts"], "质量审读": 6}
    assert state == before


@pytest.mark.parametrize("change", ["body", "goal", "chapter", "used", "other_failure", "bad_quote"])
def test_scoped_replay_refuses_stale_or_used_authorization(change):
    from application.creative.scoped_goal_repair import goal_repair_command

    state, gate = repair_fixture()
    control = {**repair_request(gate), "id": fingerprint("approved"), "gate": gate}
    actions = {
        "body": lambda: state.update(current_chapter_content="A changed body."),
        "goal": lambda: control.update(contract_id="f" * 64),
        "chapter": lambda: state.update(current_chapter_index=1),
        "used": lambda: state["revision_history"].append({"scoped_goal_repair": control["id"]}),
        "other_failure": lambda: gate["goal_acceptance"]["checks"][1].update(status="failed"),
        "bad_quote": lambda: gate["goal_acceptance"]["checks"][0].update(evidence="Invented prose."),
    }
    actions[change]()
    assert goal_repair_command(state, control) is None


def test_completed_extra_repair_still_exhausts_the_normal_quality_budget():
    from application.automatic_recovery import quality_revision_update
    from application.errors import AutomaticRecoveryExhausted

    state, _ = repair_fixture()
    state["revision_attempts"] = 7
    with pytest.raises(AutomaticRecoveryExhausted):
        quality_revision_update(state, 5)


@pytest.mark.asyncio
async def test_trusted_runtime_replays_review_and_opens_only_one_local_cycle(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    from application.creative.runtime import creative_node_scope, run_creative_node
    from application.agents.revision_node import _accept_revision
    from service.ports.model_meter import active_model_meter

    creative, state, gate = await seeded_repair(async_client, repository, tenant_context, sample_novel, monkeypatch)
    response = await authorize(async_client, sample_novel.id, repair_request(gate))
    state["creative_session_id"] = response.json()["id"]
    config = {"configurable": {"creative_repository": creative,
        "tenant_id": str(tenant_context.tenant_id), "novel_id": str(sample_novel.id),
        "_scoped_goal_repair": {"id": "forged"}, "_local_only_repair": False}}

    def unexpected_provider(state, config):
        raise AssertionError("Recovery must use the existing body-bound review without a provider call.")

    command = await run_creative_node("reflection_node", unexpected_provider, True, state, config)
    assert command.goto == "revision_node"
    next_state = {**state, **command.update}
    async with creative_node_scope("revision_node", next_state, config) as (projected, scoped):
        assert scoped["configurable"]["_local_only_repair"] is True
        await active_model_meter.get().reserve()
        accepted = _accept_revision(projected, state["current_chapter_content"] + "修复", auto_mode=True)
    assert accepted.goto == "reflection_node"
    assert accepted.update["revision_history"][-1]["scoped_goal_repair"] == response.json()["config"]["goal_repair"]["id"]
    saved = await creative.get_session(str(tenant_context.tenant_id), str(sample_novel.id))
    assert saved["counters"]["chapter:1"] == 58
    assert saved["limits"]["round"]["purpose"] == "repair_local"
    assert saved["limits"]["round"]["remaining"] == 14
    async with creative_node_scope("reflection_node", {**next_state, **accepted.update}, config) as (_, scoped):
        assert scoped["configurable"]["_scoped_goal_repair"] is None
