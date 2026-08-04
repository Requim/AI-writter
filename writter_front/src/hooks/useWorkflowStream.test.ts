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

describe('workflowReducer command isolation', () => {
  it('locks a new command and clears the previous interrupt immediately', () => {
    const started = workflowReducer({
      ...initialWorkflowState,
      status: 'paused',
      interrupt: { action: 'confirm_or_provide_title', message: '旧候选' },
    }, { type: 'start', commandId: 'command-new' })
    expect(started.status).toBe('running')
    expect(started.activeCommandId).toBe('command-new')
    expect(started.interrupt).toBeUndefined()
  })

  it('ignores events from an older command', () => {
    const state = { ...initialWorkflowState, status: 'running' as const, activeCommandId: 'command-new' }
    const stale = workflowReducer(state, { type: 'event', event: {
      id: 8, type: 'interrupt', thread_id: 'thread-1', command_id: 'command-old',
      data: { interrupts: [{ action: 'confirm_or_provide_title' }] }, timestamp: '2026-07-15T00:00:04Z',
    } })
    expect(stale).toBe(state)
  })

  it('ignores events without a command id while a command is active', () => {
    const state = { ...initialWorkflowState, status: 'running' as const, activeCommandId: 'command-new' }
    const stale = workflowReducer(state, { type: 'event', event: event(9, 'append', '旧连接片段') })
    expect(stale).toBe(state)
  })

  it('ignores stale snapshots unless reconciliation is forced', () => {
    const state = {
      ...initialWorkflowState, status: 'running' as const, activeCommandId: 'command-new',
      startedAt: '2026-07-15T10:10:00Z',
    }
    const snapshot: WorkflowSnapshot = {
      thread_id: 'thread-1', status: 'paused', has_interrupt: true,
      interrupts: [{ action: 'confirm_or_provide_title', message: '旧候选' }],
      execution: { command_id: 'command-old', started_at: '2026-07-15T10:00:00Z' }, state: {},
    }
    expect(workflowReducer(state, { type: 'snapshot', snapshot })).toBe(state)
    expect(workflowReducer(state, { type: 'snapshot', snapshot, force: true }).status).toBe('paused')
  })
})

describe('workflowReducer sync health', () => {
  it('enters recovery only after two consecutive failures and clears it on success', () => {
    const first = workflowReducer(initialWorkflowState, { type: 'sync_failed' })
    const second = workflowReducer(first, { type: 'sync_failed' })
    expect(first.connectionRecovering).toBe(false)
    expect(second.connectionRecovering).toBe(true)
    const recovered = workflowReducer(second, {
      type: 'sync_succeeded', at: '2026-08-04T08:00:00Z',
    })
    expect(recovered).toMatchObject({
      connectionRecovering: false, consecutiveSyncFailures: 0,
      lastSyncedAt: '2026-08-04T08:00:00Z',
    })
  })
})

describe('workflowReducer streamed events', () => {
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

describe('workflowReducer metadata updates', () => {
  it('captures only metadata fields carried by the current event', () => {
    const updated = workflowReducer(initialWorkflowState, { type: 'event', event: {
      id: 10,
      type: 'metadata_updated',
      thread_id: 'thread-1',
      data: { title: '潮汐证词', summary: null },
      timestamp: '2026-07-15T00:00:05Z',
    } })
    expect(updated.metadata).toEqual({ title: '潮汐证词' })
    expect(updated.metadataUpdatedAt).toBe('2026-07-15T00:00:05Z')
  })
})

describe('workflowReducer execution snapshots', () => {
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
})

describe('workflowReducer persistence stage timing', () => {
  it('restarts the stage timer for chapter summary and story-state events', () => {
    const summary = workflowReducer(initialWorkflowState, { type: 'event', event: {
      id: 20, type: 'status', thread_id: 'thread-1', node: 'chapter_summary',
      data: { status: 'started', started_at: '2026-08-04T08:00:00Z' },
      timestamp: '2026-08-04T08:00:00Z',
    } })
    expect(summary).toMatchObject({
      activeNode: 'chapter_summary', stageStartedAt: '2026-08-04T08:00:00Z',
    })
    const storyState = workflowReducer(summary, { type: 'event', event: {
      id: 21, type: 'status', thread_id: 'thread-1', node: 'story_state',
      data: { status: 'started', started_at: '2026-08-04T08:00:03Z' },
      timestamp: '2026-08-04T08:00:03Z',
    } })
    expect(storyState).toMatchObject({
      activeNode: 'story_state', stageStartedAt: '2026-08-04T08:00:03Z',
    })
  })
})

describe('workflowReducer execution start', () => {
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
    const started = workflowReducer(dirtyState, { type: 'start', commandId: 'command-1' })
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
    }, { type: 'start', preserveDraft: true, commandId: 'command-2' })

    expect(started.draft).toBe('第二章草稿')
    expect(started.status).toBe('running')
  })
})

