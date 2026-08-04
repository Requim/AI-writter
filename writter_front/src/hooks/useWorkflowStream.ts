import { useCallback, useReducer, useRef } from 'react'
import { streamWorkflow, WorkflowRequestError, type WorkflowRequest } from '@/api/workflow'
import { createIdempotencyKey } from '@/api/idempotency'
import { workflowApi } from '@/api/novel'
import type { InterruptInfo, WorkflowEvent, WorkflowSnapshot } from '@/types/novel'
import {
  initialWorkflowState,
  workflowReducer, type WorkflowAction,
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

function failureDetails(error: unknown) {
  if (!(error instanceof WorkflowRequestError)) {
    return { message: error instanceof Error ? error.message : '未知错误' }
  }
  return {
    message: error.message, code: error.code, node: error.node,
    retryable: error.retryable, retryAfter: error.retryAfter, retryCount: error.retryCount,
  }
}

type WorkflowDispatch = React.Dispatch<WorkflowAction>
type WorkflowSync = (force?: boolean) => Promise<WorkflowSnapshot | undefined>

function useSnapshotSync(threadId: string | undefined, dispatch: WorkflowDispatch): WorkflowSync {
  return useCallback(async (force = false) => {
    if (!threadId) return
    try {
      const snapshot = await workflowApi.state(threadId)
      dispatch({ type: 'snapshot', snapshot, force })
      dispatch({ type: 'sync_succeeded', at: new Date().toISOString() })
      return snapshot
    } catch (error) {
      dispatch({ type: 'sync_failed' })
      throw error
    }
  }, [dispatch, threadId])
}

function useRunCommand(
  threadId: string | undefined,
  dispatch: WorkflowDispatch,
  controllerRef: React.MutableRefObject<AbortController | null>,
  sync: WorkflowSync,
) {
  return useCallback(async (payload: WorkflowRequest, preserveDraft = false) => {
    if (!threadId) return
    const controller = replaceController(controllerRef)
    const commandId = createIdempotencyKey()
    dispatch({ type: 'start', preserveDraft, commandId })
    try {
      const result = await streamWorkflow(threadId, payload, (event) => {
        dispatch({ type: 'event', event })
        if (shouldSyncEvent(event)) void sync(true).catch(() => undefined)
      }, controller.signal, commandId)
      if (!result?.terminal && !controller.signal.aborted) dispatch({ type: 'detached' })
      if (!controller.signal.aborted) await sync(true).catch(() => undefined)
    } catch (error) {
      if (controller.signal.aborted) return
      if (shouldSyncRequest(error)) {
        try { await sync(true); return } catch { /* report the original command conflict */ }
      }
      dispatch({ type: 'failure', ...failureDetails(error) })
      await sync(true).catch(() => undefined)
    }
  }, [controllerRef, dispatch, sync, threadId])
}

function useCancelCommand(
  threadId: string | undefined,
  dispatch: WorkflowDispatch,
  controllerRef: React.MutableRefObject<AbortController | null>,
) {
  return useCallback(async () => {
    controllerRef.current?.abort()
    if (!threadId) return
    dispatch({ type: 'cancelling' })
    try {
      await workflowApi.cancel(threadId)
      dispatch({ type: 'cancelled' })
    } catch (error) {
      dispatch({ type: 'failure', ...failureDetails(error) })
    }
  }, [controllerRef, dispatch, threadId])
}

export function useWorkflowStream(threadId?: string) {
  const [state, dispatch] = useReducer(workflowReducer, initialWorkflowState)
  const controllerRef = useRef<AbortController | null>(null)
  const sync = useSnapshotSync(threadId, dispatch)
  const run = useRunCommand(threadId, dispatch, controllerRef, sync)
  const cancel = useCancelCommand(threadId, dispatch, controllerRef)

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
