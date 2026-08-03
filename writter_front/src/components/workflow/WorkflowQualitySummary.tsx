import { Progress } from 'antd'
import type { WorkflowViewState } from '@/hooks/useWorkflowStream'
import { qualityScoreOutOfFive } from './presentation'

export function WorkflowQualitySummary({ state }: { state: WorkflowViewState }) {
  if (typeof state.qualityScore !== 'number') return null
  const score = qualityScoreOutOfFive(state.qualityScore)
  return (
    <section className="quality-block" aria-label="质量评分">
      <div><span>质量评分</span><strong>{score.toFixed(1)}<small> / 5</small></strong></div>
      <Progress percent={Math.round(score * 20)} showInfo={false} strokeColor="#8d2f3d" />
      {state.issues.slice(0, 3).map((issue, index) => <p key={`${issue.issue_id || issue.type}-${index}`}>{issue.description || issue.type || '待处理问题'}</p>)}
    </section>
  )
}
