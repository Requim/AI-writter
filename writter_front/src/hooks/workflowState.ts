import type { InterruptInfo, ReflectionIssue, WorkflowEvent, WorkflowSnapshot } from '@/types/novel'

export interface WorkflowViewState {
  status: 'idle' | 'running' | 'paused' | 'recoverable' | 'error' | 'stalled' | 'cancelling'
  connection: 'idle' | 'streaming' | 'detached'
  draft: string
  issues: ReflectionIssue[]
  events: WorkflowEvent[]
  activeNode?: string
  activeCommandId?: string
  stageStartedAt?: string
  reasoning?: string
  qualityScore?: number
  interrupt?: InterruptInfo
  progress?: number
  retryable?: boolean
  retryAfter?: number
  error?: string
  startedAt?: string
  lastActivityAt?: string
  isStale?: boolean
  hasCheckpointDraft?: boolean
  hasPendingCheckpoint?: boolean
  checkpointChapterIndex?: number
  lastPersistedChapterId?: string
  currentChapter?: number
  metadataUpdatedAt?: string
  metadata?: { title?: string; summary?: string }
}

export type WorkflowAction =
  | { type: 'start'; commandId: string; preserveDraft?: boolean }
  | { type: 'event'; event: WorkflowEvent }
  | { type: 'failure'; message: string }
  | { type: 'snapshot'; snapshot: WorkflowSnapshot; force?: boolean }
  | { type: 'cancelling' }
  | { type: 'cancelled' }
  | { type: 'hydrate'; interrupt?: InterruptInfo }

export const initialWorkflowState: WorkflowViewState = {
  status: 'idle', connection: 'idle', draft: '', issues: [], events: [],
}

const interruptNodes: Record<string, string> = {
  require_novel_type: 'type_confirmation',
  review_or_modify_creative_brief: 'creative_brief_review_node',
  confirm_or_provide_title: 'title_review_node',
  confirm_or_provide_summary: 'summary_review_node',
  review_or_modify_outline: 'outline_review_node',
  review_or_provide_chapter_outline: 'chapter_outline_review_node',
  review_reflection_issues: 'reflection_review_node',
  quality_gate_exhausted: 'reflection_review_node',
  quality_gate_human_review: 'reflection_review_node',
  quality_review_unavailable: 'reflection_review_node',
  confirm_revision: 'revision_review_node',
  ready_for_next_chapter: 'progress_check_node',
}

export function nodeForInterrupt(interrupt?: InterruptInfo): string | undefined {
  return interrupt ? interruptNodes[interrupt.action] : undefined
}

function startState(state: WorkflowViewState, action: Extract<WorkflowAction, { type: 'start' }>) {
  const now = new Date().toISOString()
  return {
    ...state, status: 'running' as const, connection: 'streaming' as const,
    draft: action.preserveDraft ? state.draft : '', activeNode: undefined,
    activeCommandId: action.commandId, stageStartedAt: undefined, reasoning: undefined,
    qualityScore: undefined, issues: [], interrupt: undefined, events: [], error: undefined,
    retryable: undefined, retryAfter: undefined, isStale: false,
    hasPendingCheckpoint: false, checkpointChapterIndex: undefined,
    startedAt: now, lastActivityAt: now,
  }
}

function snapshotIsOld(state: WorkflowViewState, snapshot: WorkflowSnapshot, force = false): boolean {
  if (force || !state.activeCommandId || state.status !== 'running') return false
  const serverCommand = snapshot.execution?.command_id
  if (serverCommand) return serverCommand !== state.activeCommandId
  const localStart = Date.parse(state.startedAt ?? '')
  const serverStart = Date.parse(snapshot.execution?.started_at ?? '')
  return Number.isFinite(localStart) && Number.isFinite(serverStart) && serverStart < localStart
}

function snapshotStatus(snapshot: WorkflowSnapshot, hasDraft: boolean, hasPending: boolean) {
  if (snapshot.interrupts?.[0]) return 'paused' as const
  if (snapshot.status === 'running' && snapshot.execution?.is_stale) return 'stalled' as const
  if (snapshot.status === 'running') return 'running' as const
  return hasDraft || hasPending ? 'recoverable' as const : 'idle' as const
}

function reduceSnapshot(state: WorkflowViewState, snapshot: WorkflowSnapshot): WorkflowViewState {
  const execution = snapshot.execution
  const interrupt = snapshot.interrupts?.[0]
  const hasDraft = snapshot.state?.has_current_chapter_content === true
  const hasPending = !interrupt && Boolean(snapshot.next_nodes?.length)
  const status = snapshotStatus(snapshot, hasDraft, hasPending)
  const checkpointIndex = snapshot.state?.current_chapter_index
  const progress = snapshot.state?.progress_percentage
  const checkpointReason = snapshot.state?.router_reasoning
  return {
    ...state, status,
    connection: snapshot.status === 'running' ? 'detached' : 'idle',
    activeNode: nodeForInterrupt(interrupt) || execution?.active_node || snapshot.next_nodes?.[0],
    activeCommandId: execution?.command_id || state.activeCommandId,
    stageStartedAt: execution?.stage_started_at || execution?.started_at,
    interrupt,
    reasoning: interrupt?.message || execution?.message
      || (typeof checkpointReason === 'string' ? checkpointReason : state.reasoning),
    startedAt: execution?.started_at || state.startedAt,
    lastActivityAt: execution?.last_activity_at || state.lastActivityAt,
    isStale: status === 'stalled',
    error: status === 'stalled' ? '任务已长时间没有产生新进展，可能因页面断线或模型请求异常而停滞。' : undefined,
    retryable: status === 'stalled' || state.retryable,
    hasCheckpointDraft: hasDraft, hasPendingCheckpoint: hasPending,
    checkpointChapterIndex: typeof checkpointIndex === 'number' ? checkpointIndex : undefined,
    currentChapter: typeof checkpointIndex === 'number' ? checkpointIndex : state.currentChapter,
    progress: typeof progress === 'number' ? progress : undefined,
  }
}

