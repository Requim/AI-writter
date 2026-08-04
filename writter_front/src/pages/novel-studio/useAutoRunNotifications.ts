import { useEffect, useRef } from 'react'
import type { WorkflowViewState } from '@/hooks/useWorkflowStream'
import { requiresHumanReview } from '@/workflowReviewPolicy'
import { interruptKey } from '../novelStudioUtils'

interface NotificationPort {
  open: (config: {
    key: string
    type: 'info' | 'warning' | 'success'
    message: string
    description: string
  }) => void
}

interface AutoRunNotice {
  key: string
  type: 'info' | 'warning' | 'success'
  message: string
  description: string
}

function runIdentity(state: WorkflowViewState): string {
  return state.activeCommandId || state.startedAt || state.lastPersistedChapterId || 'current'
}

export function autoRunNotice(
  active: boolean,
  state: WorkflowViewState,
  completed: boolean,
): AutoRunNotice | undefined {
  if (!active) return undefined
  if (completed) return {
    key: `auto-completed-${runIdentity(state)}`, type: 'success',
    message: '全书创作已完成', description: '计划章节已经全部归档，可以查看完稿。',
  }
  if (state.status === 'paused' && state.interrupt && requiresHumanReview(state.interrupt.action)) return {
    key: `auto-review-${interruptKey(state.interrupt)}`, type: 'warning',
    message: '自动创作等待人工处理', description: state.interrupt.message || '当前结果需要你的决定后才能继续。',
  }
  if (state.connection === 'detached' && ['running', 'stalled'].includes(state.status)) return {
    key: `auto-background-${runIdentity(state)}`, type: 'info',
    message: '自动创作正在后台运行', description: '页面会定期同步最新阶段，期间可以继续查看已归档章节。',
  }
  return undefined
}

/** 按自动运行阶段发送一次应用内通知，不申请系统通知权限。 */
export function useAutoRunNotifications(
  active: boolean,
  state: WorkflowViewState,
  completed: boolean,
  notification: NotificationPort,
): void {
  const shownRef = useRef(new Set<string>())
  const notice = autoRunNotice(active, state, completed)
  useEffect(() => {
    if (!notice || shownRef.current.has(notice.key)) return
    shownRef.current.add(notice.key)
    notification.open(notice)
  }, [notice, notification])
}
