import { AimOutlined, HistoryOutlined } from '@ant-design/icons'
import { Empty, Tag } from 'antd'
import type {
  AssembledTacticalSlot, TacticalBeat, TacticalPlanResponse, TacticalPlanVersionSummary,
} from '@/types/novel'

const statusPresentation = {
  active: { label: '当前有效', color: 'green' },
  stale: { label: '等待刷新', color: 'orange' },
  missing: { label: '尚未生成', color: 'default' },
} as const

function BeatHeader({ beat }: { beat: TacticalBeat }) {
  return <header><span>{String(beat.chapter_number).padStart(3, '0')}</span><div>
    <strong>{beat.tactical_goal || '待确定本章战术目标'}</strong>
    <small>{beat.pacing || '节奏待定'} · {beat.slot_ref}</small>
  </div></header>
}

function HardContract({ slot }: { slot?: AssembledTacticalSlot }) {
  if (!slot) return <p className="tactical-contract-missing">槽位硬约束暂不可用</p>
  const contract = slot.slot_contract
  const clues = [
    ...contract.setup_requirements.map((item) => `设立 ${item.setup_id}`),
    ...contract.payoff_requirements.map((item) => `回收 ${item.payoff_id}`),
  ]
  return <dl className="tactical-hard-contract">
    <div><dt>必发事件</dt><dd>{contract.obligations.map((item) => item.event).join('；') || '无'}</dd></div>
    <div><dt>状态变化</dt><dd>{contract.planned_state_delta.value || '无'}</dd></div>
    <div><dt>伏笔任务</dt><dd>{clues.join('；') || '无'}</dd></div>
    <div><dt>字数契约</dt><dd>{contract.target_words.toLocaleString()} 字</dd></div>
  </dl>
}

function TacticalBeatItem({ beat, slot }: { beat: TacticalBeat; slot?: AssembledTacticalSlot }) {
  return <li className="tactical-beat-item">
    <BeatHeader beat={beat} />
    <div className="tactical-beat-route">
      <p><b>承接</b>{beat.bridge_from_previous || '从上一章状态自然进入'}</p>
      <p><b>推进</b>{beat.approach || '待细化'}</p>
      <p><b>加压</b>{beat.pressure_escalation || '待细化'}</p>
      <p><b>出口</b>{beat.exit_hook || '待细化'}</p>
    </div>
    <details><summary>查看不可改写的槽位契约</summary><HardContract slot={slot} /></details>
  </li>
}

function TacticalWindowBody({ tactical }: { tactical: TacticalPlanResponse }) {
  const window = tactical.window
  if (!window) return <div className="tactical-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
    description="下一章开始前将生成近期战术" /></div>
  const slots = new Map(tactical.assembled_slots.map((slot) => [slot.slot_contract.chapter_number, slot]))
  return <>
    <div className="tactical-window-meta">
      <Tag color={statusPresentation[tactical.status].color}>{statusPresentation[tactical.status].label}</Tag>
      <span>战术 V{window.version}</span><span>整书计划 V{window.novel_plan_version}</span>
      <span>故事事实修订 {window.story_state_revision}</span>
    </div>
    <section className="tactical-objective"><span className="eyebrow">Window Objective</span>
      <h3>第 {window.start_chapter} - {window.end_chapter} 章</h3><p>{window.window_objective}</p></section>
    <ol className="tactical-beat-list">{window.beats.map((beat) => <TacticalBeatItem
      key={`${window.version}-${beat.chapter_number}`} beat={beat} slot={slots.get(beat.chapter_number)} />)}</ol>
  </>
}

function TacticalHistory({ versions, loadFailed }: {
  versions: TacticalPlanVersionSummary[]
  loadFailed?: boolean
}) {
  return <section className="tactical-history"><header><HistoryOutlined /><div><h3>版本历史</h3>
    <p>每次正文事实刷新后都会保留一份只追加的战术快照。</p></div></header>
    {loadFailed ? <p className="plan-muted">版本历史暂时无法读取，请刷新后重试</p>
      : versions.length ? <ol>{versions.map((version) => <li key={version.version}>
      <strong>V{version.version}</strong><span>第 {version.start_chapter} - {version.end_chapter} 章</span>
      <small>计划 V{version.novel_plan_version} · 事实 {version.story_state_revision}</small>
      <time>{new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(version.created_at))}</time>
    </li>)}</ol> : <p className="plan-muted">尚无历史版本</p>}
  </section>
}

interface TacticalPlanViewProps {
  tactical?: TacticalPlanResponse
  versions?: TacticalPlanVersionSummary[]
  loadFailed?: boolean
  versionsLoadFailed?: boolean
}

export function TacticalPlanView({
  tactical, versions = [], loadFailed, versionsLoadFailed,
}: TacticalPlanViewProps) {
  const fallback: TacticalPlanResponse = { status: 'missing', window: null, assembled_slots: [] }
  return <div className="tactical-plan-view">
    <div className="tactical-section-heading"><AimOutlined /><div><span className="eyebrow">Near-term Tactics</span>
      <h3>近期战术</h3></div></div>
    {loadFailed ? <div className="tactical-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
      description="近期战术暂时无法读取，请刷新后重试" /></div> : <TacticalWindowBody tactical={tactical || fallback} />}
    <TacticalHistory versions={versions} loadFailed={versionsLoadFailed} />
  </div>
}
