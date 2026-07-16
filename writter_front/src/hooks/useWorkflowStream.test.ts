import { describe, expect, it } from 'vitest'
import { initialWorkflowState, workflowReducer } from './useWorkflowStream'
import type { WorkflowEvent, WorkflowSnapshot } from '@/types/novel'

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

  it('hydrates a detached stale execution with its current stage', () => {
    const snapshot: WorkflowSnapshot = {
      thread_id: 'thread-1',
      status: 'running',
      has_interrupt: false,
      interrupts: [],
      next_nodes: ['outline_node'],
      execution: {
        status: 'running',
        active_node: 'outline_node',
        message: '正在构建宏观总纲',
        started_at: '2026-07-15T10:00:00Z',
        last_activity_at: '2026-07-15T10:05:00Z',
        is_stale: true,
      },
      state: {},
    }

    const hydrated = workflowReducer(initialWorkflowState, { type: 'snapshot', snapshot })
    expect(hydrated.status).toBe('stalled')
    expect(hydrated.connection).toBe('detached')
    expect(hydrated.activeNode).toBe('outline_node')
    expect(hydrated.reasoning).toBe('正在构建宏观总纲')
    expect(hydrated.error).not.toContain('{"detail"')
  })

  it('starts a clean execution timeline for every run', () => {
    const dirtyState = {
      ...initialWorkflowState,
      draft: '上一轮正文',
      activeNode: 'router_agent',
      reasoning: 'router_agent 已完成',
      events: [{
        id: 1,
        type: 'status' as const,
        thread_id: 'thread-1',
        node: 'router_agent',
        data: { status: 'completed' },
        timestamp: '2026-07-15T00:00:00Z',
      }],
    }
    const started = workflowReducer(dirtyState, { type: 'start' })
    expect(started.draft).toBe('')
    expect(started.activeNode).toBeUndefined()
    expect(started.reasoning).toBeUndefined()
    expect(started.events).toEqual([])
  })

  it('preserves streamed draft when retrying a failed checkpoint', () => {
    const started = workflowReducer({
      ...initialWorkflowState,
      draft: '第二章草稿',
      status: 'error',
    }, { type: 'start', preserveDraft: true })

    expect(started.draft).toBe('第二章草稿')
    expect(started.status).toBe('running')
  })

  it('hydrates the presence of a private checkpoint draft without exposing its text', () => {
    const snapshot: WorkflowSnapshot = {
      thread_id: 'thread-1',
      status: 'idle',
      has_interrupt: false,
      interrupts: [],
      state: { has_current_chapter_content: true },
    }

    const hydrated = workflowReducer(initialWorkflowState, { type: 'snapshot', snapshot })
    expect(hydrated.hasCheckpointDraft).toBe(true)
    expect(hydrated.draft).toBe('')
  })

  it('keeps the routed business node active after router completion', () => {
    const reasoning = workflowReducer(initialWorkflowState, {
      type: 'event',
      event: {
        id: 1,
        type: 'reasoning',
        thread_id: 'thread-1',
        node: 'router_agent',
        data: { text: '第1章尚无细纲，先生成细纲', next_node: 'chapter_outline_node' },
        timestamp: '2026-07-15T00:00:00Z',
      },
    })
    const completed = workflowReducer(reasoning, {
      type: 'event',
      event: {
        id: 2,
        type: 'status',
        thread_id: 'thread-1',
        node: 'router_agent',
        data: { status: 'completed', next_node: 'chapter_outline_node' },
        timestamp: '2026-07-15T00:00:01Z',
      },
    })
    expect(completed.activeNode).toBe('chapter_outline_node')
    expect(completed.reasoning).toContain('第1章')
  })

  it('does not keep a completed node displayed as the current stage', () => {
    const completed = workflowReducer({
      ...initialWorkflowState,
      status: 'running',
      activeNode: 'outline_node',
    }, {
      type: 'event',
      event: {
        id: 5,
        type: 'status',
        thread_id: 'thread-1',
        node: 'outline_node',
        data: { status: 'completed' },
        timestamp: '2026-07-15T00:00:03Z',
      },
    })

    expect(completed.activeNode).toBeUndefined()
  })

  it('maps a chapter outline interrupt to the review stage', () => {
    const paused = workflowReducer(initialWorkflowState, {
      type: 'event',
      event: {
        id: 3,
        type: 'interrupt',
        thread_id: 'thread-1',
        data: {
          interrupts: [{
            action: 'review_or_provide_chapter_outline',
            chapter_number: 1,
            message: '第1章细纲已生成，请审阅或修改',
          }],
        },
        timestamp: '2026-07-15T00:00:02Z',
      },
    })
    expect(paused.status).toBe('paused')
    expect(paused.activeNode).toBe('chapter_outline_node')
    expect(paused.reasoning).toBe('第1章细纲已生成，请审阅或修改')
  })

  it('prefers interrupt stage and message when hydrating a paused snapshot', () => {
    const snapshot: WorkflowSnapshot = {
      thread_id: 'thread-1',
      status: 'paused',
      has_interrupt: true,
      interrupts: [{
        action: 'review_or_provide_chapter_outline',
        chapter_number: 1,
        message: '第1章细纲已生成，请审阅或修改',
      }],
      next_nodes: ['chapter_outline_node'],
      execution: {
        status: 'completed',
        active_node: 'router_agent',
        message: '本轮工作流已结束',
      },
      state: { router_reasoning: '旧路由信息' },
    }
    const hydrated = workflowReducer(initialWorkflowState, { type: 'snapshot', snapshot })
    expect(hydrated.status).toBe('paused')
    expect(hydrated.activeNode).toBe('chapter_outline_node')
    expect(hydrated.reasoning).toBe('第1章细纲已生成，请审阅或修改')
  })
})
