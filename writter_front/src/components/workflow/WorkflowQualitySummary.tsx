import { Progress } from 'antd'
import type { WorkflowViewState } from '@/hooks/useWorkflowStream'
import { qualityScoreOutOfFive } from './presentation'
import { reviewValueLabels } from './terminology'

function PlanResult({ state }: { state: WorkflowViewState }) {
  const result = state.planResult
  if (!result) return null
  const driftLabels: Record<string, string> = { none: '未发现计划偏差', minor: '部分内容延后', major: '需要调整后续规划' }
  return <section className="workflow-plan-result" aria-label="计划兑现检查">
    <h3>计划兑现检查</h3>
    <p>{result.chapter > 0 ? '第 ' + result.chapter + ' 章：' : ''}{reviewValueLabels[result.status] || '尚未确认'}</p>
    <p>{driftLabels[result.drift] || '偏差程度尚未确认'}{result.version ? ' · 整书规划 V' + result.version : ''}</p>
  </section>
}

export function WorkflowQualitySummary({ state }: { state: WorkflowViewState }) {
  if (typeof state.qualityScore !== 'number') return <PlanResult state={state} />
  const score = qualityScoreOutOfFive(state.qualityScore)
  return (
    <><section className="quality-block" aria-label="质量评分">
      <div><span>质量评分</span><strong>{score.toFixed(1)}<small> / 5</small></strong></div>
      <p>{reviewValueLabels[state.qualityDecision || ''] || '审阅结果待确认'} · 共 {state.issues.length} 条问题</p>
      <Progress percent={Math.round(score * 20)} showInfo={false} strokeColor="#8d2f3d" />
      {state.issues.slice(0, 3).map((issue, index) => <p key={`${issue.issue_id || issue.type}-${index}`}>{issue.description || reviewValueLabels[issue.type || ''] || '待处理问题'}</p>)}
      {state.issues.length > 3 && <details><summary>其余 {state.issues.length - 3} 条问题</summary>
        {state.issues.slice(3).map((issue, index) => <p key={issue.issue_id || index}>{issue.description || reviewValueLabels[issue.type || ''] || '待处理问题'}</p>)}
      </details>}
    </section><PlanResult state={state} /></>
  )
}
