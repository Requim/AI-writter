"""将服务端采用的角色设定连接到事实仓储，区分自动采用与人工确认。"""

import json
from typing import Any, cast
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.errors import InvalidReviewDecisionError, RetryableWorkflowError
from application.fact_prompt_binding import FactBoundLLM, render_fact_constraints
from application.schemas.agent_state import NovelAgentState, PendingProposal
from application.story_facts import compile_character_surnames, source_digest
from service.ports.story_fact_repository import FactVersionConflictError
from service.value_objects.chapter_constraints import ChapterConstraintSet


def _repository(config: RunnableConfig) -> Any:
    values = config.get("configurable", {})
    if "story_fact_repository" not in values:
        return None
    if values["story_fact_repository"] is None:
        raise RetryableWorkflowError("事实仓储不可用，本次操作未继续")
    return values["story_fact_repository"]


def attach_fact_input(command: Command, update: dict[str, Any]) -> Command:
    """将实际使用的模型输入快照随节点结果写入 checkpoint。"""
    return Command(goto=command.goto, update={**(command.update or {}), **update})


async def record_character_confirmation(state: NovelAgentState, config: RunnableConfig,
                                         proposal: PendingProposal, design: dict[str, Any]) -> dict[str, Any]:
    """仅角色审核通过后调用；自动采用标注独立来源，不伪造人工审核回执。"""
    values = config.get("configurable", {})
    if int(state.get("workflow_schema_version") or 2) < 3:
        return {}
    store = _repository(config)
    if store is None:
        return {}
    tenant, novel = str(values["tenant_id"]), str(values["novel_id"])
    automatic = bool(values.get("auto_mode", False))
    source_ref = ("auto:" if automatic else "") + proposal["proposal_id"]
    entities, facts = compile_character_surnames(UUID(novel), design, source_ref=source_ref,
        source_version=proposal["version"], confirmed=True)
    try:
        stored = await store.ingest_confirmed_facts(tenant, novel, entities, facts,
            source_key="character:" + source_ref)
    except FactVersionConflictError as exc:
        raise InvalidReviewDecisionError(str(exc)) from exc
    return {"character_fact_source": {"proposal_id": proposal["proposal_id"], "version": proposal["version"],
        "accepted_by": "automatic_policy" if automatic else "human",
        "fact_count": len(stored), "status": "recorded" if stored else "no_explicit_facts"}}


async def _restore_automatic_baseline(config: RunnableConfig, snapshot: ChapterConstraintSet) -> bool:
    values = config["configurable"]
    repository = values.get("novel_repository")
    if not values.get("auto_mode") or snapshot.fact_heads or repository is None:
        return False
    tenant, novel_id = str(values["tenant_id"]), str(values["novel_id"])
    novel = await repository.find_by_id(tenant, novel_id)
    if novel is None or str(novel.id) != novel_id or str(novel.tenant_id) != tenant:
        raise RetryableWorkflowError("角色事实基线的作品归属不匹配")
    outline = novel.total_outline
    characters = getattr(outline, "main_characters", None) if outline else None
    if not characters:
        return False
    design = {"characters": characters}
    digest = source_digest(json.dumps(design, ensure_ascii=False, sort_keys=True))
    source_ref = "auto-saved:" + digest[:40]
    entities, facts = compile_character_surnames(UUID(novel_id), design,
        source_ref=source_ref, source_version=1, confirmed=True)
    if not facts:
        return False
    try:
        await _repository(config).ingest_confirmed_facts(tenant, novel_id, entities, facts,
                                                       source_key=source_ref)
    except FactVersionConflictError as exc:
        raise InvalidReviewDecisionError(str(exc)) from exc
    return True


async def capture_fact_constraints(state: NovelAgentState, config: RunnableConfig) -> ChapterConstraintSet:
    """读取可信快照；自动模式只从同租户已保存角色补建空台账，不读取草稿作为事实。"""
    values, store = config["configurable"], _repository(config)
    tenant, novel = str(values["tenant_id"]), str(values["novel_id"])
    chapter = int(state.get("current_chapter_index", 0) or 0) + 1
    snapshot = await store.capture_constraints(tenant, novel, chapter)
    if (snapshot.tenant_id, snapshot.novel_id, snapshot.chapter_number) != (UUID(tenant), UUID(novel), chapter):
        raise RetryableWorkflowError("章节事实快照归属不匹配，本次生成未继续")
    if await _restore_automatic_baseline(config, snapshot):
        snapshot = await store.capture_constraints(tenant, novel, chapter)
    snapshot = ChapterConstraintSet.model_validate(snapshot.model_dump())
    if (snapshot.tenant_id, snapshot.novel_id, snapshot.chapter_number) != (UUID(tenant), UUID(novel), chapter):
        raise RetryableWorkflowError("章节事实快照归属不匹配，本次生成未继续")
    return snapshot


async def bind_chapter_fact_input(state: NovelAgentState, config: RunnableConfig) -> tuple[RunnableConfig, dict[str, Any]]:
    """每次新生成读取服务端快照；旧 checkpoint 副本不能替代当前仓储。"""
    store = _repository(config)
    if store is None:
        return config, {}
    values = config.get("configurable", {})
    tenant, novel = str(values["tenant_id"]), str(values["novel_id"])
    chapter = int(state.get("current_chapter_index", 0) or 0) + 1
    raw = await capture_fact_constraints(state, config)
    snapshot = ChapterConstraintSet.model_validate(raw.model_dump())
    if (snapshot.tenant_id, snapshot.novel_id, snapshot.chapter_number) != (UUID(tenant), UUID(novel), chapter):
        raise RetryableWorkflowError("章节事实快照归属不匹配，本次生成未继续")
    llm_config = dict(values.get("llm_config") or {})
    llm = llm_config.get("llm_instance")
    if llm is None:
        raise RetryableWorkflowError("章节生成失败：LLM 不可用")
    context = render_fact_constraints(snapshot)
    llm_config["llm_instance"] = FactBoundLLM(llm, context)
    bound = cast(RunnableConfig, {**config, "configurable": {**values, "llm_config": llm_config}})
    return bound, {"chapter_constraints": snapshot.model_dump(mode="json"),
        "chapter_fact_input": {"snapshot_digest": snapshot.digest, "prompt_context_hash": source_digest(context),
            "chapter_number": chapter, "fact_count": len(snapshot.active_facts), "validation_status": "not_checked"}}
