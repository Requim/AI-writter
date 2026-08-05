import { AimOutlined, BookOutlined, BranchesOutlined, OrderedListOutlined, PartitionOutlined } from '@ant-design/icons'
import { Collapse, Empty, Tabs, Tag } from 'antd'
import type { ReactNode } from 'react'
import type {
  ChapterSlot, JsonValue, NovelPlan, StoryArc, TacticalPlanResponse,
  TacticalPlanVersionSummary, VolumePlan,
} from '@/types/novel'
import { TacticalPlanView } from './TacticalPlanView'

const sourceLabels: Record<string, string> = {
  initial: '初始规划', legacy_upgrade: '旧作补全', volume_detail: '卷内细化',
  replan: '主动重规划', user_replan: '主动重规划', drift: '漂移调整',
  drift_replan: '重大漂移调整', manual_drift: '人工漂移调整',
}

const statusLabels: Record<string, string> = {
  planned: '待写', locked: '已锁定', completed: '已完成',
}

function displayValue(value: JsonValue): string {
  if (value == null) return '未约定'
  if (Array.isArray(value)) return value.map(displayValue).join('；')
  if (typeof value === 'object') {
    return Object.entries(value).map(([key, item]) => `${key.replaceAll('_', ' ')}：${displayValue(item)}`).join('；')
  }
  return String(value)
}

function PlanMetrics({ plan }: { plan: NovelPlan }) {
  const metrics = [
    ['计划章节', `${plan.scale.target_chapters} 章`],
    ['目标字数', `${plan.scale.target_total_words.toLocaleString()} 字`],
    ['平均篇幅', `${plan.scale.average_chapter_words.toLocaleString()} 字 / 章`],
    ['分卷数量', `${plan.scale.target_volumes} 卷`],
  ]
  return <div className="plan-metrics">
    {metrics.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}
  </div>
}

function VolumeBoundaryList({ volumes }: { volumes: VolumePlan[] }) {
  return <div className="plan-boundaries">
    {volumes.map((volume) => <div key={volume.volume_id}>
      <span>{volume.title || volume.volume_id}</span>
      <strong>第 {volume.start_chapter} - {volume.end_chapter} 章</strong>
      <small>{volume.target_words.toLocaleString()} 字</small>
    </div>)}
  </div>
}

export function NovelPlanSummary({ plan }: { plan: NovelPlan }) {
  return <div className="plan-summary">
    <div className="plan-document-meta">
      <span>V{plan.version}</span><span>{sourceLabels[plan.source] || plan.source}</span>
      <span>浮动 ±{Math.round(plan.scale.tolerance_ratio * 100)}%</span>
      <span>锁定未来 {plan.scale.lock_window} 章</span>
    </div>
    <PlanMetrics plan={plan} />
    <VolumeBoundaryList volumes={plan.volumes} />
  </div>
}

function PlanOverview({ plan }: { plan: NovelPlan }) {
  return <div className="plan-tab-panel">
    <NovelPlanSummary plan={plan} />
    <section className="plan-ending-contract">
      <span className="eyebrow">Ending Contract</span><h3>结局契约</h3>
      <dl>{Object.entries(plan.ending_contract).map(([key, value]) => <div key={key}>
        <dt>{key.replaceAll('_', ' ')}</dt><dd>{displayValue(value)}</dd>
      </div>)}</dl>
    </section>
  </div>
}

function VolumeNarrative({ volume }: { volume: VolumePlan }) {
  const rows = [
    ['开场状态', volume.opening_state], ['中点转折', volume.midpoint_turn],
    ['卷高潮', volume.climax], ['退场状态', volume.ending_state],
  ]
  return <dl className="plan-detail-rows">{rows.map(([label, value]) => <div key={label}>
    <dt>{label}</dt><dd>{value || '待细化'}</dd>
  </div>)}</dl>
}

function VolumesView({ volumes }: { volumes: VolumePlan[] }) {
  return <div className="plan-volume-sections">{volumes.map((volume) => <section key={volume.volume_id}>
    <header><div><span>{volume.volume_id}</span><h3>{volume.title || '未命名分卷'}</h3></div>
      <strong>第 {volume.start_chapter} - {volume.end_chapter} 章 · {volume.target_words.toLocaleString()} 字</strong></header>
    <VolumeNarrative volume={volume} />
    {volume.reader_promises.length > 0 && <div className="plan-tag-row"><span>读者承诺</span>
      {volume.reader_promises.map((promise) => <Tag key={promise}>{promise}</Tag>)}</div>}
  </section>)}</div>
}

function ArcEscalations({ arc }: { arc: StoryArc }) {
  if (!arc.escalation_points.length) return <span className="plan-muted">暂无升级节点</span>
  return <ol>{arc.escalation_points.map((point, index) => <li key={`${point.chapter_number}-${index}`}>
    <span>第 {point.chapter_number} 章</span>{point.description || displayValue(point as unknown as JsonValue)}
  </li>)}</ol>
}

