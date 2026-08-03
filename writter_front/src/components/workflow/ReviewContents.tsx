import { Button, Tabs, Tag } from 'antd'
import { useState } from 'react'
import type { InterruptInfo, JsonValue, TitleSuggestion } from '@/types/novel'
import { ReviewHeading, ReviewRows, ReviewValue } from './ReviewPrimitives'
import { asRecord, asText, outlineFrom, proposalFrom, proposalPayload, titleCandidates } from './valueHelpers'
import { qualityScoreOutOfFive } from './presentation'

interface ReviewProps { interrupt: InterruptInfo }

const briefLabels: Array<[string, string]> = [
  ['核心设想', 'core_premise'], ['主角驱动力', 'protagonist_drive'], ['核心冲突', 'core_conflict'],
  ['主题命题', 'theme_question'], ['读者体验', 'reader_promise'], ['基调', 'tone'],
  ['原创锚点', 'originality_anchor'], ['内容边界', 'content_boundaries'],
]

export function CreativeBriefReview({ interrupt }: ReviewProps) {
  const payload = proposalPayload(interrupt)
  const legacy = interrupt.ai_generated_creative_brief as Record<string, JsonValue> | undefined
  const direct = proposalFrom(interrupt)?.kind === 'creative_brief' ? payload : undefined
  const brief = asRecord(payload?.creative_brief) || direct || legacy
  if (!brief) return null
  return <div className="review-surface"><ReviewHeading eyebrow="创作简报" /><ReviewRows rows={briefLabels.map(([label, key]) => [label, brief[key]])} /></div>
}

interface TitleReviewProps extends ReviewProps { onSelect: (item: TitleSuggestion, index: number) => void }

export function TitleReview({ interrupt, onSelect }: TitleReviewProps) {
  const [expanded, setExpanded] = useState(false)
  const suggestions = titleCandidates(interrupt)
  const visible = expanded ? suggestions : suggestions.slice(0, 3)
  if (!suggestions.length) return null
  return <div className="review-surface title-review">
    <ReviewHeading eyebrow="书名候选" title="先看最有潜力的三个" />
    {visible.map((item, index) => <Button key={item.title} type="text" block onClick={() => onSelect(item, index)}>
      <span className="title-choice"><strong>{item.title}</strong><span>{item.category && <Tag>{item.category}</Tag>}{item.total_score != null && <small>{item.total_score} 分</small>}</span></span>
      {item.hint && <small>{item.hint}</small>}
    </Button>)}
    {suggestions.length > 3 && <Button type="link" className="expand-titles" onClick={() => setExpanded((value) => !value)}>{expanded ? '收起候选' : `展开其余 ${suggestions.length - 3} 个`}</Button>}
  </div>
}

export function SummaryReview({ interrupt }: ReviewProps) {
  const payload = proposalPayload(interrupt)
  const reader = asText(payload?.reader_blurb) || interrupt.ai_generated_summary
  const editorial = asText(payload?.editorial_brief) || reader
  if (!reader && !editorial) return null
  return <div className="review-surface summary-review">
    <ReviewHeading eyebrow="简介提案" />
    <Tabs size="small" items={[
      { key: 'reader', label: '读者文案', children: <p>{reader}</p> },
      { key: 'editorial', label: '内部简报', children: <p>{editorial}</p> },
    ]} />
  </div>
}

function characterSummary(outline: Record<string, JsonValue>): JsonValue | undefined {
  return outline.main_characters || outline.characters
}

export function MacroOutlineReview({ interrupt }: ReviewProps) {
  const payload = proposalPayload(interrupt)
  const outline = outlineFrom(interrupt)
  const validation = payload?.validation ?? interrupt.validation as JsonValue | undefined
  if (!outline) return null
  return <div className="review-surface macro-outline-review">
    <ReviewHeading eyebrow="全书总纲" title={asText(outline.title)} />
    <ReviewRows rows={[
      ['故事背景', outline.story_background], ['主要人物', characterSummary(outline)],
      ['主线推进', outline.main_plot], ['分卷 / 章节规划', outline.volumes || outline.chapters],
      ['写作风格', outline.writing_style], ['计划章节', outline.total_chapters],
    ]} />
    {validation !== undefined && <details><summary>结构校验与提醒</summary><ReviewValue value={validation} /></details>}
  </div>
}

