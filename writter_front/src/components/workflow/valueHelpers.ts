import type {
  CharacterDesignProposal, InterruptInfo, JsonValue, PendingProposal, TitleSuggestion,
} from '@/types/novel'

export type JsonRecord = Record<string, JsonValue>

export function asRecord(value: unknown): JsonRecord | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : undefined
}

export function asText(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined
}

export function asTextList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

export function proposalFrom(interrupt: InterruptInfo): PendingProposal | undefined {
  return interrupt.proposal || undefined
}

export function proposalPayload(interrupt: InterruptInfo): JsonRecord | undefined {
  return asRecord(proposalFrom(interrupt)?.payload)
}

export function summaryTextsDistinct(reader?: string, editorial?: string): boolean {
  if (!reader || !editorial) return false
  return reader.replace(/\s+/g, '') !== editorial.replace(/\s+/g, '')
}

export function summaryReviewDetails(interrupt: InterruptInfo) {
  const payload = proposalPayload(interrupt)
  const reader = asText(payload?.reader_blurb) || interrupt.ai_generated_summary
  const legacy = payload?.legacy_single_view === true || !proposalFrom(interrupt)
  const editorial = asText(payload?.editorial_brief) || (legacy ? reader : undefined)
  const distinct = summaryTextsDistinct(reader, editorial)
  return { reader, editorial, legacy, complete: Boolean(reader && editorial && (legacy || distinct)) }
}

export function summaryValidationErrors(interrupt: InterruptInfo): string[] {
  return asTextList(proposalPayload(interrupt)?.validation_errors)
}

export function outlineFrom(interrupt: InterruptInfo): JsonRecord | undefined {
  const proposal = proposalFrom(interrupt)
  const payload = proposalPayload(interrupt)
  const direct = ['outline', 'chapter_outline'].includes(proposal?.kind ?? '') ? payload : undefined
  return asRecord(payload?.chapter_outline) || asRecord(payload?.outline)
    || direct || interrupt.ai_generated_outline
}

export function characterDesignFrom(interrupt: InterruptInfo): CharacterDesignProposal | undefined {
  const payload = proposalPayload(interrupt)
  const source = interrupt.action === 'review_or_modify_character_design'
    ? payload || interrupt.ai_generated_character_design : undefined
  if (!source || !Array.isArray(source.core_roles)) return undefined
  return source as unknown as CharacterDesignProposal
}

export function titleCandidates(interrupt: InterruptInfo): TitleSuggestion[] {
  const proposal = proposalFrom(interrupt)
  const payload = proposalPayload(interrupt)
  const source = Array.isArray(proposal?.payload) ? proposal.payload
    : Array.isArray(payload?.candidates) ? payload.candidates : interrupt.ai_suggestions
  if (!Array.isArray(source)) return []
  return source.map((item) => typeof item === 'string' ? { title: item } : item as unknown as TitleSuggestion)
    .filter((item) => typeof item.title === 'string')
    .sort((left, right) => (right.total_score ?? 0) - (left.total_score ?? 0))
}

export function displayValue(value: JsonValue | undefined): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value, null, 2)
}
