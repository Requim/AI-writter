import { ReloadOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import type { WorkflowViewState } from '@/hooks/useWorkflowStream'

interface Props { state: WorkflowViewState; chapterNumber?: number; onRetry: () => void }

export function WorkflowError({ state, chapterNumber, onRetry }: Props) {
  if (!state.error || state.status === 'stalled') return null
  const label = state.activeNode?.includes('reflection') && chapterNumber
    ? `重试第 ${chapterNumber} 章质量审读` : '重试当前步骤'
  return (
    <div className="error-note" role="alert">
      {state.error}
      {state.retryable && <small>本章草稿和创作进度已保留，可直接重试当前步骤。</small>}
      {state.retryable && <Button size="small" icon={<ReloadOutlined />} onClick={onRetry}>{label}</Button>}
    </div>
  )
}