describe('workflowReducer checkpoint recovery', () => {
  it('hydrates the presence of a private checkpoint draft without exposing its text', () => {
    const snapshot: WorkflowSnapshot = {
      thread_id: 'thread-1',
      status: 'idle',
      has_interrupt: false,
      interrupts: [],
      state: { has_current_chapter_content: true },
    }

    const hydrated = workflowReducer(initialWorkflowState, { type: 'snapshot', snapshot })
    expect(hydrated.status).toBe('recoverable')
    expect(hydrated.hasCheckpointDraft).toBe(true)
    expect(hydrated.draft).toBe('')
  })

  it('marks an idle routed checkpoint as resumable work', () => {
    const snapshot: WorkflowSnapshot = {
      thread_id: 'thread-1',
      status: 'idle',
      has_interrupt: false,
      interrupts: [],
      next_nodes: ['router_agent'],
      state: { current_chapter_index: 2 },
    }

    const hydrated = workflowReducer({
      ...initialWorkflowState,
      currentChapter: 5,
      progress: 50,
    }, { type: 'snapshot', snapshot })
    expect(hydrated.status).toBe('recoverable')
    expect(hydrated.hasPendingCheckpoint).toBe(true)
    expect(hydrated.checkpointChapterIndex).toBe(2)
    expect(hydrated.currentChapter).toBe(2)
    expect(hydrated.progress).toBeUndefined()
  })
})

describe('workflowReducer chapter persistence', () => {
  it('clears the live draft only after the chapter is persisted', () => {
    const persisted = workflowReducer({
      ...initialWorkflowState,
      draft: '已生成正文',
      status: 'running',
    }, {
      type: 'event',
      event: {
        id: 8,
        type: 'chapter_persisted',
        thread_id: 'thread-1',
        node: 'persist_node',
        data: {
          chapter_id: 'chapter-2',
          current_chapter: 2,
          percentage: 20,
        },
        timestamp: '2026-07-15T00:00:04Z',
      },
    })

    expect(persisted.draft).toBe('')
    expect(persisted.lastPersistedChapterId).toBe('chapter-2')
    expect(persisted.currentChapter).toBe(2)
    expect(persisted.progress).toBe(20)
  })
})

describe('workflowReducer routing', () => {
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
})

describe('workflowReducer review stage', () => {
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
    expect(paused.activeNode).toBe('chapter_outline_review_node')
    expect(paused.reasoning).toBe('第1章细纲已生成，请审阅或修改')
  })
})

describe('workflowReducer paused snapshot', () => {
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
    expect(hydrated.activeNode).toBe('chapter_outline_review_node')
    expect(hydrated.reasoning).toBe('第1章细纲已生成，请审阅或修改')
  })
})

describe('workflowReducer completion', () => {
  it('hydrates an explicitly completed checkpoint as a finished novel', () => {
    const snapshot: WorkflowSnapshot = {
      thread_id: 'thread-1', status: 'idle', is_completed: true,
      has_interrupt: false, interrupts: [], next_nodes: ['router_agent'],
      execution: { active_node: 'router_agent', command_id: 'old-command' },
      state: { current_chapter_index: 3, is_completed: true },
    }
    const hydrated = workflowReducer(initialWorkflowState, { type: 'snapshot', snapshot })
    expect(hydrated.status).toBe('completed')
    expect(hydrated.activeNode).toBeUndefined()
    expect(hydrated.activeCommandId).toBeUndefined()
    expect(hydrated.hasPendingCheckpoint).toBe(false)
  })

  it('does not confuse a completed command with a completed novel', () => {
    const commandDone = workflowReducer({ ...initialWorkflowState, status: 'running' }, {
      type: 'event', event: {
        id: 9, type: 'completed', thread_id: 'thread-1', data: { status: 'idle' },
        timestamp: '2026-08-03T00:00:00Z',
      },
    })
    expect(commandDone.status).toBe('idle')
  })
})

describe('workflowReducer error reconciliation', () => {
  it('keeps live error diagnostics while hydrating authoritative checkpoint flags', () => {
    const snapshot: WorkflowSnapshot = {
      thread_id: 'thread-1', status: 'idle', has_interrupt: false, interrupts: [],
      next_nodes: ['reflection_node'], state: { has_current_chapter_content: true },
    }
    const hydrated = workflowReducer({
      ...initialWorkflowState, status: 'error', error: '审读结构无效',
      errorCode: 'quality_result_invalid', errorNode: 'reflection_node', retryable: true,
    }, { type: 'snapshot', snapshot, force: true })
    expect(hydrated.status).toBe('error')
    expect(hydrated.errorCode).toBe('quality_result_invalid')
    expect(hydrated.hasCheckpointDraft).toBe(true)
    expect(hydrated.hasPendingCheckpoint).toBe(true)
  })
})
