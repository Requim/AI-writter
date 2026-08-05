import { Tag } from 'antd'
import type {
  ChapterExecutionContract, InterruptInfo, JsonValue, TacticalBeat, TacticalWindow,
} from '@/types/novel'
import { ChapterOutlineReview } from './ReviewContents'
import { ReviewHeading, ReviewRows, ReviewValue } from './ReviewPrimitives'
import { asRecord, proposalPayload } from './valueHelpers'

function tacticalWindowFrom(interrupt: InterruptInfo): TacticalWindow | undefined {
  const payload = proposalPayload(interrupt)
  const value = asRecord(payload?.tactical_window) || asRecord(payload?.window)
  if (!value || !Array.isArray(value.beats)) return undefined
  const beats = value.beats.map((item) => {
    const record = asRecord(item)
    return asRecord(record?.tactical) || record
  }).filter(Boolean) as unknown as TacticalBeat[]
  return { ...value, beats } as unknown as TacticalWindow
}

function executionContractFrom(interrupt: InterruptInfo): ChapterExecutionContract | undefined {
  const payload = proposalPayload(interrupt)
  const outline = asRecord(payload?.chapter_outline)
  const value = asRecord(payload?.execution_contract) || asRecord(outline?.chapter_execution_contract)
  return value as unknown as ChapterExecutionContract | undefined
}

function currentSlotFrom(interrupt: InterruptInfo) {
  const payload = proposalPayload(interrupt)
  const direct = asRecord(payload?.current_slot) || asRecord(payload?.slot_contract)
  if (direct) return direct
  const assembled = Array.isArray(payload?.assembled_slots) ? payload.assembled_slots : []
  const hydrated = Array.isArray(asRecord(payload?.tactical_window)?.beats)
    ? asRecord(payload?.tactical_window)?.beats as JsonValue[] : []
  const slots = [...assembled, ...hydrated]
  const chapter = interrupt.chapter_number ?? executionContractFrom(interrupt)?.chapter_number
  return slots.map(asRecord).map((item) => asRecord(item?.slot_contract) || item)
    .find((slot) => slot?.chapter_number === chapter)
}

function TacticalBeatSummary({ beat }: { beat: TacticalBeat }) {
  return <li><span>第 {beat.chapter_number} 章</span><div><strong>{beat.tactical_goal}</strong>
    <small>{beat.approach}</small><em>{beat.exit_hook}</em></div></li>
}

function TacticalWindowReview({ window }: { window?: TacticalWindow }) {
  if (!window) return <p className="chapter-plan-missing">战术窗口尚未装配</p>
  return <section className="chapter-plan-window"><header><div><span>战术 V{window.version}</span>
    <strong>第 {window.start_chapter} - {window.end_chapter} 章</strong></div>
    <Tag>{window.beats.length} 章视野</Tag></header><p>{window.window_objective}</p>
    <ol>{window.beats.map((beat) => <TacticalBeatSummary key={beat.chapter_number} beat={beat} />)}</ol>
  </section>
}

function HardSlotReview({ interrupt }: { interrupt: InterruptInfo }) {
  const slot = currentSlotFrom(interrupt)
  if (!slot) return null
  const obligations = Array.isArray(slot.obligations)
    ? slot.obligations.map(asRecord).map((item) => item?.event)
      .filter((value): value is JsonValue => value !== undefined) : slot.must_happen
  const delta = asRecord(slot.planned_state_delta)?.value ?? slot.planned_state_delta
  const setups = Array.isArray(slot.setup_requirements)
    ? slot.setup_requirements.map(asRecord).map((item) => item?.setup_id)
      .filter((value): value is JsonValue => value !== undefined) : slot.setup_ids
  const payoffs = Array.isArray(slot.payoff_requirements)
    ? slot.payoff_requirements.map(asRecord).map((item) => item?.payoff_id)
      .filter((value): value is JsonValue => value !== undefined) : slot.payoff_ids
  return <details open><summary>当前槽位硬约束</summary><ReviewRows rows={[
    ['章节功能', slot.story_function], ['必发事件', obligations],
    ['状态变化', delta], ['设立伏笔', setups],
    ['回收伏笔', payoffs], ['目标字数', slot.target_words],
  ]} /></details>
}

function coverageLabel(value: JsonValue): string {
  if (value === true) return '已覆盖'
  if (value === false || value == null) return '未覆盖'
  if (typeof value === 'number') return `场景 ${value}`
  if (typeof value === 'string') return value
  return '已映射'
}

function CoverageMatrix({ contract }: { contract?: ChapterExecutionContract }) {
  if (!contract) return null
  const rows = [
    ...Object.entries(contract.obligation_coverage || {}),
    ...Object.entries(contract.state_delta_coverage || {}),
    ...Object.entries(contract.setup_payoff_coverage || {}),
  ]
  return <details open><summary>执行覆盖矩阵</summary><div className="execution-coverage-matrix">
    {rows.map(([id, value]) => <div key={id}><code>{id}</code>
      <span>{coverageLabel(value)}</span></div>)}
  </div></details>
}

export function ChapterPlanReview({ interrupt }: { interrupt: InterruptInfo }) {
  const payload = proposalPayload(interrupt)
  const contract = executionContractFrom(interrupt)
  return <>
    <div className="review-surface chapter-plan-review">
      <ReviewHeading eyebrow="滚动战术与执行细纲"
        title={`第 ${interrupt.chapter_number ?? contract?.chapter_number ?? ''} 章联合审核`} />
      <TacticalWindowReview window={tacticalWindowFrom(interrupt)} />
      <HardSlotReview interrupt={interrupt} />
      <CoverageMatrix contract={contract} />
      {payload?.previous_window_diff !== undefined && <details><summary>相对上一窗口的变化</summary>
        <ReviewValue value={payload.previous_window_diff} /></details>}
    </div>
    <ChapterOutlineReview interrupt={interrupt} />
  </>
}
