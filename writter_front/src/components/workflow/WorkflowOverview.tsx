import { ClockCircleOutlined, DisconnectOutlined, ReloadOutlined, StopOutlined } from '@ant-design/icons'
import { Button, Tooltip } from 'antd'
import { useEffect, useState } from 'react'
import type { WorkflowViewState } from '@/hooks/useWorkflowStream'
import { formatElapsed, formatTime, stagePresentation } from './presentation'

interface Props {
  state: WorkflowViewState
  chapterPrefix: string
  onRefresh: () => void
  onCancel: () => void
}

function useClock(active: boolean): number {
  const [now, setNow] = useState(0)
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [active])
  return now
}

export function WorkflowOverview({ state, chapterPrefix, onRefresh, onCancel }: Props) {
  const busy = ['running', 'stalled', 'cancelling'].includes(state.status)
  const now = useClock(busy)
  const stage = stagePresentation(state, chapterPrefix)
  const description = state.status === 'paused' && state.interrupt
    ? state.interrupt.message || '当前结果已生成，请审阅后继续。' : stage.description
  const elapsed = formatElapsed(state.stageStartedAt || state.startedAt, now)
  return (
    <section className="execution-overview" data-state={state.status} aria-live="polite">
      <div className="execution-stage"><span className="stage-marker" aria-hidden="true" /><div><small>当前阶段</small><strong>{stage.label}</strong></div></div>
      <p>{description}</p>
      {(state.startedAt || elapsed) && <dl className="execution-times">
        <div><dt><ClockCircleOutlined /> 开始</dt><dd>{formatTime(state.startedAt)}</dd></div>
        <div><dt>本阶段已用时</dt><dd>{elapsed || '正在记录'}</dd></div>
      </dl>}
      {state.connection === 'detached' && state.status === 'running' && <div className="connection-note"><DisconnectOutlined /> 页面已断开流式连接，正在同步后台状态</div>}
      {state.status === 'stalled' && <div className="stalled-note"><strong>任务长时间没有新进展</strong><span>刷新状态后仍无变化时，可以结束任务并从已保留进度继续。</span></div>}
      {(busy || state.connection === 'detached') && <div className="execution-actions">
        <Tooltip title="从服务器读取当前节点"><Button size="small" icon={<ReloadOutlined />} onClick={onRefresh}>刷新状态</Button></Tooltip>
        <Button size="small" danger icon={<StopOutlined />} loading={state.status === 'cancelling'} onClick={onCancel}>结束任务</Button>
      </div>}
    </section>
  )
}
