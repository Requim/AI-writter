import {
  CheckCircleOutlined, LoadingOutlined, PauseCircleOutlined, ReloadOutlined, WarningOutlined,
} from '@ant-design/icons'
import { Tag } from 'antd'
import type { WorkflowViewState } from '@/hooks/useWorkflowStream'

const statusMeta = {
  running: { label: '执行中', color: 'processing' as const, icon: <LoadingOutlined /> },
  paused: { label: '待确认', color: 'warning' as const, icon: <PauseCircleOutlined /> },
  recoverable: { label: '可继续', color: 'warning' as const, icon: <ReloadOutlined /> },
  stalled: { label: '状态异常', color: 'error' as const, icon: <WarningOutlined /> },
  cancelling: { label: '正在结束', color: 'processing' as const, icon: <LoadingOutlined /> },
  error: { label: '失败', color: 'error' as const, icon: <WarningOutlined /> },
  idle: { label: '空闲', color: 'default' as const, icon: <CheckCircleOutlined /> },
}

export function WorkflowHeader({ status }: Pick<WorkflowViewState, 'status'>) {
  const meta = statusMeta[status]
  return (
    <div className="panel-heading">
      <div><span className="eyebrow">AI 编辑台</span><h2>执行记录</h2></div>
      <Tag color={meta.color} icon={meta.icon}>{meta.label}</Tag>
    </div>
  )
}
