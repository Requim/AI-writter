import { CheckCircleOutlined, LoadingOutlined, PauseCircleOutlined } from '@ant-design/icons'
import type { WorkflowViewState } from '@/hooks/useWorkflowStream'
import { completedTimeline, nodeLabels, presentationNode } from './presentation'

function emptyLabel(status: WorkflowViewState['status']): string {
  if (status === 'recoverable') return '草稿已保留，等待继续'
  if (status === 'error') return '当前步骤未完成'
  if (status === 'completed') return '执行已完成，节点历史未保留'
  return '尚未开始执行'
}

export function WorkflowTimeline({ state }: { state: WorkflowViewState }) {
  const complete = completedTimeline(state)
  const presentedNode = presentationNode(state)
  const active = presentedNode !== 'router_agent' && ['running', 'paused', 'stalled', 'cancelling'].includes(state.status)
    ? presentedNode : undefined
  const nodes = active && complete.at(-1) !== active ? [...complete, active] : complete
  return (
    <ol className="event-list" aria-label="执行时间线">
      {nodes.map((node, index) => {
        const isActive = node === active && index === nodes.length - 1
        return <li key={`${node}-${index}`} data-active={isActive || undefined}>
          {isActive ? state.status === 'paused' ? <PauseCircleOutlined /> : <LoadingOutlined /> : <CheckCircleOutlined />}
          <span>{nodeLabels[node] ?? node}</span>
        </li>
      })}
      {nodes.length === 0 && <li className="muted">{emptyLabel(state.status)}</li>}
    </ol>
  )
}
