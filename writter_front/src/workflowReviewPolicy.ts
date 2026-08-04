export const HUMAN_REQUIRED_ACTIONS = new Set([
  'quality_gate_exhausted',
  'quality_gate_human_review',
  'quality_review_unavailable',
  'summary_review_required',
])

export function requiresHumanReview(action: string): boolean {
  return HUMAN_REQUIRED_ACTIONS.has(action)
}
