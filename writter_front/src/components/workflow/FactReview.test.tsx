import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WorkflowReview } from './WorkflowReview'
import type { InterruptInfo } from '@/types/novel'

afterEach(cleanup)

function show(status: string, extra: Partial<InterruptInfo> = {}) {
  const onResume = vi.fn()
  render(<WorkflowReview autoMode interrupt={{ action: 'fact_review_required', proposal_id: 'fact-current',
    artifact_content: '本次待核对的完整稿件',
    fact_report: { artifact_kind: 'body', status, reasons: ['证据尚不完整'], findings: [{
      message: '祠堂归属不同', fact_version: 2, expected_evidence: { quote: '祖祠归辛家所有' },
      actual_evidence: { quote: '祖祠归陆家所有' },
    }] }, ...extra }} onResume={onResume} onRetry={vi.fn()} />)
  return onResume
}

describe('事实复核', () => {
  it('keeps hard conflicts visible in automatic mode and forbids acceptance', () => {
    const resume = show('blocked')
    expect(screen.getByRole('heading', { name: '正文事实核对' })).toBeInTheDocument()
    expect(screen.getByText('本次待核对的完整稿件')).toBeInTheDocument()
    expect(screen.getByText(/已确认依据：祖祠归辛家所有/)).toHaveTextContent('版本 2')
    expect(screen.getByText(/稿件原文：祖祠归陆家所有/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '人工核对后继续' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '人工核对后继续' }))
    expect(resume).not.toHaveBeenCalled()
  })

  it('requires separate confirmation and submits the current proposal', () => {
    const resume = show('unknown')
    fireEvent.click(screen.getByRole('button', { name: '人工核对后继续' }))
    expect(resume).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '已核对，继续' }))
    expect(resume).toHaveBeenCalledWith({ proposal_id: 'fact-current', decision: 'accept' })
  })

  it('submits concrete correction instructions', () => {
    const resume = show('blocked')
    expect(screen.getByRole('button', { name: '按依据修订' })).toBeDisabled()
    fireEvent.change(screen.getByRole('textbox', { name: '事实修订要求' }), { target: { value: '归属应为辛家' } })
    fireEvent.click(screen.getByRole('button', { name: '按依据修订' }))
    expect(resume).toHaveBeenCalledWith({ proposal_id: 'fact-current', decision: 'revise', instruction: '归属应为辛家' })
  })

  it('does not allow acceptance without report or proposal', () => {
    show('unknown', { fact_report: undefined, proposal_id: undefined })
    expect(screen.getByRole('button', { name: '人工核对后继续' })).toBeDisabled()
  })
})