function ArcsView({ arcs }: { arcs: StoryArc[] }) {
  return <div className="plan-arc-list">{arcs.map((arc) => <section key={arc.arc_id}>
    <header><div><Tag color={arc.is_core ? 'red' : 'default'}>{arc.is_core ? '核心弧' : arc.arc_type}</Tag>
      <h3>{arc.goal}</h3></div><span>第 {arc.start_chapter} - {arc.end_chapter} 章</span></header>
    <p><strong>解决条件</strong>{arc.resolution_condition}</p>
    <div className="plan-escalations"><strong>升级节点</strong><ArcEscalations arc={arc} /></div>
  </section>)}</div>
}

function SlotObligations({ slot }: { slot: ChapterSlot }) {
  const events = slot.must_happen.length ? slot.must_happen.join('；') : '待细化'
  return <details><summary>本章义务</summary><dl>
    <div><dt>必发事件</dt><dd>{events}</dd></div>
    <div><dt>状态变化</dt><dd>{slot.planned_state_delta || '待细化'}</dd></div>
    <div><dt>剧情弧</dt><dd>{slot.arc_ids.join('、') || '未关联'}</dd></div>
    <div><dt>伏笔</dt><dd>{[...slot.setup_ids.map((id) => `埋设 ${id}`), ...slot.payoff_ids.map((id) => `回收 ${id}`)].join('；') || '无'}</dd></div>
  </dl></details>
}

function SlotList({ slots }: { slots: ChapterSlot[] }) {
  return <ol className="plan-slot-list">{slots.map((slot) => <li key={slot.chapter_number}>
    <div className="plan-slot-main"><span>{String(slot.chapter_number).padStart(3, '0')}</span>
      <div><strong>{slot.story_function || '待规划章节功能'}</strong><small>{slot.target_words.toLocaleString()} 字 · {slot.detail_level === 'detailed' ? '已细化' : '骨架'}</small></div>
      <Tag>{statusLabels[slot.status] || slot.status}</Tag></div>
    <SlotObligations slot={slot} />
  </li>)}</ol>
}

function ChapterSpineView({ plan }: { plan: NovelPlan }) {
  const items = plan.volumes.map((volume) => ({
    key: volume.volume_id,
    label: <span>{volume.title || volume.volume_id}<small>第 {volume.start_chapter} - {volume.end_chapter} 章</small></span>,
    children: <SlotList slots={plan.chapter_slots.filter((slot) => slot.volume_id === volume.volume_id)} />,
  }))
  return <Collapse className="plan-spine" ghost defaultActiveKey={items[0]?.key ? [items[0].key] : []} items={items} />
}

interface NovelPlanViewProps {
  plan?: NovelPlan
  tactical?: TacticalPlanResponse
  tacticalVersions?: TacticalPlanVersionSummary[]
  tacticalLoadFailed?: boolean
  tacticalVersionsLoadFailed?: boolean
  headerAction?: ReactNode
  emptyDescription?: string
}

function PlanViewHeader({ plan, action }: { plan?: NovelPlan; action?: ReactNode }) {
  return <header className="plan-view-heading"><div><span className="eyebrow">Production Blueprint</span><h2>整书规划</h2></div>
    <div className="plan-view-actions">{plan && <span>Schema {plan.schema_version}</span>}{action}</div></header>
}

export function NovelPlanView({
  plan, tactical, tacticalVersions, tacticalLoadFailed, tacticalVersionsLoadFailed,
  headerAction, emptyDescription,
}: NovelPlanViewProps) {
  return <div className="novel-plan-view">
    <PlanViewHeader plan={plan} action={headerAction} />
    {!plan ? <div className="plan-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
      description={emptyDescription || '整书规划尚未建立'} /></div> : <Tabs className="plan-tabs" items={[
      { key: 'overview', label: <span><BookOutlined /> 整书</span>, children: <PlanOverview plan={plan} /> },
      { key: 'volumes', label: <span><PartitionOutlined /> 分卷</span>, children: <VolumesView volumes={plan.volumes} /> },
      { key: 'arcs', label: <span><BranchesOutlined /> 剧情弧</span>, children: <ArcsView arcs={plan.arcs} /> },
      { key: 'spine', label: <span><OrderedListOutlined /> 章节骨架</span>, children: <ChapterSpineView plan={plan} /> },
      { key: 'tactical', label: <span><AimOutlined /> 近期战术</span>, children: <TacticalPlanView
        tactical={tactical} versions={tacticalVersions} loadFailed={tacticalLoadFailed}
        versionsLoadFailed={tacticalVersionsLoadFailed} /> },
    ]} />}
  </div>
}
