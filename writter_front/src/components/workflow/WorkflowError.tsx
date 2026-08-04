import { ReloadOutlined, SyncOutlined } from '@ant-design/icons'
import { Button, Tag } from 'antd'
import type { WorkflowViewState } from '@/hooks/useWorkflowStream'
import { nodeLabels } from './presentation'

interface Props {
  state: WorkflowViewState
  chapterNumber?: number
  onRetry: () => void
  onRefresh: () => void
}

function draftNote(state: WorkflowViewState): string | undefined {
  if (state.hasCheckpointDraft) return '服务端 checkpoint 已保存本章草稿，重试会从已保存现场继续。'
  if (state.draft) return '未完成预览已保留在当前页面，服务端没有可继续的草稿；重试将从本章重新生成。'
  return undefined
}

function retryText(state: WorkflowViewState): string {
  if (!state.retryable) return '服务端未标记为可直接重试'
  const wait = state.retryAfter ? `，建议 ${state.retryAfter} 秒后重试` : ''
  const count = typeof state.retryCount === 'number' ? `，已尝试 ${state.retryCount} 次` : ''
  return `可重试${count}${wait}`
}

export function WorkflowError({ state, chapterNumber, onRetry, onRefresh }: Props) {
  if (!state.error || state.status === 'stalled') return null
  const label = state.activeNode?.includes('reflection') && chapterNumber
    ? `重试第 ${chapterNumber} 章质量审读` : '重试当前步骤'
  const note = draftNote(state)
  return (
    <div className="error-note" role="alert">
      <strong>{state.error}</strong>
      <dl className="error-diagnostics">
        <div><dt>错误码</dt><dd>{state.errorCode || '未提供'}</dd></div>
        <div><dt>出错节点</dt><dd>{nodeLabels[state.errorNode || state.activeNode || ''] || state.errorNode || state.activeNode || '未提供'}</dd></div>
        <div><dt>重试情况</dt><dd><Tag color={state.retryable ? 'warning' : 'default'}>{retryText(state)}</Tag></dd></div>
      </dl>
      {note && <small>{note}</small>}
      <div className="error-actions">
        <Button size="small" icon={<SyncOutlined />} onClick={onRefresh}>同步现场</Button>
        {state.retryable && <Button size="small" icon={<ReloadOutlined />} onClick={onRetry}>{label}</Button>}
      </div>
    </div>
  )
}
