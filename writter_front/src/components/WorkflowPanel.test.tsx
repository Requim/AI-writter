import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { WorkflowPanel } from './WorkflowPanel'
import type { WorkflowViewState } from '@/hooks/useWorkflowStream'


describe('WorkflowPanel', () => {
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
