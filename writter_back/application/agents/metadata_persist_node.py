"""设定阶段的轻量元数据持久化节点。"""

import logging
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.schemas.agent_state import NovelAgentState
from application.streaming import emit_workflow_event

logger = logging.getLogger("uvicorn")


async def metadata_persist_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["summary_node", "outline_node"]]:
    """立即保存已确认的书名或简介，再进入下一个设定节点。"""
    configurable = config["configurable"]
    repository = configurable.get("novel_repository")
    novel_id = configurable.get("novel_id", "")
    tenant_id = configurable.get("tenant_id", "")
    next_node = state.get("__next_node__")
    if next_node not in {"summary_node", "outline_node"}:
        raise RuntimeError("小说元数据保存失败：后续节点无效")
    if repository and novel_id:
        novel = await repository.find_by_id(tenant_id, novel_id)
        if novel is None:
            raise RuntimeError("小说元数据保存失败：目标小说不存在")
        if state.get("title"):
            novel.title = state["title"]
        if state.get("summary"):
            novel.summary = state["summary"]
        await repository.update(tenant_id, novel)
    emit_workflow_event(
        "metadata_updated",
        {"title": state.get("title"), "summary": state.get("summary")},
        "metadata_persist_node",
    )
    logger.info("【元数据持久化节点】已保存书名/简介 -> %s", next_node)
    return Command(goto=next_node, update={"__next_node__": None})
