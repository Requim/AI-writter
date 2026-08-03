import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { WorkflowPanel } from './WorkflowPanel'
import type { WorkflowViewState } from '@/hooks/useWorkflowStream'


describe('WorkflowPanel', () => {
  it('shows the generated creative brief for manual confirmation', () => {
    const onResume = vi.fn()
    const brief = {
      core_premise: '一名记者发现所有失踪者都曾收到同一封信。',
      protagonist_drive: '查清妹妹失踪的真相。',
      core_conflict: '每接近真相一步，妹妹留下的证据就更像伪造。',
      theme_question: '真相是否值得用亲密关系来交换？',
      reader_promise: '持续解谜，并在终局获得情感回响。',
    }
    render(
      <WorkflowPanel
        state={{
          status: 'paused',
          connection: 'idle',
          draft: '',
          activeNode: 'creative_brief_node',
          issues: [],
          events: [],
          interrupt: {
            action: 'review_or_modify_creative_brief',
            message: '创作简报已生成，请确认或修改',
            ai_generated_creative_brief: brief,
          },
        }}
        autoMode={false}
        onResume={onResume}
        onRetry={vi.fn()}
        onCancel={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )

    expect(screen.getAllByText('凝练创作简报').length).toBeGreaterThan(0)
    expect(screen.getByText('一名记者发现所有失踪者都曾收到同一封信。')).toBeInTheDocument()
    expect(screen.getByText('查清妹妹失踪的真相。')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '确认创作简报' }))
    expect(onResume).toHaveBeenCalledWith(brief)
  })

  it('shows a chapter outline review instead of the internal router stage', () => {
    const state: WorkflowViewState = {
      status: 'paused',
      connection: 'idle',
      draft: '',
      activeNode: 'chapter_outline_node',
      reasoning: '第1章细纲已生成，请审阅或修改',
      issues: [],
      events: [
        {
          id: 1,
          type: 'status',
          thread_id: 'thread-1',
          node: 'router_agent',
          data: { status: 'completed', next_node: 'chapter_outline_node' },
          timestamp: '2026-07-15T14:00:00Z',
        },
      ],
      interrupt: {
        action: 'review_or_provide_chapter_outline',
        chapter_number: 1,
        message: '第1章细纲已生成，请审阅或修改',
        ai_generated_outline: {
          title: '遗嘱上的血字',
          chapter_goal: '迫使主角接下第一份危险委托',
          key_events: ['收到遗嘱', '发现异常签名', '决定追查'],
        },
      },
    }

    render(
      <WorkflowPanel
        state={state}
        autoMode={false}
        onResume={vi.fn()}
        onRetry={vi.fn()}
        onCancel={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )

    expect(screen.getAllByText('第 1 章细纲待审阅').length).toBeGreaterThan(0)
    expect(screen.getByText('遗嘱上的血字')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '使用细纲，生成正文' })).toBeInTheDocument()
    expect(screen.queryByText('规划下一步')).not.toBeInTheDocument()
    expect(screen.queryByText('router_agent')).not.toBeInTheDocument()
  })

  it('shows scored title candidates and submits the selected object', () => {
    const onResume = vi.fn()
    render(
      <WorkflowPanel
        state={{
          status: 'paused', connection: 'idle', draft: '', activeNode: 'title_node',
          issues: [], events: [],
          interrupt: {
            action: 'confirm_or_provide_title',
            ai_suggestions: [{ title: '死者请于雨夜回信', hint: '一封来信重启旧案', total_score: 35 }],
          },
        }}
        autoMode={false}
        onResume={onResume}
        onRetry={vi.fn()}
        onCancel={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /死者请于雨夜回信/ }))
    expect(onResume).toHaveBeenCalledWith(expect.objectContaining({ title: '死者请于雨夜回信' }))
  })

  it('keeps the human quality decision visible in automatic mode', () => {
    render(
      <WorkflowPanel
        state={{
          status: 'paused', connection: 'idle', draft: '', activeNode: 'reflection_node',
          issues: [], events: [],
          interrupt: {
            action: 'quality_gate_exhausted',
            chapter_number: 3,
            message: '自动修订已达上限，请人工决定',
          },
        }}
        autoMode
        onResume={vi.fn()}
        onRetry={vi.fn()}
        onCancel={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )

    expect(screen.getAllByText('自动修订已达上限，请人工决定').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: '人工接受本章' })).toBeInTheDocument()
  })

  it('shows an explicit retry action for recoverable workflow errors', () => {
    render(
      <WorkflowPanel
        state={{
          status: 'error',
          connection: 'idle',
          draft: '第二章草稿',
          activeNode: 'reflection_node',
          checkpointChapterIndex: 2,
          issues: [],
          events: [],
          error: '模型返回的审读结果格式不符合要求，请重试当前步骤',
          retryable: true,
        }}
        autoMode
        onResume={vi.fn()}
        onRetry={vi.fn()}
        onCancel={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )

    expect(screen.getByText('第 3 章质量审读失败')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重试第 3 章质量审读/ })).toBeInTheDocument()
  })

  it('shows preserved draft work as recoverable instead of idle', () => {
    render(
      <WorkflowPanel
        state={{
          status: 'recoverable',
          connection: 'idle',
          draft: '',
          activeNode: 'reflection_node',
          checkpointChapterIndex: 2,
          hasCheckpointDraft: true,
          hasPendingCheckpoint: true,
          issues: [],
          events: [],
        }}
        autoMode
        onResume={vi.fn()}
        onRetry={vi.fn()}
        onCancel={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )

    expect(screen.getByText('可继续')).toBeInTheDocument()
    expect(screen.getByText('第 3 章质量审读可继续')).toBeInTheDocument()
    expect(screen.getByText('草稿已保留，等待继续')).toBeInTheDocument()
    expect(screen.queryByText('尚未开始执行')).not.toBeInTheDocument()
    expect(screen.queryByText('空闲')).not.toBeInTheDocument()
  })
})
