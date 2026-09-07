"""确认来源边界与各类模型调用的快照输入契约。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.agents.character_design_node import character_design_node, character_design_review_node
from application.agents.chapter_outline_node import chapter_outline_node
from application.agents.chapter_writer_node import chapter_writer_node
from application.agents.revision_node import revision_node
from application.errors import InvalidReviewDecisionError, RetryableWorkflowError
from application.fact_prompt_binding import FactBoundLLM, render_fact_constraints
from application.fact_workflow import bind_chapter_fact_input
from application.story_facts import compile_character_surnames
from service.ports.story_fact_repository import FactVersionConflictError
from tests.test_chapter_constraints import snapshot
from tests.test_character_design_workflow import _CharacterLLM, _state
from tests.test_workflow_flow import FakeWorkflowLLM, _chapter_outline_result, _manual_workflow_input


class RecordingLLM(FakeWorkflowLLM):
    def __init__(self):
        super().__init__()
        self.prompts = []

    async def stream_text(self, prompt, **kwargs):
        self.prompts.append(prompt)
        yield "正文" * 600

    async def structured_generate(self, prompt, schema, **kwargs):
        self.prompts.append(prompt)
        return await super().structured_generate(prompt, schema, **kwargs)


def bound_config(llm=None, value=None):
    value = value or snapshot(chapter_number=1)
    store = SimpleNamespace(capture_constraints=AsyncMock(return_value=value), ingest_confirmed_facts=AsyncMock(return_value=[]))
    return {"configurable": {"story_fact_repository": store, "tenant_id": str(value.tenant_id),
        "novel_id": str(value.novel_id), "llm_config": {"llm_instance": llm or RecordingLLM()}}}, value


@pytest.mark.asyncio
async def test_human_confirmation_records_current_proposal_and_auto_does_not():
    config, _ = bound_config(_CharacterLLM())
    state = _state()
    generated = await character_design_node(state, config)
    checkpoint = {**state, **generated.update}
    proposal = checkpoint["pending_proposal"]
    checkpoint["pending_proposal_decision"] = {"proposal_id": proposal["proposal_id"], "decision": "accept"}
    accepted = await character_design_review_node(checkpoint, config)
    store = config["configurable"]["story_fact_repository"]
    store.ingest_confirmed_facts.assert_awaited_once()
    args = store.ingest_confirmed_facts.call_args
    assert args.kwargs["source_key"] == "character:" + proposal["proposal_id"]
    assert all(fact.evidence.source_ref == proposal["proposal_id"] for fact in args.args[3])
    assert accepted.update["character_fact_source"]["proposal_id"] == proposal["proposal_id"]
    store.ingest_confirmed_facts.reset_mock()
    config["configurable"]["auto_mode"] = True
    automatic = await character_design_review_node(checkpoint, config)
    store.ingest_confirmed_facts.assert_not_awaited()
    assert "character_fact_source" not in automatic.update


@pytest.mark.asyncio
async def test_restore_does_not_promote_existing_design_and_conflict_preserves_review():
    config, _ = bound_config(_CharacterLLM())
    generated = await character_design_node(_state(), config)
    checkpoint = {**_state(), **generated.update}
    proposal = checkpoint["pending_proposal"]
    checkpoint["pending_proposal_decision"] = {"proposal_id": proposal["proposal_id"], "decision": "accept"}
    store = config["configurable"]["story_fact_repository"]
    store.ingest_confirmed_facts.side_effect = FactVersionConflictError("事实冲突")
    with pytest.raises(InvalidReviewDecisionError, match="事实冲突"):
        await character_design_review_node(checkpoint, config)
    assert checkpoint["pending_proposal"] == proposal
    store.ingest_confirmed_facts.side_effect = None
    accepted = await character_design_review_node(checkpoint, config)
    store.ingest_confirmed_facts.reset_mock()
    await character_design_node({**_state(), **accepted.update}, config)
    store.ingest_confirmed_facts.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["outline", "writer", "scenes", "revision"])
async def test_generation_paths_bind_every_model_call_and_checkpoint(stage):
    llm = RecordingLLM()
    config, value = bound_config(llm)
    state = _manual_workflow_input()
    outline = _chapter_outline_result()
    if stage == "writer":
        outline["scenes"] = []
    state["chapter_outlines"] = [outline]
    state["current_chapter_content"] = "旧稿" * 1800
    state["user_decision"] = {"action": "revise", "instructions": "调整对话"}
    node = chapter_outline_node if stage == "outline" else revision_node if stage == "revision" else chapter_writer_node
    result = await node(state, config)
    assert llm.prompts and all(value.digest in prompt for prompt in llm.prompts)
    assert all("祖祠" in prompt for prompt in llm.prompts)
    assert result.update["chapter_constraints"]["chapter_number"] == 1
    assert result.update["chapter_fact_input"]["validation_status"] == "not_checked"
    assert config["configurable"]["llm_config"]["llm_instance"] is llm
    if stage in {"writer", "scenes", "revision"}:
        assert len(llm.prompts) >= 2


@pytest.mark.asyncio
async def test_pending_review_does_not_reload_or_generate_and_new_attempt_ignores_cached_snapshot():
    config, value = bound_config()
    state = _manual_workflow_input()
    proposal = {"kind": "chapter_outline", "chapter_number": 1}
    await chapter_outline_node({**state, "pending_proposal": proposal}, config)
    config["configurable"]["story_fact_repository"].capture_constraints.assert_not_awaited()
    _, update = await bind_chapter_fact_input({**state, "chapter_constraints": {"forged": True}}, config)
    assert update["chapter_fact_input"]["snapshot_digest"] == value.digest


@pytest.mark.asyncio
async def test_unavailable_or_wrong_scope_cannot_generate():
    config, value = bound_config()
    config["configurable"]["novel_id"] = str(value.tenant_id)
    with pytest.raises(RetryableWorkflowError, match="归属"):
        await bind_chapter_fact_input({}, config)
    config["configurable"]["story_fact_repository"] = None
    with pytest.raises(RetryableWorkflowError, match="不可用"):
        await bind_chapter_fact_input({}, config)
    config["configurable"].pop("story_fact_repository")
    assert await bind_chapter_fact_input({}, config) == (config, {})


def test_empty_or_inactive_facts_never_render_as_passed_and_budget_is_not_truncated(monkeypatch):
    value = snapshot()
    empty = value.model_copy(update={"fact_heads": ()})
    assert "no_confirmed_facts" in render_fact_constraints(empty)
    retracted = value.model_copy(update={"fact_heads": (value.fact_heads[0].model_copy(update={"status": "retracted"}),)})
    assert "祖祠" not in render_fact_constraints(retracted)
    monkeypatch.setattr("application.fact_prompt_binding.MAX_FACT_CONTEXT_CHARACTERS", 10)
    with pytest.raises(RetryableWorkflowError, match="预算"):
        render_fact_constraints(value)


def test_large_profile_keeps_original_source_hash_without_oversize_quote():
    import json
    from application.story_facts import source_digest
    value = snapshot()
    design = {"characters": [{"character_id": "hero", "name": "辛远", "surname": "辛", "profile": "长人物档案" * 1000}]}
    _, facts = compile_character_surnames(value.novel_id, design, source_ref="confirmed", source_version=1, confirmed=True)
    assert facts[0].evidence.quote == '"surname": "辛"'
    assert facts[0].evidence.source_hash == source_digest(json.dumps(design, ensure_ascii=False, sort_keys=True))


@pytest.mark.asyncio
async def test_proxy_preserves_schema_options_and_chat_history():
    delegate = SimpleNamespace(generate=AsyncMock(return_value="text"), structured_generate=AsyncMock(return_value={}), chat=AsyncMock(return_value="chat"))
    proxy = FactBoundLLM(delegate, "bound-constraints")
    assert await proxy.generate("prompt", temperature=0.2) == "text"
    await proxy.structured_generate("prompt", {"schema": True}, max_attempts=1)
    assert delegate.structured_generate.call_args.kwargs["max_attempts"] == 1
    messages = [{"role": "user", "content": "原始要求"}]
    await proxy.chat(messages)
    assert len(messages) == 1
    assert delegate.chat.call_args.args[0][-1]["content"] == "bound-constraints"


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_patch", [True, False])
async def test_patch_and_fallback_refactor_keep_same_constraints(valid_patch):
    llm = RecordingLLM()
    anchor = "原文锚点至少八个字符，这段内容只出现一次。"
    llm.structured_generate = AsyncMock(return_value={"edits": [
        {"issue_id": "issue-1", "anchor": anchor if valid_patch else "不存在的八字原文锚点", "replacement": "修订后的明确描述。"}
    ], "unresolved_issue_ids": []})
    config, value = bound_config(llm)
    state = {**_manual_workflow_input(), "chapter_outlines": [_chapter_outline_result()],
        "current_chapter_content": anchor + "其余正文" * 800, "quality_gate": {"decision": "patch"},
        "reflection_issues": [{"issue_id": "issue-1", "priority_action": "must_fix", "evidence_valid": True}],
        "user_decision": {"action": "revise"}}
    result = await revision_node(state, config)
    assert value.digest in llm.structured_generate.call_args_list[0].args[0]
    assert llm.structured_generate.call_args.kwargs["temperature"] == 0.0
    assert llm.structured_generate.call_args.kwargs["max_attempts"] == 1
    assert result.update["chapter_fact_input"]["snapshot_digest"] == value.digest
    if not valid_patch:
        assert llm.prompts and all(value.digest in prompt for prompt in llm.prompts)


@pytest.mark.asyncio
async def test_binding_does_not_swallow_provider_stream_errors():
    async def failed(prompt, **kwargs):
        yield "部分正文"
        raise RuntimeError("provider failure")
    llm = SimpleNamespace(stream_text=failed)
    proxy = FactBoundLLM(llm, "constraints")
    with pytest.raises(RuntimeError, match="provider failure"):
        async for _part in proxy.stream_text("prompt"):
            pass


def test_real_repository_is_wired_in_workflow_and_direct_rewrite():
    from application.orchestrator import LARGE_STATE_FIELDS, NovelOrchestrator
    from api.routers.novel_router import _rewrite_config
    from infrastructure.database.repository import PostgresNovelRepository
    from infrastructure.database.story_fact_repository import PostgresStoryFactRepository
    from tests.test_workflow_flow import tenant_context
    repo = object.__new__(PostgresNovelRepository)
    repo.async_session = object()
    orchestrator = NovelOrchestrator(repo, SimpleNamespace(), {})
    context = tenant_context()
    config = orchestrator._make_config(context, "novel-1", include_llm=False)
    assert isinstance(config["configurable"]["story_fact_repository"], PostgresStoryFactRepository)
    assert config["configurable"]["story_fact_repository"].async_session is repo.async_session
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(memory_service=None)))
    stub = SimpleNamespace(tenant_planning_loader=None, _get_llm_instance=lambda: object())
    rewrite = _rewrite_config(request, context, "novel-1", repo, None, stub)
    assert rewrite["configurable"]["story_fact_repository"].async_session is repo.async_session
    assert "chapter_constraints" in LARGE_STATE_FIELDS
