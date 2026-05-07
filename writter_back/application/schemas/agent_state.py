"""LangGraph Agent状态定义"""
from typing import Annotated, List, Optional, Dict, Any
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
    generated_summary: Optional[str]          # AI生成的简介
    generated_outline: Optional[Dict]         # AI生成的总纲领
    current_chapter_index: int                # 当前处理的章节索引
    chapter_outlines: Annotated[List[Dict], add]   # 最终使用的章节细纲列表
    current_chapter_content: Optional[str]    # 当前章节内容
    completed_chapters: Annotated[List[Dict], add]
    
    # ========== 长期记忆 ==========
    memory_context: Optional[str]
    
    # ========== 反思修正 ==========
    reflection_issues: Optional[List[Dict]]   # 发现的问题列表
    user_decision: Optional[Dict]             # 用户决策
    revision_instructions: Optional[str]       # 用户提供的修正指令（优先），否则AI自动修正
    
    # ========== 进度控制 ==========
    progress_percentage: float
    is_completed: bool
    errors: Annotated[List[str], add]
    
    # ========== LLM配置（注入用） ==========
    llm_config: Optional[Dict]                # LLM配置，用于节点中获取LLM实例
