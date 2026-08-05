import { PauseCircleOutlined } from '@ant-design/icons'
import { Button, Input, Segmented } from 'antd'
import { useState } from 'react'
import type {
  ChapterPlanRevisionScope, InterruptInfo, JsonValue, ReviewDecision, TitleSuggestion,
} from '@/types/novel'
import { requiresHumanReview } from '@/workflowReviewPolicy'
import {
  ChapterOutlineReview, CreativeBriefReview, MacroOutlineReview, QualityReview,
  RevisionReview, SummaryReview, TitleReview,
} from './ReviewContents'
import { CharacterDesignReview } from './CharacterDesignReview'
import { ChapterPlanReview } from './ChapterPlanReview'
import { NovelPlanProposalReview } from './NovelPlanProposalReview'
import {
  outlineFrom, proposalPayload, summaryReviewDetails, summaryTextsDistinct, titleCandidates,
} from './valueHelpers'

interface Props {
  interrupt?: InterruptInfo
  autoMode: boolean
  onResume: (value: unknown) => void
  onRetry: () => void
}

function proposalIdentity(interrupt: InterruptInfo): string | undefined {
  return interrupt.proposal?.proposal_id || interrupt.proposal_id
}

function proposalDecision(
  interrupt: InterruptInfo,
  decision: ReviewDecision['decision'],
  value?: unknown,
  scope?: ChapterPlanRevisionScope,
): ReviewDecision | undefined {
  const proposalId = proposalIdentity(interrupt)
  if (!proposalId) return undefined
  if (decision === 'accept') return { proposal_id: proposalId, decision }
  if (decision === 'regenerate') {
    return { proposal_id: proposalId, decision, ...(typeof value === 'string' ? { feedback: value } : {}) }
  }
  if (decision === 'revise') {
    return { proposal_id: proposalId, decision, instruction: String(value || ''), ...(scope ? { scope } : {}) }
  }
  return { proposal_id: proposalId, decision, value: value as JsonValue }
}

function legacyAcceptedValue(interrupt: InterruptInfo): unknown {
  if (interrupt.action === 'review_or_modify_creative_brief') return interrupt.ai_generated_creative_brief || 'accept'
  if (interrupt.action === 'confirm_or_provide_title') return titleCandidates(interrupt)[0] || '未命名小说'
  if (interrupt.action === 'confirm_or_provide_summary') return interrupt.ai_generated_summary || 'accept'
  if (['review_or_modify_outline', 'review_or_provide_chapter_outline'].includes(interrupt.action)) return outlineFrom(interrupt) || 'accept'
  return 'accept'
}

function decisionValue(
  interrupt: InterruptInfo,
  decision: ReviewDecision['decision'],
  value?: unknown,
): unknown {
  const command = proposalDecision(interrupt, decision, value)
  if (command) return command
  if (decision === 'accept') return legacyAcceptedValue(interrupt)
  if (decision === 'regenerate') return 'regenerate'
  return value
}

function primaryLabel(action: string): string {
  if (action === 'review_or_modify_creative_brief') return '确认创作简报'
  if (action === 'review_or_modify_character_design') return '确认角色设计'
  if (['review_or_modify_novel_plan', 'review_novel_plan'].includes(action)) return '确认整书规划'
  if (action === 'review_or_provide_chapter_outline') return '使用细纲，生成正文'
  if (action === 'review_or_modify_chapter_plan') return '确认战术与细纲，生成正文'
  if (action === 'review_reflection_issues') return '接受本章'
  if (action === 'ready_for_next_chapter') return '生成下一章'
  if (action === 'confirm_revision') return '接受修订'
  if (['quality_gate_exhausted', 'quality_gate_human_review'].includes(action)) return '接受当前版本'
  if (action === 'quality_review_unavailable') return '接受并标记未审读'
  return '接受并继续'
}

interface TitleActions { confirm: (item: TitleSuggestion) => void; regenerate: () => void }

