"""Deterministic routing for the per-chapter creation loop."""

import logging
from typing import Any, Literal, cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.schemas.agent_state import NovelAgentState
from application.streaming import emit_workflow_event
from application.tactical_planning import tactical_window_status
from application.feature_policy import require_planning_v1
from service.value_objects.novel_plan import NovelPlan
from service.value_objects.tactical_plan import TacticalWindow

logger = logging.getLogger("uvicorn")

RouterDestination = Literal[
    "outline_node",
    "novel_plan_initialize_node",
    "memory_retrieval_node",
    "chapter_quota_node",
    "tactical_plan_node",
    "chapter_outline_node",
    "chapter_writer_node",
    "chapter_compaction_node",
    "reflection_node",
]


def _outline_for_current_chapter(
    outlines: list[dict[str, Any]], chapter_number: int
) -> dict[str, Any] | None:
    for outline in reversed(outlines):
        if outline.get("chapter_number") == chapter_number:
            return outline
    return None


def _route(state: NovelAgentState) -> tuple[str, str]:
    """Select the next node from trusted state, without another LLM request."""
    total_outline = state.get("total_outline")
    if not isinstance(total_outline, dict) or not total_outline:
        return "outline_node", "缺少宏观总纲，返回总纲节点"

    schema_version = int(state.get("workflow_schema_version") or 2)
    if schema_version >= 5:
        planning_route = _planning_route(state)
        if planning_route is not None:
            return planning_route

    current_index = state.get("current_chapter_index", 0)
    chapter_number = current_index + 1
    content = state.get("current_chapter_content")
    if content and state.get("compaction_checked") is False:
        return "chapter_compaction_node", f"第{chapter_number}章正文已生成，检查篇幅与重复"
    if content:
        return "reflection_node", f"第{chapter_number}章正文已生成，进入质量审读"

    if (
        current_index > 0
        and state.get("memory_retrieved_for_chapter") != current_index
    ):
        return "memory_retrieval_node", f"生成第{chapter_number}章前先检索前文记忆"

    plan = _valid_plan(state.get("novel_plan")) if schema_version >= 5 else None
    if plan and state.get("chapter_quota_reserved_for_chapter") != current_index:
        return "chapter_quota_node", f"预占第{chapter_number}章唯一生成额度"
    window = _valid_window(state.get("tactical_window")) if plan else None
    if plan and tactical_window_status(
        window, plan, chapter_number, int(current_index or 0)
    ) != "active":
        return "tactical_plan_node", f"刷新第{chapter_number}章起的滚动战术窗口"

    outlines = state.get("chapter_outlines", [])
    outline = _outline_for_current_chapter(outlines, chapter_number)
    if not outline or (
        plan and window and not _execution_contract_matches(outline, plan, window)
    ):
        return "chapter_outline_node", f"为第{chapter_number}章即时生成细纲"

    return "chapter_writer_node", f"第{chapter_number}章细纲就绪，开始生成正文"


def _planning_route(state: NovelAgentState) -> tuple[str, str] | None:
    if state.get("plan_replan_request"):
        return "novel_plan_initialize_node", "检测到重规划请求，进入计划版本流程"
    raw = state.get("novel_plan")
    if not isinstance(raw, dict) or not raw:
        return "novel_plan_initialize_node", "缺少已接受的整书计划，先补全章节骨架"
    try:
        plan = NovelPlan.from_dict(raw)
    except (TypeError, ValueError):
        return "novel_plan_initialize_node", "整书计划不可用，重新建立计划提案"
    chapter = int(state.get("current_chapter_index", 0) or 0) + 1
    slot = next((item for item in plan.chapter_slots if item.chapter_number == chapter), None)
    if slot is not None and slot.detail_level == "skeleton":
        return "novel_plan_initialize_node", f"进入新卷前细化第{chapter}章所在分卷"
    return None


def _valid_plan(value: Any) -> NovelPlan | None:
    try:
        return NovelPlan.from_dict(value) if isinstance(value, dict) and value else None
    except (TypeError, ValueError):
        return None


def _valid_window(value: Any) -> TacticalWindow | None:
    try:
        return TacticalWindow.from_dict(value) if isinstance(value, dict) and value else None
    except (TypeError, ValueError):
        return None


def _execution_contract_matches(
    outline: dict[str, Any], plan: NovelPlan, window: TacticalWindow
) -> bool:
    contract = outline.get("chapter_execution_contract")
    if not isinstance(contract, dict):
        return False
    return (
        int(contract.get("plan_version", 0) or 0) == plan.version
        and int(contract.get("tactical_version", 0) or 0) == window.version
        and int(contract.get("chapter_number", 0) or 0) == window.start_chapter
    )


def _schema_upgrade(
    state: NovelAgentState, config: RunnableConfig
) -> dict[str, Any]:
    """Upgrade legacy checkpoints only after their pending review has cleared."""
    schema_version = int(state.get("workflow_schema_version") or 2)
    enabled = bool(config.get("configurable", {}).get(
        "novel_planning_v1_enabled", False
    ))
    if schema_version >= 5 or not enabled or state.get("pending_proposal"):
        return {}
    return {"workflow_schema_version": 5}


async def router_agent(
    state: NovelAgentState, config: RunnableConfig
) -> Command[RouterDestination]:
    """Route the fixed writing process and expose the reason to the SSE timeline."""
    schema_version = int(state.get("workflow_schema_version") or 2)
    configured = config.get("configurable", {})
    upgrading = bool(
        configured.get("novel_planning_v1_enabled")
        and not state.get("pending_proposal")
    )
    if schema_version >= 5 or upgrading:
        await require_planning_v1(config)
    upgrade = _schema_upgrade(state, config)
    route_state = cast(NovelAgentState, {**state, **upgrade})
    next_tool, reasoning = _route(route_state)
    logger.info("【确定性路由】%s -> %s", reasoning, next_tool)
    emit_workflow_event(
        "reasoning",
        {"text": reasoning, "next_node": next_tool},
        "router_agent",
    )
    return Command(
        goto=next_tool,
        update={
            **upgrade,
            "phase": "writing",
            "graph_version": "v3",
            "next_tool": next_tool,
            "router_reasoning": reasoning,
        },
    )
