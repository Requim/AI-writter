"""Reserve the single chapter quota before Schema 5 planning calls."""

from typing import Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.errors import RetryableWorkflowError
from application.feature_policy import require_planning_v1
from application.schemas.agent_state import NovelAgentState


async def chapter_quota_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["router_agent"]]:
    await require_planning_v1(config)
    values = config["configurable"]
    service = values.get("quota_service")
    context = values.get("tenant_context")
    run_id = state.get("workflow_run_id")
    if not service or not context or not run_id:
        raise RetryableWorkflowError("章节额度服务不可用，尚未调用规划模型")
    chapter_index = int(state.get("current_chapter_index", 0) or 0)
    await service.reserve(context, run_id, "chapter", chapter_index)
    return Command(
        goto="router_agent",
        update={"chapter_quota_reserved_for_chapter": chapter_index},
    )
