"""将真实人工确认与章节生成连接到事实仓储；不从模型自报确认建立权威。"""

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
    """仅审核节点完成真实人工确认后调用；自动模式和旧协议不回填事实。"""
    values = config.get("configurable", {})
    if values.get("auto_mode", False) or int(state.get("workflow_schema_version") or 2) < 3:
        return {}
    store = _repository(config)
    if store is None:
        return {}
    tenant, novel = str(values["tenant_id"]), str(values["novel_id"])
    entities, facts = compile_character_surnames(UUID(novel), design, source_ref=proposal["proposal_id"],
        source_version=proposal["version"], confirmed=True)
    try:
        stored = await store.ingest_confirmed_facts(tenant, novel, entities, facts,
            source_key="character:" + proposal["proposal_id"])
    except FactVersionConflictError as exc:
        raise InvalidReviewDecisionError(str(exc)) from exc
    return {"character_fact_source": {"proposal_id": proposal["proposal_id"], "version": proposal["version"],
        "fact_count": len(stored), "status": "recorded" if stored else "no_explicit_facts"}}


async def bind_chapter_fact_input(state: NovelAgentState, config: RunnableConfig) -> tuple[RunnableConfig, dict[str, Any]]:
    """每次新生成读取服务端快照；旧 checkpoint 副本不能替代当前仓储。"""
    store = _repository(config)
    if store is None:
        return config, {}
    values = config.get("configurable", {})
    tenant, novel = str(values["tenant_id"]), str(values["novel_id"])
    chapter = int(state.get("current_chapter_index", 0) or 0) + 1
    raw = await store.capture_constraints(tenant, novel, chapter)
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
