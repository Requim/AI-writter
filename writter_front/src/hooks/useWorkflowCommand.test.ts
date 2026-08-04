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

  it('detaches and forces a snapshot sync when SSE ends without a terminal event', async () => {
    streamMock.mockResolvedValue({ terminal: false })
    stateMock.mockResolvedValue({
      thread_id: 'thread-1', status: 'running', has_interrupt: false, interrupts: [], state: {},
      execution: { command_id: 'server-command', active_node: 'chapter_writer_node' },
    })
    const { result } = renderHook(() => useWorkflowStream('thread-1'))
    await act(async () => result.current.run({ command: { retry: true } }))
    expect(stateMock).toHaveBeenCalledWith('thread-1')
    expect(result.current.state.connection).toBe('detached')
    expect(result.current.state.activeNode).toBe('chapter_writer_node')
  })

  it('syncs the authoritative snapshot after a normal terminal event', async () => {
    streamMock.mockImplementation(async (_thread, _payload, onEvent) => {
      onEvent({
        id: 1, type: 'interrupt', thread_id: 'thread-1', data: { interrupts: [] },
        timestamp: '2026-08-04T00:00:00Z',
      })
      return { terminal: true }
    })
    const { result } = renderHook(() => useWorkflowStream('thread-1'))
    await act(async () => result.current.run({ input: { novel_id: 'novel-1' } }))
    expect(stateMock).toHaveBeenCalledTimes(1)
    expect(result.current.state.interrupt?.message).toBe('请重新审阅现场')
  })

  it('keeps diagnostics and immediately syncs after an ordinary command failure', async () => {
    streamMock.mockRejectedValue(new Error('网络连接中断'))
    stateMock.mockResolvedValue({
      thread_id: 'thread-1', status: 'idle', has_interrupt: false, interrupts: [], state: {},
    })
    const { result } = renderHook(() => useWorkflowStream('thread-1'))
    await act(async () => result.current.run({ command: { retry: true } }))
    expect(stateMock).toHaveBeenCalledWith('thread-1')
    expect(result.current.state.error).toBe('网络连接中断')
    expect(result.current.state.lastSyncedAt).toBeTruthy()
  })

  it('tracks consecutive sync failures and resets health after recovery', async () => {
    stateMock.mockRejectedValue(new Error('state unavailable'))
    const { result } = renderHook(() => useWorkflowStream('thread-1'))
    await act(async () => { await result.current.sync().catch(() => undefined) })
    await act(async () => { await result.current.sync().catch(() => undefined) })
    expect(result.current.state.connectionRecovering).toBe(true)
    stateMock.mockResolvedValue(pausedSnapshot)
    await act(async () => { await result.current.sync() })
    expect(result.current.state).toMatchObject({
      connectionRecovering: false, consecutiveSyncFailures: 0,
    })
  })
})
