"""LangGraph工作流构建器"""
from langgraph.graph import END, StateGraph

from application.schemas.agent_state import NovelAgentState
from application.agents import (
    type_confirmation_node,
    creative_brief_node,
    creative_brief_review_node,
    character_design_node,
    character_design_review_node,
    title_generator_node,
    title_review_node,
    summary_generator_node,
    summary_review_node,
    outline_generator_node,
    outline_review_node,
    progress_check_node,
    memory_retrieval_node,
    chapter_outline_node,
    chapter_outline_review_node,
    metadata_persist_node,
    chapter_writer_node,
    chapter_compaction_node,
    reflection_node,
    reflection_review_node,
    revision_node,
    revision_review_node,
    persist_node,
    router_agent,
)

WORKFLOW_NODES = {
    "type_confirmation": type_confirmation_node,
    "creative_brief_node": creative_brief_node,
    "creative_brief_review_node": creative_brief_review_node,
    "character_design_node": character_design_node,
    "character_design_review_node": character_design_review_node,
    "title_node": title_generator_node,
    "title_review_node": title_review_node,
    "summary_node": summary_generator_node,
    "summary_review_node": summary_review_node,
    "outline_node": outline_generator_node,
    "outline_review_node": outline_review_node,
    "progress_check_node": progress_check_node,
    "memory_retrieval_node": memory_retrieval_node,
    "chapter_outline_node": chapter_outline_node,
    "chapter_outline_review_node": chapter_outline_review_node,
    "metadata_persist_node": metadata_persist_node,
    "chapter_writer_node": chapter_writer_node,
    "chapter_compaction_node": chapter_compaction_node,
    "reflection_node": reflection_node,
    "reflection_review_node": reflection_review_node,
    "revision_node": revision_node,
    "revision_review_node": revision_review_node,
    "persist_node": persist_node,
    "router_agent": router_agent,
}

PROGRESS_ROUTES = {"end": END, "continue": "router_agent"}
ROUTER_ROUTES = {
    "memory_retrieval_node": "memory_retrieval_node",
    "chapter_outline_node": "chapter_outline_node",
    "chapter_writer_node": "chapter_writer_node",
    "chapter_compaction_node": "chapter_compaction_node",
    "reflection_node": "reflection_node",
    "revision_node": "revision_node",
    "persist_node": "persist_node",
    "progress_check_node": "progress_check_node",
}


def _add_nodes(workflow: StateGraph) -> None:
    """注册工作流节点。"""
    for name, node in WORKFLOW_NODES.items():
        workflow.add_node(name, node)


def _add_deterministic_edges(workflow: StateGraph) -> None:
    """注册不会由节点 Command 自行决定的固定边。"""
    workflow.add_edge("persist_node", "progress_check_node")
    workflow.add_edge("memory_retrieval_node", "router_agent")
    workflow.add_edge("chapter_writer_node", "router_agent")
    workflow.add_edge("chapter_compaction_node", "router_agent")


def _add_conditional_routes(workflow: StateGraph) -> None:
    """注册进度与章节阶段的条件分发。"""
    workflow.add_conditional_edges(
        "progress_check_node",
        lambda state: state.get("__route__", "continue"),
        PROGRESS_ROUTES,
    )
    workflow.add_conditional_edges(
        "router_agent",
        lambda state: state.get("next_tool", "progress_check_node"),
        ROUTER_ROUTES,
    )


def create_novel_workflow(checkpointer=None):
    """构建支持 checkpoint 与人工中断的小说创作工作流。"""
    workflow = StateGraph(NovelAgentState)
    _add_nodes(workflow)
    workflow.set_entry_point("type_confirmation")
    _add_deterministic_edges(workflow)
    _add_conditional_routes(workflow)
    return workflow.compile(checkpointer=checkpointer)
