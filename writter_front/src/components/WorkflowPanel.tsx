import { Progress } from 'antd'
import type { WorkflowViewState } from '@/hooks/useWorkflowStream'
import { WorkflowError } from './workflow/WorkflowError'
import { WorkflowHeader } from './workflow/WorkflowHeader'
import { WorkflowOverview } from './workflow/WorkflowOverview'
import { WorkflowQualitySummary } from './workflow/WorkflowQualitySummary'
import { WorkflowReview } from './workflow/WorkflowReview'
import { WorkflowTimeline } from './workflow/WorkflowTimeline'
import { chapterNumberFromState } from './workflow/presentation'

interface WorkflowPanelProps {
  className?: string
  state: WorkflowViewState
  autoMode: boolean
  onResume: (value: unknown) => void
  onRetry: () => void
  onCancel: () => void
  onRefresh: () => void
}

export function WorkflowPanel(props: WorkflowPanelProps) {
  const { className = '', state, autoMode, onResume, onRetry, onCancel, onRefresh } = props
  const chapterNumber = chapterNumberFromState(state)
  const chapterPrefix = chapterNumber ? `第 ${chapterNumber} 章` : '本章'
  return (
    <aside className={`workflow-panel ${className}`.trim()} aria-label="创作执行状态">
      <WorkflowHeader status={state.status} />
      {typeof state.progress === 'number' && <Progress percent={Math.round(state.progress)} showInfo={false} strokeColor="#176b5b" />}
      <WorkflowOverview state={state} chapterPrefix={chapterPrefix} onRefresh={onRefresh} onCancel={onCancel} />
      {state.status === 'running' && state.reasoning && <div className="reasoning-block"><span>流程判断</span><p>{state.reasoning}</p></div>}
      <WorkflowTimeline state={state} />
      <WorkflowQualitySummary state={state} />
      <WorkflowReview interrupt={state.interrupt} autoMode={autoMode} onResume={onResume} onRetry={onRetry} />
      <WorkflowError state={state} chapterNumber={chapterNumber} onRetry={onRetry} />
    </aside>
  )
}
