"""LangGraph Agent状态定义"""
from typing import Annotated, Any, List, Optional, Dict, Literal
from operator import add
from typing_extensions import TypedDict


class PendingProposal(TypedDict):
    """等待人工确认的、已持久化到 checkpoint 的生成提案。"""

    proposal_id: str
    kind: Literal[
        "creative_brief",
        "character_design",
        "title",
        "summary",
        "outline",
        "novel_plan",
        "chapter_plan",
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
    target_total_words: Optional[int]         # 用户计划总字数（软目标）
    scale_contract: Optional[Dict]             # 服务端确认的规模契约
    requested_writing_style: Optional[str]    # 用户指定写作风格（约束AI生成总纲）
    creative_brief: Optional[Dict]            # 创作简报（母题、冲突、读者承诺与内容边界）
    creative_brief_feedback: Optional[str]    # 用户对创作简报的修改要求
    character_design: Optional[Dict]           # 已确认角色表、命名策略与关系轴
    character_design_feedback: Optional[str]  # 用户对角色设计的重生成要求
    character_design_return_to: Optional[str] # 旧 checkpoint 补做角色设计后的返回节点
    title_feedback: Optional[str]              # 用户对书名提案的修改要求
    summary_feedback: Optional[str]            # 用户对简介提案的修改要求
    outline_feedback: Optional[str]            # 用户对宏观总纲的修改要求
    chapter_outline_feedback: Optional[str]    # 用户对当前章节细纲的修改要求
    total_outline: Optional[Dict]            # 总纲领（用户优先，空则AI生成）
    chapter_outlines_input: Optional[Dict]    # 用户提供的章节细纲（优先使用）
    
    # ========== 系统生成区 ==========
    generated_title: Optional[str]            # AI生成的书名（当用户未提供时）
    title_story_hint: Optional[str]           # AI生成书名时附带的"一句话卖点"，联动传给简介生成
    generated_summary: Optional[str]          # AI生成的简介
    editorial_summary: Optional[str]          # 供总纲规划使用的内部简介
    generated_outline: Optional[Dict]         # AI生成的总纲领
    novel_plan: Optional[Dict]                 # 当前已接受的整书计划
    plan_generation: Optional[Dict]            # 分卷批次生成 checkpoint
    plan_feedback: Optional[str]               # 计划重生成要求
    plan_replan_request: Optional[Dict]         # 用户或漂移触发的重规划请求
    plan_fulfillment: Optional[Dict]            # 当前章计划兑现结果
    plan_drift_severity: Optional[str]          # none/minor/major
    tactical_window: Optional[Dict]             # 当前章的战术窗口（候选或已接受）
    tactical_previous_window: Optional[Dict]    # 生成候选时的上一已接受窗口
    tactical_window_expected_version: Optional[int]  # 战术追加版本基线
    tactical_window_persisted: Optional[bool]   # 当前窗口是否已写入版本仓储
    chapter_quota_reserved_for_chapter: Optional[int]  # 已预占额度的 0 基章节号
    tactical_plan_feedback: Optional[str]       # 战术层审核修改指令
    chapter_plan_revision_scope: Optional[str]  # tactical/chapter_outline/both
    story_state_needs_reconciliation: Optional[bool]  # 回退后禁止复用旧窗口
    last_persisted_chapter: Optional[Dict]      # 正文后对账的最小持久化回执
    rewrite_chapter_id: Optional[str]           # 独立重写时保持章节资源标识不变
    rewrite_chapter_version: Optional[int]      # 独立重写前的乐观锁版本
    rewrite_chapter_created_at: Optional[Any]   # 独立重写时保留首次创建时间
    pending_proposal: Optional[PendingProposal]  # 当前等待审核的生成提案
    pending_proposal_decision: Optional[Any]     # 仅用于恢复旧 checkpoint 的一次性决定
    proposal_versions: Dict[str, int]          # 每类提案的单调版本号
    workflow_schema_version: int               # checkpoint 状态契约版本
    legacy_revision_recompute_done: Optional[bool]  # 旧修订预览是否已兼容重算
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
