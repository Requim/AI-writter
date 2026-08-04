import type { JsonValue } from '@/types/novel'
import { asRecord, displayValue } from './valueHelpers'

interface ReviewRowsProps { rows: Array<[string, JsonValue | undefined]> }

const fieldLabels: Record<string, string> = {
  name: '姓名', role: '身份', goal: '目标', motivation: '动机', conflict: '冲突',
  description: '说明', location: '地点', time: '时间', characters: '人物', known: '已知',
  unknown: '未知', subject: '对象', before: '此前', after: '此后', evidence_event: '依据事件',
  scene_goal: '场景目标', desire: '欲望', obstacle: '阻碍', tactic: '策略', events: '事件链',
  turn: '转折', price_paid: '代价', state_delta: '状态变化', exit_hook: '退场钩子', purpose: '场景功能',
  entry: '进入', struggle: '对抗', result: '结果', callback: '回收伏笔', setup: '新设伏笔',
  last_action: '最后行动', next_pressure: '下一压力', open_conflicts: '未决冲突',
  issue_id: '问题编号', type: '问题类型', severity: '严重程度', priority_action: '处理优先级',
  evidence: '原文证据', suggestion: '操作建议', suggested_fix_text: '建议改写',
  issue_resolved: '是否解决', evidence_valid: '证据是否有效',
  from: '发起人物', to: '关联人物', relation: '关系',
}

function fieldLabel(key: string): string {
  return fieldLabels[key] || key.replaceAll('_', ' ')
}

export function ReviewRows({ rows }: ReviewRowsProps) {
  const visible = rows.filter(([, value]) => value !== undefined && value !== '' && value !== null)
  if (!visible.length) return null
  return <dl className="review-rows">{visible.map(([label, value]) => (
    <div key={label}><dt>{label}</dt><dd><ReviewValue value={value} /></dd></div>
  ))}</dl>
}

export function ReviewValue({ value }: { value: JsonValue | undefined }) {
  if (Array.isArray(value)) return <ol className="review-list">{value.map((item, index) => <li key={index}><ReviewValue value={item} /></li>)}</ol>
  const record = asRecord(value)
  if (record) return <dl className="nested-review">{Object.entries(record).map(([key, item]) => (
    <div key={key}><dt>{fieldLabel(key)}</dt><dd><ReviewValue value={item} /></dd></div>
  ))}</dl>
  return <span>{displayValue(value)}</span>
}

export function ReviewHeading({ eyebrow, title }: { eyebrow: string; title?: string }) {
  return <div className="review-heading"><span>{eyebrow}</span>{title && <strong>{title}</strong>}</div>
}
