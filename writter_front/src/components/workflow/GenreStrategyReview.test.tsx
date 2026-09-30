import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { WorkflowReview } from './WorkflowReview'
import type { InterruptInfo } from '@/types/novel'

const interrupt: InterruptInfo = {
  action: 'review_or_modify_genre_strategy',
  proposal: {
    proposal_id: 'strategy-1', kind: 'genre_strategy', version: 1,
    payload: { reader_promise: '公平线索推理', plot_engine: '证据链推进',
      style_constraints: ['叙述克制'], chapter_requirements: ['推进线索'],
      review_dimensions: ['线索公平'], avoid_solutions: ['梦境解释'],
      tone_guidance: '冷静', originality_hooks: ['证词冲突'] },
  },
}

describe('题材策略审核', () => {
  it('展示策略并使用当前提案接受、重生成和修订', () => {
    const resume = vi.fn()
    render(<WorkflowReview interrupt={interrupt} autoMode={false} onResume={resume} onRetry={vi.fn()} />)
    expect(screen.getByText('公平线索推理')).toBeTruthy()
    expect(screen.getByText('梦境解释')).toBeTruthy()
    fireEvent.click(screen.getByText('确认题材策略'))
    expect(resume).toHaveBeenLastCalledWith({ proposal_id: 'strategy-1', decision: 'accept' })
    fireEvent.click(screen.getByText('重新生成'))
    expect(resume).toHaveBeenLastCalledWith({ proposal_id: 'strategy-1', decision: 'regenerate' })
    fireEvent.change(screen.getByPlaceholderText('输入具体修改要求'), { target: { value: '加强心理压力' } })
    fireEvent.click(screen.getByText('按要求修订'))
    expect(resume).toHaveBeenLastCalledWith({
      proposal_id: 'strategy-1', decision: 'revise', instruction: '加强心理压力',
    })
  })
})
