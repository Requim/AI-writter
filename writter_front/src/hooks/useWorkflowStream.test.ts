import { describe, expect, it } from 'vitest'
import { initialWorkflowState, workflowReducer } from './useWorkflowStream'
import type { WorkflowEvent } from '@/types/novel'

function event(id: number, operation: 'append' | 'reset', text: string): WorkflowEvent {
  return {
    id,
    type: 'content_delta',
    thread_id: 'thread-1',
    node: 'chapter_writer_node',
    data: { operation, text },
    timestamp: '2026-07-15T00:00:00Z',
  }
}

describe('workflowReducer', () => {
  it('appends streamed content and resets before regeneration', () => {
    const first = workflowReducer(initialWorkflowState, { type: 'event', event: event(1, 'append', '旧稿') })
    const reset = workflowReducer(first, { type: 'event', event: event(2, 'reset', '') })
    const revised = workflowReducer(reset, { type: 'event', event: event(3, 'append', '新稿') })
    expect(revised.draft).toBe('新稿')
  })

  it('marks provider timeouts as retryable', () => {
    const failed = workflowReducer(initialWorkflowState, {
      type: 'event',
      event: {
        id: 4,
        type: 'error',
        thread_id: 'thread-1',
        data: {
          code: 'provider_timeout',
          message: '模型服务生成超时，请重试当前步骤',
          retryable: true,
          retry_after: 120,
        },
        timestamp: '2026-07-15T00:00:00Z',
      },
    })
    expect(failed.status).toBe('error')
    expect(failed.retryable).toBe(true)
    expect(failed.retryAfter).toBe(120)
  })
})
