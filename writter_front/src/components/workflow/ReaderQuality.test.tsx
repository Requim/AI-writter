import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { QualityReview, TitleReview } from './ReviewContents'
import { WorkflowReview } from './WorkflowReview'
import { WorkflowPanel } from '../WorkflowPanel'
import { initialWorkflowState, workflowReducer } from '@/hooks/workflowState'

afterEach(cleanup)

describe('书名评分', () => {
  it('shows the declared hundred-point scale and keeps a long title selectable', () => {
    const title = '重来七次以后我终于知道她为什么没有等我一起回家'
    const onConfirm = vi.fn()
    render(<TitleReview interrupt={{ action: 'confirm_or_provide_title', ai_suggestions: [{
      title, hint: '重来会失去共同记忆', total_score: 86, score_max: 100,
    }] }} onConfirm={onConfirm} onRegenerate={vi.fn()} />)
    expect(screen.getByText('86 / 100')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /重来七次以后/ }))
    fireEvent.click(screen.getByRole('button', { name: /确认使用/ }))
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ title }))
  })

  it('does not invent a denominator for a legacy unversioned score', () => {
    render(<TitleReview interrupt={{ action: 'confirm_or_provide_title',
      ai_suggestions: [{ title: '旧车站', total_score: 32 }] }}
      onConfirm={vi.fn()} onRegenerate={vi.fn()} />)
    expect(screen.queryByText('32 / 40')).not.toBeInTheDocument()
    expect(screen.getByText('评分 32')).toBeInTheDocument()
  })
})

const gate = {
  reader_review_required: true,
  reader_comprehension: {
    status: 'failed', source: 'simulated_reader',
    report: {
      checks: [{ key: 'goal', status: 'unclear', answer: '不知道她为什么反复整理纸杯',
        evidence: [{ source: 'current', quote: '她又把纸杯推过去' }] }],
      issues: [{ kind: 'padding', quote: '她又把纸杯推过去',
        reason: '动作没有推动事情', suggestion: '让对白说清当前需要办的事', blocking: true }],
    },
  },
}

describe('读者理解报告', () => {
  it('shows a failed report once when both proposal and event summary contain it', () => {
    render(<WorkflowPanel state={{
      ...initialWorkflowState, status: 'paused', readerComprehension: gate.reader_comprehension,
      interrupt: { action: 'quality_gate_human_review', proposal: {
        proposal_id: 'reader', kind: 'reflection', version: 1, payload: { gate }, prompt_version: 'v1',
      } },
    }} autoMode={false} onResume={vi.fn()} onRetry={vi.fn()} onCancel={vi.fn()} onRefresh={vi.fn()} />)
    expect(screen.getAllByText('读者理解')).toHaveLength(1)
  })
  it('retains optional reader feedback from events and checkpoint snapshots', () => {
    const current = workflowReducer(initialWorkflowState, { type: 'event', event: {
      id: 1, thread_id: 'book', type: 'quality', timestamp: '2026-10-13T00:00:00Z', node: 'reflection_node',
      data: { score: .9, decision: 'refactor', reader_comprehension: gate.reader_comprehension },
    } })
    expect(current.readerComprehension).toEqual(gate.reader_comprehension)
    const restored = workflowReducer(initialWorkflowState, { type: 'snapshot', snapshot: {
      thread_id: 'book', status: 'idle', has_interrupt: false, interrupts: [],
      next_nodes: [], state: { reader_comprehension: gate.reader_comprehension },
    } })
    expect(restored.readerComprehension).toEqual(gate.reader_comprehension)
    const next = workflowReducer(current, { type: 'event', event: {
      id: 2, thread_id: 'book', type: 'quality', timestamp: '2026-10-13T00:01:00Z', node: 'reflection_node',
      data: { score: .9, decision: 'pass' },
    } })
    expect(next.readerComprehension).toBeUndefined()
  })
  it('shows the actual confusion and excerpt without presenting simulated feedback as real readers', () => {
    render(<QualityReview interrupt={{ action: 'quality_gate_human_review',
      proposal: { proposal_id: 'reader', kind: 'reflection', version: 1,
        payload: { gate }, prompt_version: 'v1' } }} />)
    expect(screen.getByText('读者理解')).toBeInTheDocument()
    expect(screen.getByText(/模拟试读/)).toBeInTheDocument()
    expect(screen.getByText('当前目标')).toBeInTheDocument()
    expect(screen.getByText('不知道她为什么反复整理纸杯')).toBeInTheDocument()
    expect(screen.getAllByText('她又把纸杯推过去').length).toBeGreaterThan(0)
    expect(screen.getByRole('alert')).toHaveTextContent('章节未归档')
  })

  it('does not offer acceptance for a failed reader gate', () => {
    render(<WorkflowReview interrupt={{ action: 'quality_gate_human_review',
      proposal: { proposal_id: 'reader', kind: 'reflection', version: 1,
        payload: { gate }, prompt_version: 'v1' } }}
      autoMode={false} onResume={vi.fn()} onRetry={vi.fn()} />)
    expect(screen.queryByRole('button', { name: '接受当前版本' })).not.toBeInTheDocument()
  })
})