function reviewContent(interrupt: InterruptInfo, title: TitleActions) {
  if (interrupt.action === 'review_or_modify_creative_brief') return <CreativeBriefReview interrupt={interrupt} />
  if (interrupt.action === 'confirm_or_provide_title') {
    return <TitleReview interrupt={interrupt} onConfirm={title.confirm} onRegenerate={title.regenerate} />
  }
  if (['confirm_or_provide_summary', 'summary_review_required'].includes(interrupt.action)) {
    return <SummaryReview interrupt={interrupt} />
  }
  if (['review_or_modify_novel_plan', 'review_novel_plan'].includes(interrupt.action)
    || interrupt.proposal?.kind === 'novel_plan') {
    return <NovelPlanProposalReview interrupt={interrupt} />
  }
  if (interrupt.action === 'review_or_modify_chapter_plan' || interrupt.proposal?.kind === 'chapter_plan') {
    return <ChapterPlanReview interrupt={interrupt} />
  }
  if (interrupt.action === 'review_or_modify_outline') return <MacroOutlineReview interrupt={interrupt} />
  if (interrupt.action === 'review_or_provide_chapter_outline') return <ChapterOutlineReview interrupt={interrupt} />
  if (['review_reflection_issues', 'quality_gate_exhausted', 'quality_gate_human_review', 'quality_review_unavailable'].includes(interrupt.action)) return <QualityReview interrupt={interrupt} />
  if (interrupt.action === 'confirm_revision') return <RevisionReview interrupt={interrupt} />
  return proposalPayload(interrupt) ? <div className="review-surface">当前提案已准备好，请确认后继续。</div> : null
}

function QualityActions({ interrupt, onResume }: Omit<Props, 'autoMode' | 'onRetry' | 'interrupt'> & { interrupt: InterruptInfo }) {
  const accept = () => onResume(decisionValue(interrupt, 'accept'))
  const revise = () => onResume(decisionValue(interrupt, 'revise', 'revise'))
  const regenerate = () => onResume(decisionValue(interrupt, 'regenerate'))
  return <div className="interrupt-actions">
    <Button type="primary" onClick={accept}>{primaryLabel(interrupt.action)}</Button>
    <Button onClick={revise}>按建议修订</Button>
    <Button onClick={regenerate}>重新生成正文</Button>
  </div>
}

function UnavailableActions({ interrupt, onResume }: Omit<Props, 'autoMode' | 'onRetry' | 'interrupt'> & { interrupt: InterruptInfo }) {
  const retry = () => onResume(decisionValue(interrupt, 'revise', 'retry'))
  const accept = () => onResume(decisionValue(interrupt, 'accept'))
  const rewrite = () => onResume(decisionValue(interrupt, 'regenerate'))
  return <div className="interrupt-actions">
    <Button type="primary" onClick={retry}>重新审读</Button>
    <Button onClick={accept}>接受并标记未审读</Button>
    <Button onClick={rewrite}>重写正文</Button>
  </div>
}

function SummaryRepairActions({ interrupt, onResume }: Omit<Props, 'autoMode' | 'onRetry' | 'interrupt'> & { interrupt: InterruptInfo }) {
  const details = summaryReviewDetails(interrupt)
  const [reader, setReader] = useState(details.reader || '')
  const [editorial, setEditorial] = useState(details.editorial || '')
  const readerValue = reader.trim()
  const editorialValue = editorial.trim()
  const valid = summaryTextsDistinct(readerValue, editorialValue)
  const replace = () => onResume(decisionValue(interrupt, 'replace', {
    reader_blurb: readerValue, editorial_brief: editorialValue,
  }))
  const regenerate = () => onResume(decisionValue(interrupt, 'regenerate'))
  return <>
    <div className="summary-repair-fields">
      <label>读者文案<Input.TextArea value={reader} onChange={(event) => setReader(event.target.value)} autoSize={{ minRows: 2, maxRows: 5 }} /></label>
      <label>内部简报<Input.TextArea value={editorial} onChange={(event) => setEditorial(event.target.value)} autoSize={{ minRows: 2, maxRows: 5 }} /></label>
    </div>
    <div className="interrupt-actions">
      <Button type="primary" disabled={!valid} onClick={replace}>提交修复后的简介</Button>
      <Button onClick={regenerate}>重新生成简介</Button>
    </div>
  </>
}

interface InstructionProps { interrupt: InterruptInfo; onResume: (value: unknown) => void }

const chapterPlanScopes = [
  { label: '仅近期战术', value: 'tactical' },
  { label: '仅当前章细纲', value: 'chapter_outline' },
  { label: '两者一起', value: 'both' },
] as const

function ChapterPlanInstructionEditor({ interrupt, onResume }: InstructionProps) {
  const [scope, setScope] = useState<ChapterPlanRevisionScope>('both')
  const [instruction, setInstruction] = useState('')
  const submit = () => {
    const text = instruction.trim()
    if (!text) return
    onResume(proposalDecision(interrupt, 'revise', text, scope) || text)
    setInstruction('')
  }
  return <div className="review-instruction chapter-plan-instruction">
    <label>修改范围<Segmented block value={scope} options={[...chapterPlanScopes]}
      onChange={(value) => setScope(value as ChapterPlanRevisionScope)} /></label>
    <Input.TextArea aria-label="章节计划修改要求" value={instruction}
      onChange={(event) => setInstruction(event.target.value)} placeholder="说明要调整的战术或细纲，不会直接修改原始 JSON"
      autoSize={{ minRows: 2, maxRows: 5 }} />
    <Button disabled={!instruction.trim()} onClick={submit}>按范围重新生成</Button>
  </div>
}

