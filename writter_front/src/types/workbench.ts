import type { ChapterSummary } from './novel'

export type WorkbenchAssetKind = 'idea' | 'world' | 'character' | 'outline' | 'chapter' | 'reference'
export type WorkbenchIntent = 'discuss' | 'setting' | 'outline' | 'write' | 'continue' | 'rewrite' | 'review'
export type AdoptionAcceptance = 'reviewed' | 'with_issues' | 'unreviewed'

export interface WorkbenchConversation {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface WorkbenchSource {
  source_type: string
  source_id: string
  title: string
  version: number
  start: number
  end: number
  text: string
  score: number
}

export interface WorkbenchPreviousAttempt {
  content: string
  status: string
}

export interface WorkbenchMessage {
  id: string
  conversation_id: string
  role: 'user' | 'assistant' | 'system' | string
  content: string
  status: string
  intent: WorkbenchIntent | string | null
  sources: WorkbenchSource[]
  job_id: string | null
  retrieval_available?: boolean
  previous_attempts?: WorkbenchPreviousAttempt[]
  created_at: string
}

export interface WorkbenchJob {
  id: string
  conversation_id: string
  message_id: string
  status: string
  content: string
  error: string | null
  sources: WorkbenchSource[]
  intent: WorkbenchIntent | string
  chapter_index: number | null
  target_chapter_id: string | null
  retrieval_available?: boolean
  previous_attempts?: WorkbenchPreviousAttempt[]
  created_at: string
  updated_at: string
}

export interface AssetReviewGate {
  decision?: string
  score?: number
  [key: string]: unknown
}

export interface AssetReviewIssue {
  severity?: string
  description?: string
  suggestion?: string
  evidence?: string
  [key: string]: unknown
}

export interface AssetReview {
  asset_version: number
  basis: string
  gate: AssetReviewGate
  issues: AssetReviewIssue[]
  content_hash: string
}

export interface WorkbenchAsset {
  id: string
  title: string
  kind: WorkbenchAssetKind
  content: string
  version: number
  source_message_id: string | null
  provenance: Record<string, unknown> | null
  review: AssetReview | null
  adopted_chapter_id: string | null
  created_at: string
  updated_at: string
}

export interface WorkbenchOverview {
  novel: { id: string; title?: string; novel_type: string }
  conversations: WorkbenchConversation[]
  assets: WorkbenchAsset[]
  chapters: ChapterSummary[]
  legacy_sources: WorkbenchSource[]
  enabled: boolean
}

export interface WorkbenchSearchResponse {
  hits: WorkbenchSource[]
  available: boolean
}

export interface ConversationDetail {
  conversation: WorkbenchConversation
  messages: WorkbenchMessage[]
}

export interface CreateMessageRequest {
  text: string
  intent: WorkbenchIntent
  reference_ids: string[]
  chapter_index?: number
  target_chapter_id?: string
}

export interface AssetMutationRequest {
  title: string
  kind: WorkbenchAssetKind
  content: string
}

export interface AdoptionRequest {
  expected_version: number
  acceptance: AdoptionAcceptance
  chapter_index?: number
  target_chapter_id?: string
  expected_chapter_version?: number
}

export interface AdoptionReceipt {
  chapter_id: string
  chapter_index: number
  chapter_version: number
  asset_version: number
  review_status: string
}
