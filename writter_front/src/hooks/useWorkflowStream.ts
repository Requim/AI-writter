import { useCallback, useReducer, useRef } from 'react'
import { streamWorkflow, type WorkflowRequest } from '@/api/workflow'
import { workflowApi } from '@/api/novel'
import type { InterruptInfo, ReflectionIssue, WorkflowEvent } from '@/types/novel'

export interface WorkflowViewState {
  status: 'idle' | 'running' | 'paused' | 'error'
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
}

type Action =
  | { type: 'start' }
  | { type: 'event'; event: WorkflowEvent }
  | { type: 'failure'; message: string }
  | { type: 'cancelled' }
  | { type: 'hydrate'; interrupt?: InterruptInfo }

export const initialWorkflowState: WorkflowViewState = {
  status: 'idle',
  draft: '',
  issues: [],
  events: [],
}

export function workflowReducer(state: WorkflowViewState, action: Action): WorkflowViewState {
  if (action.type === 'start') return {
    ...state,
    status: 'running',
    interrupt: undefined,
    error: undefined,
    retryable: undefined,
    retryAfter: undefined,
  }
  if (action.type === 'failure') return { ...state, status: 'error', error: action.message }
  if (action.type === 'cancelled') return { ...state, status: 'idle', activeNode: undefined }
  if (action.type === 'hydrate') return {
    ...state,
    status: action.interrupt ? 'paused' : state.status,
    interrupt: action.interrupt,
  }

  const event = action.event
  const next: WorkflowViewState = { ...state, events: [...state.events.slice(-39), event] }
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
  }
  if (event.type === 'completed' && next.status !== 'paused') next.status = 'idle'
  if (event.type === 'error') {
    next.status = 'error'
    next.error = typeof event.data.message === 'string' ? event.data.message : '工作流执行失败'
    next.retryable = event.data.retryable === true
    next.retryAfter = typeof event.data.retry_after === 'number' ? event.data.retry_after : undefined
  }
  return next
}

export function useWorkflowStream(threadId?: string) {
  const [state, dispatch] = useReducer(workflowReducer, initialWorkflowState)
  const controllerRef = useRef<AbortController | null>(null)

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
      dispatch({ type: 'failure', message: error instanceof Error ? error.message : '未知错误' })
    }
  }, [threadId])

  const cancel = useCallback(async () => {
    controllerRef.current?.abort()
    if (threadId) await workflowApi.cancel(threadId)
    dispatch({ type: 'cancelled' })
  }, [threadId])

  const resume = useCallback((value: unknown, autoMode: boolean) => run({
    command: { resume: value, _auto_mode: autoMode },
  }), [run])

  const hydrateInterrupt = useCallback((interrupt?: InterruptInfo) => {
    dispatch({ type: 'hydrate', interrupt })
  }, [])

  return { state, run, resume, cancel, hydrateInterrupt }
}
