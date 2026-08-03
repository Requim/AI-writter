import { PauseCircleOutlined } from '@ant-design/icons'
import { Button, Input } from 'antd'
import { useState } from 'react'
import type { InterruptInfo, TitleSuggestion } from '@/types/novel'
import {
  ChapterOutlineReview, CreativeBriefReview, MacroOutlineReview, QualityReview,
  RevisionReview, SummaryReview, TitleReview,
} from './ReviewContents'
import { outlineFrom, proposalPayload, titleCandidates } from './valueHelpers'

interface Props {
  interrupt?: InterruptInfo
  autoMode: boolean
  onResume: (value: unknown) => void
  onRetry: () => void
}

type Decision = 'accept' | 'regenerate' | 'modify'

function proposalIdentity(interrupt: InterruptInfo): string | undefined {
  return interrupt.proposal?.proposal_id || interrupt.proposal_id
}

function proposalDecision(interrupt: InterruptInfo, decision: Decision, value?: unknown, feedback?: string) {
  const proposalId = proposalIdentity(interrupt)
  if (!proposalId) return undefined
  return { proposal_id: proposalId, decision, ...(value === undefined ? {} : { value }), ...(feedback ? { feedback } : {}) }
}

function legacyAcceptedValue(interrupt: InterruptInfo): unknown {
  if (interrupt.action === 'review_or_modify_creative_brief') return interrupt.ai_generated_creative_brief || 'accept'
  if (interrupt.action === 'confirm_or_provide_title') return titleCandidates(interrupt)[0] || '未命名小说'
  if (interrupt.action === 'confirm_or_provide_summary') return interrupt.ai_generated_summary || 'accept'
  if (['review_or_modify_outline', 'review_or_provide_chapter_outline'].includes(interrupt.action)) return outlineFrom(interrupt) || 'accept'
  return 'accept'
}

function decisionValue(interrupt: InterruptInfo, decision: Decision, value?: unknown): unknown {
  const command = proposalDecision(interrupt, decision, value)
  if (command) return command
  if (decision === 'accept') return legacyAcceptedValue(interrupt)
  if (decision === 'regenerate') return 'regenerate'
  return value
}

function primaryLabel(action: string): string {
  if (action === 'review_or_modify_creative_brief') return '确认创作简报'
  if (action === 'review_or_provide_chapter_outline') return '使用细纲，生成正文'
  if (action === 'review_reflection_issues') return '接受本章'
  if (action === 'ready_for_next_chapter') return '生成下一章'
  if (action === 'confirm_revision') return '接受修订'
  if (['quality_gate_exhausted', 'quality_gate_human_review'].includes(action)) return '接受当前版本'
  if (action === 'quality_review_unavailable') return '接受并标记未审读'
  return '接受并继续'
}

function reviewContent(interrupt: InterruptInfo, onSelect: (item: TitleSuggestion) => void) {
  if (interrupt.action === 'review_or_modify_creative_brief') return <CreativeBriefReview interrupt={interrupt} />
  if (interrupt.action === 'confirm_or_provide_title') return <TitleReview interrupt={interrupt} onSelect={onSelect} />
  if (interrupt.action === 'confirm_or_provide_summary') return <SummaryReview interrupt={interrupt} />
  if (interrupt.action === 'review_or_modify_outline') return <MacroOutlineReview interrupt={interrupt} />
  if (interrupt.action === 'review_or_provide_chapter_outline') return <ChapterOutlineReview interrupt={interrupt} />
  if (['review_reflection_issues', 'quality_gate_exhausted', 'quality_gate_human_review', 'quality_review_unavailable'].includes(interrupt.action)) return <QualityReview interrupt={interrupt} />
  if (interrupt.action === 'confirm_revision') return <RevisionReview interrupt={interrupt} />
  return proposalPayload(interrupt) ? <div className="review-surface">当前提案已准备好，请确认后继续。</div> : null
}

