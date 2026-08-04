import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { initialWorkflowState } from '@/hooks/useWorkflowStream'
import type { WorkflowViewState } from '@/hooks/useWorkflowStream'
import { useAutoRunNotifications } from './useAutoRunNotifications'

describe('useAutoRunNotifications', () => {
  it('notifies each automatic-run transition once even after rerenders', () => {
    const notification = { open: vi.fn() }
    const background: WorkflowViewState = {
      ...initialWorkflowState, status: 'running', connection: 'detached', activeCommandId: 'command-1',
    }
    const { rerender } = renderHook(
      ({ state, completed }) => useAutoRunNotifications(true, state, completed, notification),
      { initialProps: { state: background, completed: false } },
    )
    expect(notification.open).toHaveBeenCalledTimes(1)
    expect(notification.open).toHaveBeenLastCalledWith(expect.objectContaining({
      key: 'auto-background-command-1', message: '自动创作正在后台运行',
    }))
    rerender({ state: { ...background }, completed: false })
    expect(notification.open).toHaveBeenCalledTimes(1)

    const waiting: WorkflowViewState = {
      ...background, status: 'paused', connection: 'idle',
      interrupt: { action: 'summary_review_required', proposal_id: 'summary-2' },
    }
    rerender({ state: waiting, completed: false })
    expect(notification.open).toHaveBeenLastCalledWith(expect.objectContaining({
      type: 'warning', message: '自动创作等待人工处理',
    }))
    rerender({ state: { ...waiting, status: 'completed', interrupt: undefined }, completed: true })
    expect(notification.open).toHaveBeenLastCalledWith(expect.objectContaining({
      type: 'success', message: '全书创作已完成',
    }))
    expect(notification.open).toHaveBeenCalledTimes(3)
  })

  it('does not label an automatically resumable interrupt as waiting for a person', () => {
    const notification = { open: vi.fn() }
    renderHook(() => useAutoRunNotifications(true, {
      ...initialWorkflowState, status: 'paused',
      interrupt: { action: 'confirm_or_provide_title', proposal_id: 'title-1' },
    }, false, notification))
    expect(notification.open).not.toHaveBeenCalled()
  })
})
