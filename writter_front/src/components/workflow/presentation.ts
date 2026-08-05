import type { WorkflowViewState } from '@/hooks/useWorkflowStream'

export const nodeLabels: Record<string, string> = {
  type_confirmation: '确认题材', creative_brief_node: '凝练创作简报',
  creative_brief_review_node: '审阅创作简报', character_design_node: '设计核心角色',
  character_design_review_node: '审阅角色设计', title_node: '推敲书名',
  title_review_node: '选择书名', summary_node: '撰写简介', summary_review_node: '审阅简介',
  outline_node: '搭建总纲', outline_review_node: '审阅总纲', memory_retrieval_node: '检索前文',
  novel_plan_initialize_node: '初始化整书规划', novel_plan_volume_node: '生成分卷骨架',
  novel_plan_finalize_node: '校验整书规划', novel_plan_review_node: '审阅整书规划',
  plan_reconciliation_node: '核对计划兑现',
  chapter_outline_node: '设计细纲', chapter_outline_review_node: '细纲待审阅',
  chapter_writer_node: '撰写正文', chapter_compaction_node: '压缩冗余', reflection_node: '质量审读',
  reflection_review_node: '审阅质量报告',
  revision_node: '修订章节', revision_review_node: '确认修订', persist_node: '归档稿件',
  chapter_summary: '生成章节摘要', story_state: '更新故事状态',
  metadata_persist_node: '保存作品设定', progress_check_node: '核对进度', router_agent: '规划下一步',
}

export const nodeDescriptions: Record<string, string> = {
  type_confirmation: '正在确认作品题材和基础约束。', creative_brief_node: '正在明确故事母题、核心冲突与读者体验。',
  creative_brief_review_node: '创作简报已经生成，正在等待你的决定。', character_design_node: '正在设计人物动机、关系与典故姓名。',
  character_design_review_node: '角色与姓名候选已经生成，正在等待你的决定。', title_node: '正在生成或确认小说名称。',
  title_review_node: '书名候选已经生成，正在等待你的选择。', summary_node: '正在整理故事简介与内部策划摘要。',
  summary_review_node: '简介提案已经生成，正在等待你的决定。', outline_node: '正在构建世界观、角色、主线和分卷结构。',
  outline_review_node: '全书总纲已经生成，正在等待你的审阅。', memory_retrieval_node: '正在读取前文章节和人物状态。',
  novel_plan_initialize_node: '正在根据目标规模建立整书生产计划。', novel_plan_volume_node: '正在按卷生成全书章节骨架。',
  novel_plan_finalize_node: '正在闭合章节、分卷与总字数预算。', novel_plan_review_node: '整书规划已经生成，正在等待你的审阅。',
  plan_reconciliation_node: '正在核对本章对规划义务的兑现情况。',
  chapter_outline_node: '正在根据总纲设计当前章节细纲。', chapter_outline_review_node: '章节细纲已经生成，正在等待你的审阅。',
  chapter_writer_node: '正在根据细纲流式生成章节正文。', reflection_node: '正在检查情节、人物和语言质量。',
  reflection_review_node: '质量报告已经生成，正在等待你的决定。', revision_node: '正在按审读结果修订正文。',
  revision_review_node: '修订稿已经生成，正在等待你的确认。', chapter_compaction_node: '正在压缩重复表达并保留情节信息。',
  chapter_summary: '正在为已完成章节生成可检索摘要。', story_state: '正在更新人物、线索和连续性状态。',
  metadata_persist_node: '正在保存已经确认的书名和简介。',
  persist_node: '正在保存章节、进度和长期记忆。', progress_check_node: '正在核对章节进度并准备下一章。',
  router_agent: '正在根据当前创作状态安排下一步。',
}

export function formatTime(value?: string): string {
  if (!value || Number.isNaN(new Date(value).getTime())) return '尚无记录'
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(new Date(value))
}

