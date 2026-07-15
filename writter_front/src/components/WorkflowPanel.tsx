import { CheckCircleOutlined, LoadingOutlined, PauseCircleOutlined } from '@ant-design/icons'
import { Button, Input, Progress, Tag } from 'antd'
import { useState } from 'react'
import type { WorkflowViewState } from '@/hooks/useWorkflowStream'

const nodeLabels: Record<string, string> = {
  type_confirmation: '确认题材',
  title_node: '推敲书名',
  summary_node: '撰写简介',
  outline_node: '搭建总纲',
  memory_retrieval_node: '检索前文',
  chapter_outline_node: '设计细纲',
  chapter_writer_node: '撰写正文',
  reflection_node: '质量审读',
  revision_node: '修订章节',
  persist_node: '归档稿件',
  progress_check_node: '核对进度',
  router_agent: '规划下一步',
}

interface WorkflowPanelProps {
  className?: string
  state: WorkflowViewState
  autoMode: boolean
  onResume: (value: unknown) => void
}

export function WorkflowPanel({ className = '', state, autoMode, onResume }: WorkflowPanelProps) {
  const [instruction, setInstruction] = useState('')
  const interrupt = state.interrupt
  return (
    <aside className={`workflow-panel ${className}`.trim()} aria-label="创作执行状态">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">AI 编辑台</span>
          <h2>执行记录</h2>
        </div>
        <Tag color={state.status === 'running' ? 'processing' : state.status === 'error' ? 'error' : 'default'}>
          {state.status === 'running' ? '执行中' : state.status === 'paused' ? '待确认' : '空闲'}
        </Tag>
      </div>

      {typeof state.progress === 'number' && (
        <Progress percent={Math.round(state.progress)} showInfo={false} strokeColor="#176b5b" />
      )}

      <div className="reasoning-block">
        <span>当前判断</span>
        <p>{state.reasoning || '等待工作流给出下一步判断。'}</p>
      </div>

      <ol className="event-list">
        {state.events.filter((event) => event.type === 'status').slice(-8).map((event) => (
          <li key={`${event.id}-${event.node}`}>
            {state.activeNode === event.node && state.status === 'running'
              ? <LoadingOutlined />
              : <CheckCircleOutlined />}
            <span>{nodeLabels[event.node ?? ''] ?? event.node ?? '工作流'}</span>
          </li>
        ))}
        {state.events.length === 0 && <li className="muted">尚未开始执行</li>}
      </ol>

      {typeof state.qualityScore === 'number' && (
        <section className="quality-block">
          <div><span>质量评分</span><strong>{Math.round(state.qualityScore * 100)}</strong></div>
          <Progress percent={Math.round(state.qualityScore * 100)} showInfo={false} strokeColor="#8d2f3d" />
          {state.issues.slice(0, 3).map((issue, index) => (
            <p key={`${issue.type}-${index}`}>{issue.description || issue.type || '待处理问题'}</p>
          ))}
        </section>
      )}

      {interrupt && !autoMode && (
        <section className="interrupt-block">
          <div className="interrupt-title"><PauseCircleOutlined /> 需要你的决定</div>
          <p>{interrupt.message || '请审阅当前结果后继续。'}</p>
          <div className="interrupt-actions">
            <Button type="primary" onClick={() => onResume('accept')}>接受并继续</Button>
            <Button onClick={() => onResume('regenerate')}>重新生成</Button>
          </div>
          <Input.TextArea
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            placeholder="输入具体修改要求"
            autoSize={{ minRows: 2, maxRows: 5 }}
          />
          <Button
            disabled={!instruction.trim()}
            onClick={() => {
              onResume(instruction.trim())
              setInstruction('')
            }}
          >
            按要求修订
          </Button>
        </section>
      )}

      {state.error && <div className="error-note">{state.error}</div>}
    </aside>
  )
}
