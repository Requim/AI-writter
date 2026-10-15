"""Narrow repairs save calls by removing generation retries, never review gates."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from application.agents.revision_node import _generate_patch, revision_node
from application.creative.errors import CreativePause
from application.creative.runtime import creative_node_scope
from application.errors import RetryableWorkflowError
from application.goal_contract import evaluate_goals
from tests.test_creative_budget_grants import seed_book
from tests.test_elastic_budget import activate, set_counters
from tests.test_goal_contract import goal_state, report_for


def local_state():
    state = goal_state()
    body = state["current_chapter_content"]
    state.update(author_mode="autonomous_v1", quality_gate={
        "decision": "patch", "goal_acceptance": evaluate_goals(state, report_for(state), body)},
        reflection_issues=[{"issue_id": "block", "evidence": body[:10],
            "evidence_valid": True, "priority_action": "must_fix", "issue_resolved": False}])
    return state


@pytest.mark.asyncio
async def test_trusted_local_scope_fits_without_reset_and_reuses_the_hold(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    from service.ports.model_meter import active_model_meter

    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    assert (await activate(async_client, novel)).status_code == 200
    await set_counters(repository, tenant_context, sample_novel, {"chapter:1": 32})
    saved = await creative.get_session(tenant, novel)
    state = {**local_state(), "creative_session_id": saved["id"]}
    config = {"configurable": {"creative_repository": creative, "tenant_id": tenant, "novel_id": novel}}
    for _ in range(2):
        async with creative_node_scope("revision_node", state, config) as (_, scoped):
            assert scoped["configurable"]["_local_only_repair"] is True
            await active_model_meter.get().reserve()
    saved = await creative.get_session(tenant, novel)
    assert saved["limits"]["round"]["purpose"] == "repair_local"
    assert saved["limits"]["round"]["size"] == 15
    assert saved["limits"]["round"]["remaining"] == 13
    assert saved["limits"]["total"] == 200
    assert saved["counters"] == {"chapter:1": 34}


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["long", "refactor", "instruction", "stale", "blocked", "no_issue"])
async def test_unqualified_body_cannot_use_local_allowance(
    async_client, repository, tenant_context, sample_novel, monkeypatch, mutation,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    assert (await activate(async_client, novel)).status_code == 200
    await set_counters(repository, tenant_context, sample_novel, {"chapter:1": 32})
    saved = await creative.get_session(tenant, novel)
    state = {**local_state(), "creative_session_id": saved["id"]}
    actions = {
        "long": lambda: state.update(current_chapter_content="x" * 6001),
        "refactor": lambda: state["quality_gate"].update(decision="refactor"),
        "instruction": lambda: state.update(user_decision={"instructions": "rewrite"}),
        "stale": lambda: state["quality_gate"]["goal_acceptance"].update(content_hash="a" * 64),
        "blocked": lambda: state["quality_gate"]["goal_acceptance"].update(status="blocked"),
        "no_issue": lambda: state.update(reflection_issues=[]),
    }
    actions[mutation]()
    config = {"configurable": {"creative_repository": creative, "tenant_id": tenant, "novel_id": novel,
        "_local_only_repair": True}}
    with pytest.raises(CreativePause, match="至少所需18"):
        async with creative_node_scope("revision_node", state, config):
            pytest.fail("Insufficient full repair must stop before generation")
    assert (await creative.get_session(tenant, novel))["counters"] == {"chapter:1": 32}


@pytest.mark.asyncio
async def test_local_minimum_and_closed_cycle_cannot_be_refilled(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    assert (await activate(async_client, novel)).status_code == 200
    await set_counters(repository, tenant_context, sample_novel, {"chapter:1": 34})
    with pytest.raises(CreativePause):
        await creative.begin_budget_round(tenant, novel, "chapter:1", "body", "repair_local")
    await set_counters(repository, tenant_context, sample_novel, {"chapter:1": 33})
    await creative.begin_budget_round(tenant, novel, "chapter:1", "body", "repair_local")
    await creative.reserve(tenant, novel, "chapter:1", "revision_node")
    await creative.release_budget_round(tenant, novel, "chapter:1")
    await set_counters(repository, tenant_context, sample_novel, {})
    with pytest.raises(CreativePause, match="同一正文"):
        await creative.begin_budget_round(tenant, novel, "chapter:1", "body", "repair")


@pytest.mark.asyncio
async def test_local_generation_is_one_attempt_and_unsafe_patch_never_falls_back():
    state = local_state()
    body = state["current_chapter_content"]
    state["current_chapter_content"] = body[:40] + "\n" + body[40:]
    original = deepcopy(state)
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value={
        "edits": [{"issue_id": "block", "anchor": body[40:], "replacement": "changed",
            "evidence_start": "p2", "evidence_end": "p2"}],
        "unresolved_issue_ids": []}), stream_generate=AsyncMock())
    config = {"configurable": {"auto_mode": True, "_local_only_repair": True,
        "llm_config": {"llm_instance": llm}}}
    with (
        patch("application.agents.revision_node.require_planning_v1", AsyncMock()),
        patch("application.agents.revision_node.bind_chapter_fact_input", AsyncMock(return_value=(config, {}))),
        patch("application.agents.revision_node._generate_refactor",
              AsyncMock(return_value=state["current_chapter_content"])) as fallback,
    ):
        with pytest.raises(RetryableWorkflowError, match="局部修改锚点没有包含对应问题的原文证据"):
            await revision_node(state, config)
    assert llm.structured_generate.call_args.kwargs["max_attempts"] == 1
    fallback.assert_not_called()
    llm.stream_generate.assert_not_called()
    assert state == original


@pytest.mark.asyncio
async def test_regular_manual_patch_keeps_existing_attempt_policy():
    body = "Original unique prose. " * 1 + "Rest. " * 50
    state = {"reflection_issues": [{"issue_id": "block", "evidence": "Original unique prose.",
        "evidence_valid": True, "priority_action": "must_fix"}]}
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value={
        "edits": [{"issue_id": "block", "anchor": "Original unique prose.",
            "replacement": "Repaired unique prose."}], "unresolved_issue_ids": []}))
    revised = await _generate_patch(llm, state, body, {}, "", "")
    assert revised.startswith("Repaired unique prose.")
    assert "max_attempts" not in llm.structured_generate.call_args.kwargs


def test_patch_prompt_explains_the_existing_evidence_scope_for_paired_locations():
    from application.prompts.revision_prompts import build_patch_revision_prompt

    prompt = build_patch_revision_prompt("A paired-location finding", "Existing prose", {})
    assert "必须完整包含该 issue 的原文证据" in prompt
    assert "同一 issue 的多处修正合并为一个连续 anchor" in prompt


def test_paired_location_patch_still_requires_primary_evidence_in_one_bounded_span():
    from application.agents.revision_node import _check_goal_patch_scope, apply_structured_patch

    first, second = "The worksheet says front side.", "The copied application says front side."
    anchor = first + "\nShe completes the application.\n" + second
    body = "Earlier prose. " * 60 + anchor + " Later prose." * 60
    issue = {"issue_id": "paired", "evidence": first}
    split = {"edits": [
        {"issue_id": "paired", "anchor": first, "replacement": first.replace("front", "back")},
        {"issue_id": "paired", "anchor": second, "replacement": second.replace("front", "back")},
    ]}
    with pytest.raises(RetryableWorkflowError, match="原文证据"):
        _check_goal_patch_scope(split, [issue], body)
    grouped = {"edits": [{"issue_id": "paired", "anchor": anchor,
        "replacement": anchor.replace("front", "back")}]}
    _check_goal_patch_scope(grouped, [issue], body)
    result = apply_structured_patch(body, grouped, {"paired"})
    assert "front side" not in result
    assert result == body.replace(anchor, anchor.replace("front", "back"))


def test_untrusted_provider_error_is_not_exposed_in_the_retained_diagnostic(caplog):
    from application.agents.revision_node import _bounded_patch_error

    error = _bounded_patch_error(RetryableWorkflowError("private provider credential and response"))
    assert "private provider" not in str(error)
    assert "private provider" not in caplog.text
    assert "RetryableWorkflowError" in str(error)


@pytest.mark.asyncio
async def test_local_patch_resolves_server_owned_paragraphs_without_model_anchor_copy():
    state = local_state()
    body = state["current_chapter_content"]
    lines = [body[:40], body[40:80], body[80:120], body[120:]]
    body = "\n".join(lines)
    state["current_chapter_content"] = body
    anchor = "\n".join(lines[:3])
    replacement = anchor.replace("归还失物", "核对后归还失物")
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value={
        "edits": [{"issue_id": "block", "evidence_start": "p1", "evidence_end": "p3",
            "replacement": replacement}], "unresolved_issue_ids": []}))
    config = {"configurable": {"_local_only_repair": True}}
    result = await _generate_patch(llm, state, body, state["chapter_outlines"][-1], "", "", config)
    assert result == body.replace(anchor, replacement)
    assert llm.structured_generate.call_args.kwargs["max_attempts"] == 1
    assert '"evidence_start"' in llm.structured_generate.call_args.kwargs["prompt"]


@pytest.mark.parametrize("edit", [
    {"evidence_start": "p9", "evidence_end": "p9"},
    {"evidence_start": "p2", "evidence_end": "p1"},
    {"evidence_start": "p1"},
    {"evidence_start": "p1", "evidence_end": "p1", "anchor": "Forged original"},
    {"anchor": "First original paragraph."},
])
def test_local_paragraph_protocol_rejects_missing_forged_or_reversed_spans(edit):
    from application.revision_patch_spans import resolve_local_patch

    with pytest.raises(RetryableWorkflowError, match="段落引用无效"):
        resolve_local_patch({"edits": [edit]}, "First original paragraph.\nSecond original paragraph.")