function QualityActions({ interrupt, onResume }: Omit<Props, 'autoMode' | 'onRetry' | 'interrupt'> & { interrupt: InterruptInfo }) {
  const accept = () => onResume(decisionValue(interrupt, 'accept'))
  const revise = () => onResume(decisionValue(interrupt, 'modify', 'revise'))
  const regenerate = () => onResume(decisionValue(interrupt, 'regenerate'))
  return <div className="interrupt-actions">
    <Button type="primary" onClick={accept}>{primaryLabel(interrupt.action)}</Button>
    <Button onClick={revise}>按建议修订</Button>
    <Button onClick={regenerate}>重新生成正文</Button>
  </div>
}

function UnavailableActions({ interrupt, onResume }: Omit<Props, 'autoMode' | 'onRetry' | 'interrupt'> & { interrupt: InterruptInfo }) {
  const retry = () => onResume(decisionValue(interrupt, 'modify', 'retry'))
  const accept = () => onResume(decisionValue(interrupt, 'accept'))
  const rewrite = () => onResume(decisionValue(interrupt, 'regenerate'))
  return <div className="interrupt-actions">
    <Button type="primary" onClick={retry}>重新审读</Button>
    <Button onClick={accept}>接受并标记未审读</Button>
    <Button onClick={rewrite}>重写正文</Button>
  </div>
}

interface InstructionProps { interrupt: InterruptInfo; onResume: (value: unknown) => void }

function InstructionEditor({ interrupt, onResume }: InstructionProps) {
  const [instruction, setInstruction] = useState('')
  const submit = () => {
    const text = instruction.trim()
    if (!text) return
    const command = interrupt.action === 'review_or_modify_creative_brief'
      ? proposalDecision(interrupt, 'regenerate', undefined, text)
      : proposalDecision(interrupt, 'modify', text)
    onResume(command || text)
    setInstruction('')
  }
  return <div className="review-instruction">
    <Input.TextArea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="输入具体修改要求" autoSize={{ minRows: 2, maxRows: 5 }} />
    <Button disabled={!instruction.trim()} onClick={submit}>按要求修订</Button>
  </div>
}

function StandardActions({ interrupt, onResume }: Omit<Props, 'autoMode' | 'onRetry' | 'interrupt'> & { interrupt: InterruptInfo }) {
  const accept = () => onResume(decisionValue(interrupt, 'accept'))
  const regenerate = () => onResume(decisionValue(interrupt, 'regenerate'))
  const canRegenerate = interrupt.action !== 'ready_for_next_chapter'
  return <div className="interrupt-actions">
    <Button type="primary" onClick={accept}>{primaryLabel(interrupt.action)}</Button>
    {canRegenerate && <Button onClick={regenerate}>重新生成</Button>}
  </div>
}

export function WorkflowReview({ interrupt, autoMode, onResume }: Props) {
  if (!interrupt) return null
  const humanReview = ['quality_gate_exhausted', 'quality_gate_human_review', 'quality_review_unavailable'].includes(interrupt.action)
  if (autoMode && !humanReview) return null
  const selectTitle = (item: TitleSuggestion) => onResume(decisionValue(interrupt, 'modify', item))
  const canInstruct = !['ready_for_next_chapter', 'require_novel_type'].includes(interrupt.action)
  return <section className="interrupt-block">
    <div className="interrupt-title"><PauseCircleOutlined /> 需要你的决定</div>
    <p>{interrupt.message || '请审阅当前结果后继续。'}</p>
    {reviewContent(interrupt, selectTitle)}
    {interrupt.action === 'quality_review_unavailable'
      ? <UnavailableActions interrupt={interrupt} onResume={onResume} />
      : humanReview ? <QualityActions interrupt={interrupt} onResume={onResume} />
      : <StandardActions interrupt={interrupt} onResume={onResume} />}
    {canInstruct && !humanReview && <InstructionEditor interrupt={interrupt} onResume={onResume} />}
  </section>
}
