import { useCallback, useReducer, useRef } from 'react'
import { streamWorkflow, WorkflowRequestError, type WorkflowRequest } from '@/api/workflow'
import { createIdempotencyKey } from '@/api/idempotency'
import { workflowApi } from '@/api/novel'
import type { InterruptInfo, WorkflowEvent, WorkflowSnapshot } from '@/types/novel'
import {
  initialWorkflowState,
  workflowReducer,
} from './workflowState'

export { initialWorkflowState, workflowReducer } from './workflowState'
export type { WorkflowViewState } from './workflowState'

const SNAPSHOT_SYNC_CODES = new Set([
  'workflow_command_in_progress',
  'workflow_command_already_applied',
  'stale_workflow_decision',
  'workflow_already_running',
])

function shouldSyncRequest(error: unknown): boolean {
  return error instanceof WorkflowRequestError
    && error.status === 409
    && (!error.code || SNAPSHOT_SYNC_CODES.has(error.code))
}

function shouldSyncEvent(event: WorkflowEvent): boolean {
  return event.type === 'error'
    && typeof event.data.code === 'string'
    && SNAPSHOT_SYNC_CODES.has(event.data.code)
}

function replaceController(ref: React.MutableRefObject<AbortController | null>): AbortController {
  ref.current?.abort()
  const controller = new AbortController()
  ref.current = controller
  return controller
}

export function useWorkflowStream(threadId?: string) {
  const [state, dispatch] = useReducer(workflowReducer, initialWorkflowState)
  const controllerRef = useRef<AbortController | null>(null)

  const sync = useCallback(async (force = false) => {
    if (!threadId) return
    const snapshot = await workflowApi.state(threadId)
    dispatch({ type: 'snapshot', snapshot, force })
    return snapshot
  }, [threadId])

  const run = useCallback(async (payload: WorkflowRequest, preserveDraft = false) => {
    if (!threadId) return
    const controller = replaceController(controllerRef)
    const commandId = createIdempotencyKey()
    dispatch({ type: 'start', preserveDraft, commandId })
    try {
      await streamWorkflow(threadId, payload, (event) => {
        dispatch({ type: 'event', event })
        if (shouldSyncEvent(event)) void sync(true).catch(() => undefined)
      }, controller.signal, commandId)
    } catch (error) {
      if (controller.signal.aborted) return
      if (shouldSyncRequest(error)) {
        try { await sync(true); return } catch { /* report the original command conflict */ }
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

  const retry = useCallback((autoMode: boolean) => run({
    command: { retry: true, _auto_mode: autoMode },
  }, true), [run])

  const hydrateInterrupt = useCallback((interrupt?: InterruptInfo) => dispatch({ type: 'hydrate', interrupt }), [])

  const hydrateSnapshot = useCallback((snapshot: WorkflowSnapshot) => {
    dispatch({ type: 'snapshot', snapshot })
  }, [])

  return { state, run, retry, resume, cancel, sync, hydrateInterrupt, hydrateSnapshot }
}