function eventCommandId(event: WorkflowEvent): string | undefined {
  return event.command_id || (typeof event.data.command_id === 'string' ? event.data.command_id : undefined)
}

function eventIsCurrent(state: WorkflowViewState, event: WorkflowEvent): boolean {
  const commandId = eventCommandId(event)
  return !state.activeCommandId || !commandId || commandId === state.activeCommandId
}

function reduceStatusEvent(next: WorkflowViewState, event: WorkflowEvent): void {
  const status = event.data.status
  const nextNode = typeof event.data.next_node === 'string' ? event.data.next_node : undefined
  if (nextNode) next.activeNode = nextNode
  else if (status === 'completed' && next.activeNode === event.node) next.activeNode = undefined
  else if (status !== 'completed') next.activeNode = event.node
  if (status === 'started') {
    next.stageStartedAt = typeof event.data.started_at === 'string' ? event.data.started_at : event.timestamp
  }
}

function reduceChapterEvent(next: WorkflowViewState, event: WorkflowEvent): void {
  next.draft = ''
  next.hasCheckpointDraft = false
  next.lastPersistedChapterId = typeof event.data.chapter_id === 'string' ? event.data.chapter_id : undefined
  next.currentChapter = typeof event.data.current_chapter === 'number'
    ? event.data.current_chapter : next.currentChapter
  if (typeof event.data.percentage === 'number') next.progress = event.data.percentage
}

function reduceTypedEvent(next: WorkflowViewState, event: WorkflowEvent): void {
  if (event.type === 'status') reduceStatusEvent(next, event)
  if (event.type === 'chapter_persisted') reduceChapterEvent(next, event)
  if (event.type === 'reasoning') {
    if (typeof event.data.text === 'string') next.reasoning = event.data.text
    if (typeof event.data.next_node === 'string') next.activeNode = event.data.next_node
  }
  if (event.type === 'quality') {
    next.qualityScore = typeof event.data.score === 'number' ? event.data.score : undefined
    next.issues = Array.isArray(event.data.issues) ? event.data.issues as ReflectionIssue[] : []
  }
  if (event.type === 'progress' && typeof event.data.percentage === 'number') next.progress = event.data.percentage
  if (event.type === 'metadata_updated') {
    next.metadataUpdatedAt = event.timestamp
    next.metadata = {
      ...(typeof event.data.title === 'string' ? { title: event.data.title } : {}),
      ...(typeof event.data.summary === 'string' ? { summary: event.data.summary } : {}),
    }
  }
}

function reduceTerminalEvent(next: WorkflowViewState, event: WorkflowEvent): void {
  if (event.type === 'interrupt') {
    const interrupts = event.data.interrupts
    next.interrupt = Array.isArray(interrupts) ? interrupts[0] as InterruptInfo : undefined
    next.activeNode = nodeForInterrupt(next.interrupt) || next.activeNode
    next.reasoning = next.interrupt?.message || next.reasoning
    next.status = 'paused'
    next.connection = 'idle'
  }
  if (event.type === 'completed') {
    next.connection = 'idle'
    next.hasCheckpointDraft = false
    next.hasPendingCheckpoint = false
    if (next.status !== 'paused') next.status = 'idle'
  }
  if (event.type === 'error') {
    next.status = 'error'
    next.connection = 'idle'
    next.error = typeof event.data.message === 'string' ? event.data.message : '工作流执行失败'
    next.retryable = event.data.retryable === true
    next.retryAfter = typeof event.data.retry_after === 'number' ? event.data.retry_after : undefined
  }
}

function reduceEvent(state: WorkflowViewState, event: WorkflowEvent): WorkflowViewState {
  if (!eventIsCurrent(state, event)) return state
  const next = {
    ...state,
    events: [...state.events.slice(-39), event],
    lastActivityAt: event.type === 'heartbeat' ? state.lastActivityAt : event.timestamp,
  }
  if (event.type === 'content_delta') {
    const text = typeof event.data.text === 'string' ? event.data.text : ''
    next.draft = event.data.operation === 'reset' ? text : state.draft + text
  }
  reduceTypedEvent(next, event)
  reduceTerminalEvent(next, event)
  return next
}

export function workflowReducer(state: WorkflowViewState, action: WorkflowAction): WorkflowViewState {
  if (action.type === 'start') return startState(state, action)
  if (action.type === 'event') return reduceEvent(state, action.event)
  if (action.type === 'snapshot') {
    return snapshotIsOld(state, action.snapshot, action.force) ? state : reduceSnapshot(state, action.snapshot)
  }
  if (action.type === 'failure') return { ...state, status: 'error', connection: 'idle', error: action.message }
  if (action.type === 'cancelling') return { ...state, status: 'cancelling' }
  if (action.type === 'cancelled') return {
    ...state, status: 'idle', connection: 'idle', activeNode: undefined,
    activeCommandId: undefined, error: undefined, isStale: false,
  }
  return {
    ...state, status: action.interrupt ? 'paused' : state.status,
    activeNode: nodeForInterrupt(action.interrupt) || state.activeNode,
    reasoning: action.interrupt?.message || state.reasoning,
    interrupt: action.interrupt,
  }
}
