import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WorkflowPanel } from '../WorkflowPanel'
import { initialWorkflowState, workflowReducer, type WorkflowViewState } from '@/hooks/workflowState'
import { planningFieldLabel } from './terminology'
import { WorkflowReview } from './WorkflowReview'

afterEach(cleanup)

function show(state: Partial<WorkflowViewState>) {
  return render(<WorkflowPanel state={{ ...initialWorkflowState, syncState: 'confirmed', ...state }}
    autoMode={false} onResume={vi.fn()} onRetry={vi.fn()} onCancel={vi.fn()} onRefresh={vi.fn()} />)
}

describe('创作进度的用户视图', () => {
  it('requires explicit confirmation before accepting a problem chapter', () => {
    const onResume = vi.fn()
    render(<WorkflowReview interrupt={{ action: 'quality_gate_human_review' }} autoMode={false} onResume={onResume} onRetry={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: '接受当前版本' }))
    expect(onResume).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '确认接受' }))
    expect(onResume).toHaveBeenCalledWith('accept')
  })

  it('restores persisted plan results and clears unsupported legacy results', () => {
    const snapshot = { thread_id: 'novel', status: 'idle' as const, has_interrupt: false, interrupts: [],
      state: { last_plan_execution: { chapter_number: 3, status: 'breached', drift_severity: 'major', plan_version: 2 } } }
    const restored = workflowReducer(initialWorkflowState, { type: 'snapshot', snapshot })
    expect(restored.planResult).toEqual({ chapter: 3, status: 'breached', drift: 'major', version: 2 })
    const legacy = workflowReducer(restored, { type: 'snapshot', snapshot: { ...snapshot, state: {} } })
    expect(legacy.planResult).toBeUndefined()
  })

})

describe('创作进度的展示边界', () => {
  it('folds internal nodes and reasoning away from the current task', () => {
    show({ status: 'running', activeNode: 'chapter_writer_node', reasoning: 'router_debug_only' })
    expect(screen.getByRole('heading', { name: '创作进度' })).toBeInTheDocument()
    const details = screen.getByText('技术详情').closest('details')
    expect(details).not.toHaveAttribute('open')
    expect(details).toHaveTextContent('chapter_writer_node')
    expect(details).toHaveTextContent('router_debug_only')
  })

  it('uses a Chinese fallback for unrecognized timeline nodes', () => {
    show({ status: 'running', activeNode: 'future_node_internal' })
    expect(screen.getByText('其他创作步骤')).toBeInTheDocument()
    expect(screen.getByText('future_node_internal').closest('details')).not.toHaveAttribute('open')
  })

  it('exposes sync failure without implying an idle server', () => {
    const failed = workflowReducer(initialWorkflowState, { type: 'sync_failed' })
    expect(failed.syncState).toBe('unknown')
    show(failed)
    expect(screen.getByText('当前进度尚未确认')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重新核对进度/ })).toBeInTheDocument()
  })

  it('keeps plan completion separate from quality scores', () => {
    const state = workflowReducer(initialWorkflowState, { type: 'event', event: {
      id: 1, type: 'plan_reconciled', thread_id: 'novel', node: 'plan_reconciliation_node',
      timestamp: '2026-09-07T08:00:00Z',
      data: { chapter_number: 3, status: 'breached', drift_severity: 'major', plan_version: 2 },
    } })
    show(state)
    expect(screen.getByText('第 3 章：需要调整')).toBeInTheDocument()
    expect(screen.getByText(/需要调整后续规划/)).toBeInTheDocument()
    expect(screen.queryByLabelText('质量评分')).not.toBeInTheDocument()
  })

  it('does not erase an error when a stream termination arrives', () => {
    const state = workflowReducer({ ...initialWorkflowState, status: 'error', error: '审阅失败' }, {
      type: 'event', event: { id: 2, type: 'completed', thread_id: 'novel', timestamp: '', data: { is_completed: false } },
    })
    expect(state.status).toBe('error')
    expect(state.error).toBe('审阅失败')
  })

  it('does not present malformed plan outcomes as success', () => {
    const state = workflowReducer(initialWorkflowState, { type: 'event', event: {
      id: 3, type: 'plan_reconciled', thread_id: 'novel', timestamp: '', data: {},
    } })
    expect(state.planResult?.status).toBe('unknown')
    expect(planningFieldLabel('final_state')).toBe('最终局面')
    expect(planningFieldLabel('unrecognized_field')).toBe('补充设定')
  })
})
