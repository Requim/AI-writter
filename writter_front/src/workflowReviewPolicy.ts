export const HUMAN_REQUIRED_ACTIONS = new Set([
  'quality_gate_exhausted',
  'quality_gate_human_review',
  'quality_review_unavailable',
  'summary_review_required',
  'review_or_modify_novel_plan',
  'review_novel_plan',
])

export function requiresHumanReview(action: string, proposalKind?: string): boolean {
  return HUMAN_REQUIRED_ACTIONS.has(action) || proposalKind === 'novel_plan'
}
