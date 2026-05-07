"""LangGraph工作流构建器"""
from langgraph.graph import StateGraph, START, END
from application.schemas.agent_state import NovelAgentState
from application.agents import (
    type_confirmation_node,
    title_generator_node,
    summary_generator_node,
    outline_generator_node,
    progress_check_node,
    memory_retrieval_node,
    chapter_outline_node,
    chapter_writer_node,
    reflection_node,
    revision_node,
    persist_node,
)


def create_novel_workflow(checkpointer=None):
    """构建小说创作LangGraph工作流
    
    Args:
        checkpointer: LangGraph Checkpointer实例，用于支持interrupt/resume
        
    Returns:
        Compiled StateGraph: 编译好的LangGraph工作流
    """
    workflow = StateGraph(NovelAgentState)
    
    # ========= 添加节点 =========
    workflow.add_node("type_confirmation", type_confirmation_node)
    workflow.add_node("title_node", title_generator_node)
    workflow.add_node("summary_node", summary_generator_node)
    workflow.add_node("outline_node", outline_generator_node)
    workflow.add_node("progress_check_node", progress_check_node)
    workflow.add_node("memory_retrieval_node", memory_retrieval_node)
    workflow.add_node("chapter_outline_node", chapter_outline_node)
    workflow.add_node("chapter_writer_node", chapter_writer_node)
    workflow.add_node("reflection_node", reflection_node)
    workflow.add_node("revision_node", revision_node)
    workflow.add_node("persist_node", persist_node)
    
    # ========= 设置入口 =========
    workflow.set_entry_point("type_confirmation")
    
    # ========= 第一阶段：小说设定（线性流程） =========
    workflow.add_edge("type_confirmation", "title_node")
    workflow.add_edge("title_node", "summary_node")
    workflow.add_edge("summary_node", "outline_node")
    workflow.add_edge("outline_node", "progress_check_node")
    
    # ========= 进度检查分支 =========
    # progress_check_node 返回 {"__route__": "end"} 或 {"__route__": "continue"}
    workflow.add_conditional_edges(
        "progress_check_node",
        lambda state: state.get("__route__", "continue"),
        {
            "end": END,
            "continue": "memory_retrieval_node"
        }
    )
    
    # ========= 第二阶段：章节创作循环 =========
    workflow.add_edge("memory_retrieval_node", "chapter_outline_node")
    workflow.add_edge("chapter_outline_node", "chapter_writer_node")
    workflow.add_edge("chapter_writer_node", "reflection_node")
    workflow.add_edge("reflection_node", "revision_node")
    workflow.add_edge("revision_node", "persist_node")
    workflow.add_edge("persist_node", "progress_check_node")
    
    # ========= 编译工作流 =========
    return workflow.compile(checkpointer=checkpointer)