export function formatElapsed(startedAt?: string, now = Date.now()): string | undefined {
  const started = Date.parse(startedAt ?? '')
  if (!Number.isFinite(started)) return undefined
  const seconds = Math.max(0, Math.floor((now - started) / 1000))
  const minutes = Math.floor(seconds / 60)
  return minutes ? `${minutes} 分 ${seconds % 60} 秒` : `${seconds} 秒`
}

export function formatSyncAge(value?: string, now = Date.now()): string {
  const synced = Date.parse(value ?? '')
  if (!Number.isFinite(synced)) return '等待首次同步'
  const seconds = Math.max(0, Math.floor((now - synced) / 1000))
  if (seconds < 60) return `${seconds} 秒前`
  return `${Math.floor(seconds / 60)} 分钟前`
}

export function chapterNumberFromState(state: WorkflowViewState): number | undefined {
  const number = state.interrupt?.chapter_number
  if (typeof number === 'number') return number
  if (typeof state.checkpointChapterIndex === 'number') return state.checkpointChapterIndex + 1
  const match = state.reasoning?.match(/第\s*(\d+)\s*章/)
  return match ? Number(match[1]) : undefined
}

const reviewNodes: Record<string, string> = {
  review_or_modify_creative_brief: 'creative_brief_review_node',
  review_or_modify_character_design: 'character_design_review_node',
  confirm_or_provide_title: 'title_review_node', confirm_or_provide_summary: 'summary_review_node',
  summary_review_required: 'summary_review_node',
  review_or_modify_outline: 'outline_review_node', review_or_provide_chapter_outline: 'chapter_outline_review_node',
  review_or_modify_novel_plan: 'novel_plan_review_node', review_novel_plan: 'novel_plan_review_node',
  review_reflection_issues: 'reflection_review_node', quality_gate_exhausted: 'reflection_review_node',
  quality_gate_human_review: 'reflection_review_node', confirm_revision: 'revision_review_node',
  quality_review_unavailable: 'reflection_review_node',
}

export function presentationNode(state: WorkflowViewState): string {
  if (state.status !== 'paused' || !state.interrupt) return state.activeNode ?? ''
  return reviewNodes[state.interrupt.action] || state.activeNode || ''
}

export function stagePresentation(state: WorkflowViewState, chapterPrefix: string) {
  if (state.status === 'completed') return {
    label: '全书创作完成', description: '计划章节已全部归档，可以查看、编辑或导出完整书稿。',
  }
  const node = presentationNode(state)
  const label = nodeLabels[node] ?? '当前步骤'
  const chapterNodes = ['chapter_outline_node', 'chapter_outline_review_node', 'chapter_writer_node',
    'reflection_node', 'reflection_review_node', 'revision_node', 'revision_review_node',
    'chapter_compaction_node', 'chapter_summary', 'story_state', 'persist_node']
  const contextualLabel = chapterNodes.includes(node) ? `${chapterPrefix}${label}` : label
  if (state.status === 'error') return { label: `${contextualLabel}失败`, description: state.error || '当前步骤未能完成。' }
  if (state.status === 'recoverable') return {
    label: `${contextualLabel}可继续`,
    description: state.hasCheckpointDraft ? '本章草稿和创作进度均已保留，继续后不会重写前文。' : '创作进度已保留，可以从当前步骤继续。',
  }
  return { label: node ? contextualLabel : '等待开始创作', description: nodeDescriptions[node] ?? '尚未开始本轮创作。' }
}

export function completedTimeline(state: WorkflowViewState): string[] {
  return state.events
    .filter((event) => event.type === 'status' && event.data.status === 'completed' && event.node !== 'router_agent')
    .map((event) => event.node as string)
    .filter((node, index, nodes) => index === 0 || node !== nodes[index - 1])
    .slice(-7)
}

export function qualityScoreOutOfFive(score: number): number {
  if (score <= 1) return score * 5
  if (score <= 5) return score
  if (score <= 10) return score / 2
  return score / 20
}
