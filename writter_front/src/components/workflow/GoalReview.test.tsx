import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { InterruptInfo } from '@/types/novel'
import { WorkflowReview } from './WorkflowReview'

afterEach(cleanup)

function goalInterrupt(unavailable = false): InterruptInfo {
  return {
    action: unavailable ? 'quality_review_unavailable' : 'quality_gate_human_review',
    chapter_number: 1,
    proposal: {
      proposal_id: 'goal-1', kind: 'reflection', version: 1,
      payload: unavailable ? { status: 'unavailable', goal_review_required: true } : {
        gate: {
          goal_review_required: true,
          goal_acceptance: { status: 'blocked', checks: [
            { id: 'ch1:must:2', status: 'unknown', expected: '归还失物', reason: '缺少原文证据' },
          ] },
        },
      },
    },
  }
}

describe('fixed goal acceptance', () => {
  it('shows unmet goals and prevents accepting them through the quality action', () => {
    const onResume = vi.fn()
    render(<WorkflowReview interrupt={goalInterrupt()} autoMode onResume={onResume} onRetry={vi.fn()} />)
    expect(screen.getByText('原始目标验收')).toBeInTheDocument()
    expect(screen.getByText('缺少原文证据')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '接受当前版本' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '重新审读目标' }))
    expect(onResume).toHaveBeenCalledWith({ proposal_id: 'goal-1', decision: 'revise', instruction: 'retry' })
  })

  it('does not allow unavailable review to waive goal acceptance', () => {
    render(<WorkflowReview interrupt={goalInterrupt(true)} autoMode onResume={vi.fn()} onRetry={vi.fn()} />)
    expect(screen.getByRole('button', { name: '接受并标记未审读' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '重新审读' })).toBeEnabled()
  })
})
