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
    router_agent,
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
    workflow.add_node("router_agent", router_agent)
    
    # ========= 设置入口 =========
    workflow.set_entry_point("type_confirmation")
    
    # ========= 第一阶段：小说设定（线性流程） =========
    workflow.add_edge("type_confirmation", "title_node")
    workflow.add_edge("title_node", "summary_node")
    workflow.add_edge("summary_node", "outline_node")
    workflow.add_edge("outline_node", "persist_node")
    workflow.add_edge("persist_node", "progress_check_node")
    
    # ========= 进度检查分支 =========
    # progress_check_node 返回 {"__route__": "end"} 或 {"__route__": "continue"}
    # continue 目标改为 router_agent（由 LLM 决定下一步）
    workflow.add_conditional_edges(
        "progress_check_node",
        lambda state: state.get("__route__", "continue"),
        {
            "end": END,
            "continue": "router_agent"
        }
    )
    
    # ========= 第二阶段：章节创作循环（Agent 驱动） =========
    # 所有写作节点完成后回到 router_agent，由 LLM 决策下一步
    workflow.add_edge("memory_retrieval_node", "router_agent")
    workflow.add_edge("chapter_outline_node", "router_agent")
    workflow.add_edge("chapter_writer_node", "router_agent")
    # reflection_node/revision_node 通过 Command(goto=...) 自决路由，不加静态边
    #
    # 【确定性数据流 - 非决策路径】
    #   reflection_node(pass)  → persist_node     (必须保存)
    #   reflection_node(fail)  → revision_node     (必须修正)
    #   revision_node(accept)  → persist_node      (必须保存)
    #   revision_node(regenerate) → chapter_writer_node (必须重写)
    #   persist_node(writing)  → progress_check_node    (必须检查进度)
    #   persist_node(setup)    → progress_check_node    (必须检查进度)
    #
    # 【Agent 决策路径】
    #   progress_check_node(continue) → router_agent  (下一章做什么?)
    #   memory_retrieval_node         → router_agent  (细纲还是直接写?)
    #   chapter_outline_node          → router_agent  (准备好写了吗?)
    #   chapter_writer_node           → router_agent  (需要检查质量吗?)
    
    # ========= router_agent 条件分发 =========
    # router_agent 返回的 next_tool 字段决定下一节点
    workflow.add_conditional_edges(
        "router_agent",
        lambda state: state.get("next_tool", "progress_check_node"),
        {
            "memory_retrieval_node": "memory_retrieval_node",
            "chapter_outline_node": "chapter_outline_node",
            "chapter_writer_node": "chapter_writer_node",
            "reflection_node": "reflection_node",
            "revision_node": "revision_node",
            "persist_node": "persist_node",
            "progress_check_node": "progress_check_node",
        }
    )
    
    # ========= 编译工作流 =========
    return workflow.compile(checkpointer=checkpointer)
