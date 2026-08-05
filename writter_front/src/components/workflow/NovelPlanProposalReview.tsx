import { Tag } from 'antd'
import { NovelPlanSummary } from '@/components/novel-plan/NovelPlanView'
import type { InterruptInfo, JsonValue, NovelPlan } from '@/types/novel'
import { ReviewValue } from './ReviewPrimitives'
import { asRecord, proposalPayload } from './valueHelpers'

function looksLikePlan(value: Record<string, JsonValue> | undefined): boolean {
  return Boolean(value && asRecord(value.scale) && Array.isArray(value.volumes)
    && Array.isArray(value.arcs) && Array.isArray(value.chapter_slots))
}

function planFrom(interrupt: InterruptInfo): NovelPlan | undefined {
  const payload = proposalPayload(interrupt)
  const nested = asRecord(payload?.novel_plan) || asRecord(payload?.plan)
  const candidate = nested || payload
  return looksLikePlan(candidate) ? candidate as unknown as NovelPlan : undefined
}

function proposalDiff(interrupt: InterruptInfo): JsonValue | undefined {
  const payload = proposalPayload(interrupt)
  return payload?.diff ?? payload?.changes ?? payload?.change_summary
}

function PlanArcSummary({ plan }: { plan: NovelPlan }) {
  return <div className="plan-proposal-arcs">{plan.arcs.map((arc) => <div key={arc.arc_id}>
    <Tag color={arc.is_core ? 'red' : 'default'}>{arc.is_core ? '核心' : arc.arc_type}</Tag>
    <span>{arc.goal}</span><small>第 {arc.start_chapter} - {arc.end_chapter} 章</small>
  </div>)}</div>
}

export function NovelPlanProposalReview({ interrupt }: { interrupt: InterruptInfo }) {
  const plan = planFrom(interrupt)
  if (!plan) return null
  const diff = proposalDiff(interrupt)
  return <div className="review-surface novel-plan-proposal-review">
    <div className="review-heading"><span>整书规划提案</span><strong>V{plan.version || 1} · {plan.scale.target_chapters} 章生产蓝图</strong></div>
    <NovelPlanSummary plan={plan} />
    <details open><summary>剧情弧与覆盖范围</summary><PlanArcSummary plan={plan} /></details>
    {diff !== undefined && <details open><summary>本次结构化变更</summary><ReviewValue value={diff} /></details>}
  </div>
}
