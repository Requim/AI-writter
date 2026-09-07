export const workflowStatusLabels = {
  idle: '等待开始', running: '创作进行中', paused: '等待你的确认',
  recoverable: '进度已保留', stalled: '需要核对进度',
  cancelling: '正在停止', error: '当前步骤失败', completed: '章节已全部生成',
} as const

export const planningFieldLabels: Record<string, string> = {
  final_state: '最终局面', final_world_state: '最终世界状态', protagonist_final_state: '主角最终状态',
  ending_type: '结局类型', ending_tone: '结局基调', final_conflict: '最终冲突',
  resolution: '解决方式', main_conflict_resolution: '主线冲突结局',
  protagonist_fate: '主角归宿', final_choice: '最终选择', theme_resolution: '主题回应',
  reader_payoff: '读者期待的收束', open_questions: '保留悬念',
  required_payoffs: '必须回收的伏笔', forbidden_outcomes: '不可出现的结局',
  character_endings: '人物结局', unresolved_threads: '未收束线索',
  state_delta: '状态变化', plan_version: '整书规划版本', tactical_version: '近期推进版本',
  plan_fulfillment: '整书规划兑现', tactical_fulfillment: '近期推进兑现',
  state_delta_fulfilled: '状态变化已落实', must_happen_covered: '已完成关键事件',
  missing_required_events: '缺失关键事件', deferred_items: '延后事项',
  volume_boundary_breached: '跨越分卷边界', core_arc_breached: '偏离核心剧情',
  ending_contract_breached: '偏离结局要求', scale_change_required: '需要调整篇幅',
  tactical_goal_fulfilled: '章节目标已落实', approach_followed: '推进方式已落实',
  exit_hook_established: '章末悬念已建立', deviations: '偏差', notes: '备注',
  status: '状态', invalid_fields: '缺失或格式错误的项目',
}

export const reviewValueLabels: Record<string, string> = {
  high: '高', medium: '中', low: '低', must_fix: '必须修复', optional: '建议修改',
  can_ignore: '可保留', logic: '逻辑', pacing: '节奏', character: '人物',
  consistency: '一致性', continuity: '连续性', causality: '因果',
  unknown: '尚未确认', reviewed: '已检查', pass: '通过', human_review: '需要人工审阅',
  main: '主线', subplot: '支线', romance: '感情线', growth: '成长线',
  mystery: '悬疑线', conflict: '冲突线', fulfilled: '已兑现', deferred: '部分延后', breached: '需要调整',
}

export function planningFieldLabel(key: string): string {
  return planningFieldLabels[key] || (/[一-鿿]/.test(key) ? key : '补充设定')
}
