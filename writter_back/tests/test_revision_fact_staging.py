"""Fact-staged candidates need a fresh proposal, never a stale-source waiver."""

from copy import deepcopy
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from application.agents.revision_node import _next_after_revision, revision_review_node
from application.errors import RetryableWorkflowError
from application.fact_gate_workflow import check_fact_artifact, fact_review_node
from tests.test_fact_gate import config, judge, setup_gate
from tests.test_goal_contract import goal_state


async def _staged_fixture():
    state, snapshot = goal_state(), setup_gate()
    revised = "辛家祖祠归辛家所有。" + state["current_chapter_content"]
    cfg = config(snapshot)
    cfg["configurable"]["auto_mode"] = True
    continuation = _next_after_revision(state, revised)
    pending = await check_fact_artifact(state, cfg, revised, "body", continuation)
    state.update(pending.update)
    cfg["configurable"]["llm_config"]["llm_instance"] = judge(snapshot)
    checked = await fact_review_node(state, cfg)
    state.update(checked.update)
    assert checked.goto == "revision_review_node"
    assert state["fact_reports"]["body"]["status"] == "pass"
    return state, cfg


@pytest.mark.asyncio
async def test_fact_staging_creates_new_source_bound_proposal_before_quality_review():
    state, cfg = await _staged_fixture()
    before = deepcopy(state)
    old = state["pending_proposal"]
    command = await revision_review_node(state, cfg)
    assert command.goto == "revision_review_node"
    assert "current_chapter_content" not in command.update
    fresh = command.update["pending_proposal"]
    assert fresh["proposal_id"] != old["proposal_id"] and fresh["version"] == old["version"] + 1
    assert fresh["payload"]["revised_content"] == old["payload"]["revised_content"]
    assert fresh["payload"]["source_hash"] == hashlib.sha256(state["current_chapter_content"].encode()).hexdigest()
    assert fresh["payload"]["contract_id"] == old["payload"]["contract_id"]
    provenance = fresh["payload"]["fact_staging_rebind"]
    assert provenance["proposal_id"] == old["proposal_id"]
    assert provenance["source_hash"] == old["payload"]["source_hash"]
    assert len(provenance["fact_report_digest"]) == 64
    assert state == before and "automatic_recovery" not in command.update
    state.update(command.update)
    accepted = await revision_review_node(state, cfg)
    assert accepted.goto == "reflection_node" and accepted.update["pending_proposal"] is None
    assert accepted.update["revision_history"][-1]["fact_staging_rebind"] == provenance
    assert not accepted.update.get("quality_gate") and not accepted.update.get("fact_acknowledgements")
    assert cfg["configurable"]["llm_config"]["llm_instance"].structured_generate.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", [
    "body", "contract", "missing_receipt", "old_version", "unknown", "hash", "tenant",
    "source_missing", "already_rebound", "snapshot", "canonical_conflict",
    "repository_missing", "fresh_snapshot",
])
async def test_stale_or_unverified_candidate_cannot_be_rebound(problem):
    state, cfg = await _staged_fixture()
    payload, report = state["pending_proposal"]["payload"], state["fact_reports"]["body"]
    snapshot = cfg["configurable"]["story_fact_repository"].capture_constraints.return_value
    mutations = {
        "body": lambda: state.update(current_chapter_content="A newer author draft."),
        "contract": lambda: payload.update(contract_id="changed"),
        "missing_receipt": lambda: state.update(fact_reports={}),
        "old_version": lambda: report.update(extraction_version="fact-extraction-v4"),
        "unknown": lambda: report.update(status="unknown", coverage="partial"),
        "hash": lambda: report.update(artifact_hash="0" * 64),
        "tenant": lambda: report.update(tenant_id=str(uuid4())),
        "source_missing": lambda: payload.pop("source_hash"),
        "already_rebound": lambda: payload.update(fact_staging_rebind={"proposal_id": "older"}),
        "snapshot": lambda: report.update(snapshot_digest="0" * 64),
        "canonical_conflict": lambda: report["assertions"][0].update(
            object_entity_id=str(snapshot.entities[-1].id)),
        "repository_missing": lambda: cfg["configurable"].pop("story_fact_repository"),
        "fresh_snapshot": lambda: setattr(
            cfg["configurable"]["story_fact_repository"].capture_constraints, "return_value",
            snapshot.model_copy(update={"fact_heads": tuple(
                fact.model_copy(update={"version": fact.version + 1}) for fact in snapshot.fact_heads)})),
    }
    mutations[problem]()
    before = deepcopy(state)
    with pytest.raises(RetryableWorkflowError, match="旧正文|旧目标"):
        await revision_review_node(state, cfg)
    assert state == before
    assert cfg["configurable"]["llm_config"]["llm_instance"].structured_generate.await_count == 1


@pytest.mark.asyncio
async def test_revision_rebinding_never_restores_or_changes_an_empty_fact_ledger():
    state, cfg = await _staged_fixture()
    store = cfg["configurable"]["story_fact_repository"]
    empty = store.capture_constraints.return_value.model_copy(update={"fact_heads": ()})
    store.capture_constraints.return_value = empty
    store.ingest_confirmed_facts = AsyncMock()
    repository = SimpleNamespace(find_by_id=AsyncMock(side_effect=AssertionError("Ledger restore forbidden")))
    cfg["configurable"]["novel_repository"] = repository
    before = deepcopy(state)
    with pytest.raises(RetryableWorkflowError, match="旧正文|旧目标"):
        await revision_review_node(state, cfg)
    assert state == before
    assert repository.find_by_id.await_count == 0
    assert store.ingest_confirmed_facts.await_count == 0
