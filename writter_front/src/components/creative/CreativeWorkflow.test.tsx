import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { initialWorkflowState, workflowReducer } from '@/hooks/workflowState'
import { WorkflowReview } from '@/components/workflow/WorkflowReview'
import { CreativeRecords } from './CreativeRecords'
import type { CreativeRecord } from '@/types/creative'

afterEach(cleanup)

function experimentRecord(status: string): CreativeRecord {
  return {
    id: 'trial-1', kind: 'experiment', key: 'window:1', version: 2,
    source: 'system', status, input_versions: { chapter: 1 }, evidence: [],
    payload: { factor: '缩短重复独白', variant_a: '原稿', variant_b: '改稿' },
    created_at: '2026-09-09T00:00:00Z',
  }
}

describe('自主作家事件与工作台边界', () => {
  it('distinguishes model trials from human validation and replays revocation', () => {
    const event = { id: 1, type: 'creative' as const, thread_id: 'book', timestamp: '',
      data: { kind: 'experiment', status: 'model_supported_trial' } }
    const trial = workflowReducer(initialWorkflowState, { type: 'event', event })
    expect(trial.creativeStatus?.status).toBe('model_supported_trial')
    const revoked = workflowReducer(trial, { type: 'event', event: { ...event, id: 2, data: { ...event.data, status: 'revoked' } } })
    expect(revoked.creativeStatus?.status).toBe('revoked')
    expect(workflowReducer(revoked, { type: 'event', event })).toEqual(revoked)
  })

  it('preserves a creative pause even when the last body is complete', () => {
    const restored = workflowReducer(initialWorkflowState, { type: 'snapshot', snapshot: {
      thread_id: 'book', status: 'idle', has_interrupt: true, is_completed: true,
      interrupts: [{ action: 'creative_paused', message: '后处理待恢复' }], state: { is_completed: true },
    } })
    expect(restored.status).toBe('paused')
    expect(restored.interrupt?.message).toBe('后处理待恢复')
  })

  it('never presents a budget pause as an accept-and-bypass action', () => {
    const resume = vi.fn()
    render(<WorkflowReview interrupt={{ action: 'creative_paused', message: '预算耗尽' }}
      autoMode onResume={resume} onRetry={vi.fn()} />)
    expect(screen.queryByRole('button', { name: '接受当前版本' })).not.toBeInTheDocument()
    expect(screen.getByText('预算耗尽')).toBeInTheDocument()
    expect(resume).not.toHaveBeenCalled()
  })

  it('shows isolated variants but never labels a model trial as human support', () => {
    render(<CreativeRecords records={[experimentRecord('model_supported_trial')]} />)
    expect(screen.getByText('模型支持试用')).toBeInTheDocument()
    expect(screen.queryByText('真人复测支持')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /expand row|展开行/i }))
    expect(screen.getByText('原稿')).toBeInTheDocument()
    expect(screen.getByText('改稿')).toBeInTheDocument()
  })
})
