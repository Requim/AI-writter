import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { WorkflowEvent, WorkflowSnapshot } from '@/types/novel'

const { stateMock, streamMock } = vi.hoisted(() => ({
  stateMock: vi.fn(),
  streamMock: vi.fn(),
}))

vi.mock('@/api/novel', () => ({ workflowApi: { state: stateMock } }))
vi.mock('@/api/workflow', () => {
  class WorkflowRequestError extends Error {
    readonly status: number
    readonly code?: string

    constructor(message: string, status: number, code?: string) {
      super(message)
      this.status = status
      this.code = code
    }
  }
  return { streamWorkflow: streamMock, WorkflowRequestError }
})

import { WorkflowRequestError } from '@/api/workflow'
import { useWorkflowStream } from './useWorkflowStream'

const pausedSnapshot: WorkflowSnapshot = {
  thread_id: 'thread-1', status: 'paused', has_interrupt: true,
  interrupts: [{ action: 'confirm_or_provide_title', message: '请重新审阅现场' }], state: {},
}

describe('useWorkflowStream command reconciliation', () => {
  beforeEach(() => {
    stateMock.mockReset().mockResolvedValue(pausedSnapshot)
    streamMock.mockReset()
  })

  it('synchronizes the checkpoint after an idempotency conflict', async () => {
    streamMock.mockRejectedValue(new WorkflowRequestError(
      '命令正在执行', 409, 'workflow_command_in_progress',
    ))
    const { result } = renderHook(() => useWorkflowStream('thread-1'))
    await act(async () => result.current.run({ command: { retry: true } }))
    expect(stateMock).toHaveBeenCalledWith('thread-1')
    expect(result.current.state.interrupt?.message).toBe('请重新审阅现场')
  })

  it('synchronizes when a stale proposal arrives inside the SSE stream', async () => {
    streamMock.mockImplementation(async (_thread, _payload, onEvent) => {
      const event: WorkflowEvent = {
        id: 1, type: 'error', thread_id: 'thread-1',
        data: { code: 'stale_workflow_decision', message: '提案已过期' },
        timestamp: '2026-08-03T00:00:00Z',
      }
      onEvent(event)
    })
    const { result } = renderHook(() => useWorkflowStream('thread-1'))
    await act(async () => result.current.run({ command: { resume: 'accept' } }))
    await waitFor(() => expect(stateMock).toHaveBeenCalledWith('thread-1'))
    expect(result.current.state.status).toBe('paused')
  })
})