export function ChapterOutlineReview({ interrupt }: ReviewProps) {
  const outline = outlineFrom(interrupt)
  if (!outline) return null
  return <div className="review-surface chapter-outline-review">
    <ReviewHeading eyebrow={`第 ${interrupt.chapter_number ?? outline.chapter_number ?? ''} 章细纲`} title={asText(outline.title)} />
    <ReviewRows rows={[
      ['章节目标', outline.chapter_goal], ['戏剧问题', outline.dramatic_question], ['人物欲望', outline.desire],
      ['主动阻碍', outline.obstacle], ['关键转折', outline.turn], ['付出代价', outline.price_paid],
      ['不可逆变化', outline.state_delta], ['关键事件', outline.key_events], ['预计字数', outline.estimated_word_count],
    ]} />
    {outline.scenes !== undefined && <details open><summary>场景义务</summary><ReviewValue value={outline.scenes} /></details>}
    <details><summary>因果与连续性</summary><ReviewRows rows={[
      ['入场状态', outline.entry_state], ['因果链', outline.causal_chain], ['状态变化', outline.state_changes],
      ['知识边界', outline.knowledge_boundaries], ['连续性约束', outline.continuity_constraints],
      ['逻辑钩子', outline.logic_hooks], ['退场状态', outline.exit_state],
    ]} /></details>
  </div>
}

const scoreLabels: Record<string, string> = {
  causality: '因果', continuity: '连续性', character: '人物', scene_function: '场景功能',
  voice: '叙述声音', prose_specificity: '语言具体度', ending_effect: '结尾效果',
}

function scoreText(value: JsonValue): string {
  return typeof value === 'number' ? `${qualityScoreOutOfFive(value).toFixed(1)} / 5` : '待核对'
}

function densityText(value: JsonValue | undefined): string {
  if (typeof value === 'string') return value.endsWith('%') ? value : `${value}%`
  return typeof value === 'number' ? `${value}%` : '待核对'
}

export function QualityReview({ interrupt }: ReviewProps) {
  const payload = proposalPayload(interrupt) || {}
  const gate = asRecord(payload.gate) || payload
  const scores = asRecord(gate.rubric_scores)
  const wordCount = asRecord(gate.word_count_analysis)
  const issues = Array.isArray(payload.issues) ? payload.issues
    : Array.isArray(gate.issues) ? gate.issues : interrupt.issues || []
  const rows = scores ? Object.entries(scores).map(([key, value]) => [scoreLabels[key] || key, scoreText(value)]) as Array<[string, JsonValue]> : []
  return <div className="review-surface quality-review">
    <ReviewHeading eyebrow="质量报告" title={interrupt.chapter_number ? `第 ${interrupt.chapter_number} 章` : undefined} />
    {asText(payload.reason) && <p>{asText(payload.reason)}</p>}
    {rows.length > 0 && <ReviewRows rows={rows} />}
    {wordCount && <div className="quality-density"><span>有效内容密度</span><strong>{densityText(wordCount.effective_density)}</strong></div>}
    {issues.length > 0 && <details open><summary>问题、证据与处理建议</summary><ReviewValue value={issues as JsonValue} /></details>}
  </div>
}

export function RevisionReview({ interrupt }: ReviewProps) {
  const payload = proposalPayload(interrupt) || {}
  const explicitPreview = asText(payload.preview) || asText(interrupt.revised_content_preview)
  const content = asText(payload.revised_content) || asText(interrupt.revised_content)
  const preview = explicitPreview || (content && `${content.slice(0, 1200)}${content.length > 1200 ? '…' : ''}`)
  return <div className="review-surface revision-review">
    <ReviewHeading eyebrow="修订结果" title={interrupt.chapter_number ? `第 ${interrupt.chapter_number} 章` : undefined} />
    {preview ? <p className="revision-preview">{preview}</p> : <p>修订稿已经生成，正文区保留完整内容。</p>}
    {payload.changes !== undefined && <details><summary>本轮修改说明</summary><ReviewValue value={payload.changes} /></details>}
  </div>
}