function InstructionEditor({ interrupt, onResume }: InstructionProps) {
  const [instruction, setInstruction] = useState('')
  const submit = () => {
    const text = instruction.trim()
    if (!text) return
    const command = proposalDecision(interrupt, 'revise', text)
    onResume(command || text)
    setInstruction('')
  }
  return <div className="review-instruction">
    <Input.TextArea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="输入具体修改要求" autoSize={{ minRows: 2, maxRows: 5 }} />
    <Button disabled={!instruction.trim()} onClick={submit}>按要求修订</Button>
  </div>
}

interface StandardActionProps {
  interrupt: InterruptInfo
  onResume: (value: unknown) => void
  acceptDisabled?: boolean
}

function StandardActions({ interrupt, onResume, acceptDisabled }: StandardActionProps) {
  const accept = () => onResume(decisionValue(interrupt, 'accept'))
  const regenerate = () => onResume(decisionValue(interrupt, 'regenerate'))
  const canRegenerate = interrupt.action !== 'ready_for_next_chapter'
  const acceptLabel = interrupt.proposal?.kind === 'chapter_plan'
    ? '确认战术与细纲，生成正文' : primaryLabel(interrupt.action)
  return <div className="interrupt-actions">
    <Button type="primary" disabled={acceptDisabled} onClick={accept}>{acceptLabel}</Button>
    {canRegenerate && <Button onClick={regenerate}>重新生成</Button>}
  </div>
}

export function WorkflowReview({ interrupt, autoMode, onResume }: Props) {
  if (!interrupt) return null
  const novelPlanReview = ['review_or_modify_novel_plan', 'review_novel_plan'].includes(interrupt.action)
    || interrupt.proposal?.kind === 'novel_plan'
  const chapterPlanReview = interrupt.action === 'review_or_modify_chapter_plan'
    || interrupt.proposal?.kind === 'chapter_plan'
  const humanReview = requiresHumanReview(interrupt.action, interrupt.proposal?.kind)
  if (autoMode && !humanReview) return null
  const titleActions = {
    confirm: (item: TitleSuggestion) => onResume(decisionValue(interrupt, 'replace', item)),
    regenerate: () => onResume(decisionValue(interrupt, 'regenerate')),
  }
  const characterDesign = interrupt.action === 'review_or_modify_character_design'
  const titleReview = interrupt.action === 'confirm_or_provide_title'
  const summaryRequired = interrupt.action === 'summary_review_required'
  const summaryComplete = interrupt.action !== 'confirm_or_provide_summary'
    || summaryReviewDetails(interrupt).complete
  const confirmCharacters = (value?: unknown) => onResume(decisionValue(interrupt, value ? 'replace' : 'accept', value))
  const regenerateCharacters = () => onResume(decisionValue(interrupt, 'regenerate'))
  const canInstruct = !['ready_for_next_chapter', 'require_novel_type'].includes(interrupt.action)
  return <section className="interrupt-block">
    <div className="interrupt-title"><PauseCircleOutlined /> 需要你的决定</div>
    <p>{interrupt.message || '请审阅当前结果后继续。'}</p>
    {characterDesign
      ? <CharacterDesignReview key={proposalIdentity(interrupt)} interrupt={interrupt} onConfirm={confirmCharacters} onRegenerate={regenerateCharacters} />
      : reviewContent(interrupt, titleActions)}
    {!characterDesign && (interrupt.action === 'quality_review_unavailable'
      ? <UnavailableActions interrupt={interrupt} onResume={onResume} />
      : summaryRequired ? <SummaryRepairActions interrupt={interrupt} onResume={onResume} />
      : novelPlanReview ? <StandardActions interrupt={interrupt} onResume={onResume} />
      : humanReview ? <QualityActions interrupt={interrupt} onResume={onResume} />
      : titleReview ? null
      : <StandardActions interrupt={interrupt} onResume={onResume} acceptDisabled={!summaryComplete} />)}
    {chapterPlanReview ? <ChapterPlanInstructionEditor interrupt={interrupt} onResume={onResume} />
      : canInstruct && (!humanReview || summaryRequired || novelPlanReview)
        && <InstructionEditor interrupt={interrupt} onResume={onResume} />}
  </section>
}
