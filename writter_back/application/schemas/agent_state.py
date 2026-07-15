"""LangGraph Agent状态定义"""
from typing import Annotated, List, Optional, Dict
from operator import add
from typing_extensions import TypedDict


class NovelAgentState(TypedDict):
    """LangGraph Agent 状态 - 整个小说创作流程的共享状态"""
    
    # ========== 用户输入区（由用户通过interrupt提供） ==========
    novel_type: str                          # 小说类型（强制用户输入，无AI fallback）
    title: Optional[str]                      # 书名（用户优先，空则AI生成）
    summary: Optional[str]                    # 简介（用户优先，空则AI生成）
    total_outline: Optional[Dict]            # 总纲领（用户优先，空则AI生成）
    chapter_outlines_input: Optional[Dict]    # 用户提供的章节细纲（优先使用）
    
    # ========== 系统生成区 ==========
    generated_title: Optional[str]            # AI生成的书名（当用户未提供时）
    title_story_hint: Optional[str]           # AI生成书名时附带的"一句话卖点"，联动传给简介生成
    generated_summary: Optional[str]          # AI生成的简介
    generated_outline: Optional[Dict]         # AI生成的总纲领
    current_chapter_index: int                # 当前处理的章节索引
    chapter_outlines: Annotated[List[Dict], add]   # 最终使用的章节细纲列表
    current_chapter_content: Optional[str]    # 当前章节内容
    completed_chapters: Annotated[List[Dict], add]
    
    # ========== 长期记忆 ==========
    memory_context: Optional[str]
    memory_retrieved_for_chapter: Optional[int]
    
    # ========== 反思修正 ==========
    reflection_issues: Optional[List[Dict]]   # 发现的问题列表
    user_decision: Optional[Dict]             # 用户决策
    revision_instructions: Optional[str]       # 用户提供的修正指令（优先），否则AI自动修正
    revision_attempts: int                    # 自动模式修正重试次数，用于循环修正防死循环
    
    # ========== 进度控制 ==========
    progress_percentage: float
    is_completed: bool
    errors: Annotated[List[str], add]
    
    # ========== LLM配置（注入用） ==========
    llm_config: Optional[Dict]                # LLM配置，用于节点中获取LLM实例
    workflow_run_id: Optional[str]            # 配额幂等键，恢复时沿用

    # ========== 内部路由 ==========
    __next_node__: Optional[str]               # persist_node 设定阶段的目标节点
    __route__: Optional[str]                   # workflow_builder 条件路由用
    
    # ========== Agent 驱动路由（v2） ==========
    graph_version: Optional[str]               # "v1"(固定DAG) / "v2"(Agent驱动)
    phase: Optional[str]                       # "setup" / "writing" / "complete"
    next_tool: Optional[str]                   # router_agent 选定的下一个工具名
    router_reasoning: Optional[str]            # LLM 路由决策原因（调试用）
