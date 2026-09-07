import {
  CheckCircleOutlined, LoadingOutlined, PauseCircleOutlined, ReloadOutlined, WarningOutlined,
} from '@ant-design/icons'
import { Tag } from 'antd'
import type { WorkflowViewState } from '@/hooks/useWorkflowStream'
import { workflowStatusLabels } from './terminology'

const statusMeta = {
  running: { label: '执行中', color: 'processing' as const, icon: <LoadingOutlined /> },
  paused: { label: '待确认', color: 'warning' as const, icon: <PauseCircleOutlined /> },
  recoverable: { label: '可继续', color: 'warning' as const, icon: <ReloadOutlined /> },
  stalled: { label: '状态异常', color: 'error' as const, icon: <WarningOutlined /> },
  cancelling: { label: '正在结束', color: 'processing' as const, icon: <LoadingOutlined /> },
  error: { label: '失败', color: 'error' as const, icon: <WarningOutlined /> },
  completed: { label: '已完稿', color: 'success' as const, icon: <CheckCircleOutlined /> },
  idle: { label: '空闲', color: 'default' as const, icon: <CheckCircleOutlined /> },
}

export function WorkflowHeader({ status, syncState }: Pick<WorkflowViewState, 'status' | 'syncState'>) {
  const meta = statusMeta[status]
  const label = syncState === 'unknown' ? '进度尚未确认' : syncState === 'syncing' ? '正在读取进度' : workflowStatusLabels[status]
  return (
    <div className="panel-heading">
      <div><span className="eyebrow">当前作品</span><h2>创作进度</h2></div>
      <Tag color={syncState === 'unknown' ? 'warning' : meta.color} icon={meta.icon}>{label}</Tag>
    </div>
  )
}
