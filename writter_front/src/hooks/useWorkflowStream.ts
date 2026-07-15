import { useCallback, useReducer, useRef } from 'react'
import { streamWorkflow, WorkflowRequestError, type WorkflowRequest } from '@/api/workflow'
import { workflowApi } from '@/api/novel'
import type { InterruptInfo, ReflectionIssue, WorkflowEvent, WorkflowSnapshot } from '@/types/novel'

export interface WorkflowViewState {
  status: 'idle' | 'running' | 'paused' | 'error' | 'stalled' | 'cancelling'
  connection: 'idle' | 'streaming' | 'detached'
  draft: string
  activeNode?: string
  reasoning?: string
  qualityScore?: number
  issues: ReflectionIssue[]
  interrupt?: InterruptInfo
  progress?: number
  retryable?: boolean
  retryAfter?: number
  events: WorkflowEvent[]
  error?: string
  startedAt?: string
  lastActivityAt?: string
  isStale?: boolean
}

type Action =
  | { type: 'start' }
  | { type: 'event'; event: WorkflowEvent }
  | { type: 'failure'; message: string }
  | { type: 'snapshot'; snapshot: WorkflowSnapshot }
  | { type: 'cancelling' }
  | { type: 'cancelled' }
  | { type: 'hydrate'; interrupt?: InterruptInfo }

export const initialWorkflowState: WorkflowViewState = {
  status: 'idle',
  connection: 'idle',
  draft: '',
  issues: [],
  events: [],
}

export function workflowReducer(state: WorkflowViewState, action: Action): WorkflowViewState {
  if (action.type === 'start') return {
    ...state,
    status: 'running',
    connection: 'streaming',
    interrupt: undefined,
    error: undefined,
    retryable: undefined,
    retryAfter: undefined,
    isStale: false,
    startedAt: new Date().toISOString(),
    lastActivityAt: new Date().toISOString(),
  }
  if (action.type === 'failure') return { ...state, status: 'error', connection: 'idle', error: action.message }
  if (action.type === 'cancelling') return { ...state, status: 'cancelling' }
  if (action.type === 'cancelled') return {
    ...state,
    status: 'idle',
    connection: 'idle',
    activeNode: undefined,
    error: undefined,
    isStale: false,
  }
  if (action.type === 'snapshot') {
    const { snapshot } = action
    const execution = snapshot.execution
    const interrupt = snapshot.interrupts?.[0]
    const activeNode = execution?.active_node || snapshot.next_nodes?.[0]
    const isStale = snapshot.status === 'running' && execution?.is_stale === true
    const status: WorkflowViewState['status'] = interrupt
      ? 'paused'
      : isStale
        ? 'stalled'
        : snapshot.status === 'running'
          ? 'running'
          : 'idle'
    const checkpointReason = snapshot.state?.router_reasoning
    return {
      ...state,
      status,
      connection: snapshot.status === 'running' ? 'detached' : 'idle',
      activeNode,
      interrupt,
      reasoning: execution?.message || (typeof checkpointReason === 'string' ? checkpointReason : state.reasoning),
      startedAt: execution?.started_at,
      lastActivityAt: execution?.last_activity_at,
      isStale,
      error: isStale ? '任务已长时间没有产生新进展，可能因页面断线或模型请求异常而停滞。' : undefined,
      retryable: isStale || state.retryable,
    }
  }
  if (action.type === 'hydrate') return {
    ...state,
    status: action.interrupt ? 'paused' : state.status,
    interrupt: action.interrupt,
  }

  const event = action.event
  const next: WorkflowViewState = {
    ...state,
    events: [...state.events.slice(-39), event],
    lastActivityAt: event.type === 'heartbeat' ? state.lastActivityAt : event.timestamp,
  }
  if (event.type === 'content_delta') {
    const text = typeof event.data.text === 'string' ? event.data.text : ''
    next.draft = event.data.operation === 'reset' ? text : state.draft + text
  }
  if (event.type === 'status') next.activeNode = event.node
  if (event.type === 'reasoning' && typeof event.data.text === 'string') next.reasoning = event.data.text
  if (event.type === 'quality') {
    next.qualityScore = typeof event.data.score === 'number' ? event.data.score : undefined
    next.issues = Array.isArray(event.data.issues) ? (event.data.issues as ReflectionIssue[]) : []
  }
  if (event.type === 'progress' && typeof event.data.percentage === 'number') next.progress = event.data.percentage
  if (event.type === 'interrupt') {
    const interrupts = event.data.interrupts
    next.interrupt = Array.isArray(interrupts) ? (interrupts[0] as InterruptInfo) : undefined
    next.status = 'paused'
    next.connection = 'idle'
  }
  if (event.type === 'completed') {
    next.connection = 'idle'
    if (next.status !== 'paused') next.status = 'idle'
  }
  if (event.type === 'error') {
    next.status = 'error'
    next.connection = 'idle'
    next.error = typeof event.data.message === 'string' ? event.data.message : '工作流执行失败'
    next.retryable = event.data.retryable === true
    next.retryAfter = typeof event.data.retry_after === 'number' ? event.data.retry_after : undefined
  }
  return next
}

export function useWorkflowStream(threadId?: string) {
  const [state, dispatch] = useReducer(workflowReducer, initialWorkflowState)
  const controllerRef = useRef<AbortController | null>(null)

  const sync = useCallback(async () => {
    if (!threadId) return
    const snapshot = await workflowApi.state(threadId)
    dispatch({ type: 'snapshot', snapshot })
    return snapshot
  }, [threadId])

  const run = useCallback(async (payload: WorkflowRequest) => {
    if (!threadId) return
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    dispatch({ type: 'start' })
    try {
      await streamWorkflow(threadId, payload, (event) => dispatch({ type: 'event', event }), controller.signal)
    } catch (error) {
      if (controller.signal.aborted) return
      if (error instanceof WorkflowRequestError && error.status === 409) {
        try {
          await sync()
          return
        } catch {
          dispatch({ type: 'failure', message: error.message })
          return
        }
      }
      dispatch({ type: 'failure', message: error instanceof Error ? error.message : '未知错误' })
    }
  }, [sync, threadId])

  const cancel = useCallback(async () => {
    controllerRef.current?.abort()
    if (!threadId) return
    dispatch({ type: 'cancelling' })
    try {
      await workflowApi.cancel(threadId)
      dispatch({ type: 'cancelled' })
    } catch (error) {
      dispatch({ type: 'failure', message: error instanceof Error ? error.message : '无法结束当前任务' })
    }
  }, [threadId])

  const resume = useCallback((value: unknown, autoMode: boolean) => run({
    command: { resume: value, _auto_mode: autoMode },
  }), [run])

  const hydrateInterrupt = useCallback((interrupt?: InterruptInfo) => {
    dispatch({ type: 'hydrate', interrupt })
  }, [])

  const hydrateSnapshot = useCallback((snapshot: WorkflowSnapshot) => {
    dispatch({ type: 'snapshot', snapshot })
  }, [])

  return { state, run, resume, cancel, sync, hydrateInterrupt, hydrateSnapshot }
}
