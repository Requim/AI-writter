"""LangGraph Agent状态定义"""
from typing import Annotated, Any, List, Optional, Dict, Literal
from operator import add
from typing_extensions import TypedDict


class PendingProposal(TypedDict):
    """等待人工确认的、已持久化到 checkpoint 的生成提案。"""

    proposal_id: str
    kind: Literal[
        "creative_brief",
        "title",
        "summary",
        "outline",
        "chapter_outline",
        "reflection",
        "revision",
    ]
    version: int
    payload: Any
    chapter_number: Optional[int]
    prompt_version: str


class NovelAgentState(TypedDict):
    """LangGraph Agent 状态 - 整个小说创作流程的共享状态"""
    
    # ========== 用户输入区（由用户通过interrupt提供） ==========
    novel_type: str                          # 小说类型（强制用户输入，无AI fallback）
    title: Optional[str]                      # 书名（用户优先，空则AI生成）
    summary: Optional[str]                    # 简介（用户优先，空则AI生成）
    target_total_chapters: Optional[int]      # 用户计划章节数（约束AI生成总纲）
    requested_writing_style: Optional[str]    # 用户指定写作风格（约束AI生成总纲）
    creative_brief: Optional[Dict]            # 创作简报（母题、冲突、读者承诺与内容边界）
    creative_brief_feedback: Optional[str]    # 用户对创作简报的修改要求
    total_outline: Optional[Dict]            # 总纲领（用户优先，空则AI生成）
    chapter_outlines_input: Optional[Dict]    # 用户提供的章节细纲（优先使用）
    
    # ========== 系统生成区 ==========
    generated_title: Optional[str]            # AI生成的书名（当用户未提供时）
    title_story_hint: Optional[str]           # AI生成书名时附带的"一句话卖点"，联动传给简介生成
    generated_summary: Optional[str]          # AI生成的简介
    editorial_summary: Optional[str]          # 供总纲规划使用的内部简介
    generated_outline: Optional[Dict]         # AI生成的总纲领
    pending_proposal: Optional[PendingProposal]  # 当前等待审核的生成提案
    pending_proposal_decision: Optional[Any]     # 仅用于恢复旧 checkpoint 的一次性决定
    proposal_versions: Dict[str, int]          # 每类提案的单调版本号
    workflow_schema_version: int               # checkpoint 状态契约版本
    current_chapter_index: int                # 当前处理的章节索引
    chapter_outlines: Annotated[List[Dict], add]   # 最终使用的章节细纲列表
    current_chapter_content: Optional[str]    # 当前章节内容
    scene_ledger: Optional[List[Dict]]         # 已生成场景的累计执行账本
    compaction_checked: bool                   # 当前正文是否完成过压缩判定
    compaction_metrics: Optional[Dict]         # 压缩触发原因和保真校验结果
    completed_chapters: Annotated[List[Dict], add]
    
    # ========== 长期记忆 ==========
    memory_context: Optional[str]
    memory_retrieved_for_chapter: Optional[int]
    
    # ========== 反思修正 ==========
    reflection_issues: Optional[List[Dict]]   # 发现的问题列表
    user_decision: Optional[Dict]             # 用户决策
    revision_instructions: Optional[str]       # 用户提供的修正指令（优先），否则AI自动修正
    revision_attempts: int                    # 自动模式修正重试次数，用于循环修正防死循环
    revision_history: Optional[List[Dict]]    # 自动修订的审读问题历史
    quality_gate: Optional[Dict]              # 服务端计算的质量判定与分项评分
    quality_results: Annotated[List[Dict], add]  # 跨章节保留的审读审计结果
    
    # ========== 进度控制 ==========
    progress_percentage: float
    is_completed: bool
    errors: Annotated[List[str], add]
    
    # ========== LLM配置（注入用） ==========
    llm_config: Optional[Dict]                # LLM配置，用于节点中获取LLM实例
    workflow_run_id: Optional[str]            # 配额幂等键，恢复时沿用
    prompt_version: Optional[str]              # 本轮使用的提示词契约版本

    # ========== 内部路由 ==========
    __next_node__: Optional[str]               # persist_node 设定阶段的目标节点
    __route__: Optional[str]                   # workflow_builder 条件路由用
    
    # ========== Agent 驱动路由（v2） ==========
    graph_version: Optional[str]               # "v1"(固定DAG) / "v2"(Agent驱动)
    phase: Optional[str]                       # "setup" / "writing" / "complete"
    next_tool: Optional[str]                   # router_agent 选定的下一个工具名
    router_reasoning: Optional[str]            # LLM 路由决策原因（调试用）
