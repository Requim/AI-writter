export type JsonPrimitive = string | number | boolean | null
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue }

export interface CreativeBrief {
  core_premise?: string
  protagonist_drive?: string
  core_conflict?: string
  theme_question?: string
  reader_promise?: string
  tone?: string
  originality_anchor?: string
  content_boundaries?: string | string[]
  setting_context?: {
    era?: string
    region?: string
  }
  naming_preference?: string
  style_fingerprint?: JsonValue
  trope_contract?: JsonValue
}

export interface CharacterNameCandidate {
  candidate_id: string
  name: string
  surname: string
  given_name: string
  source_id: string
  source_title: string
  source_quote: string
  meaning: string
  pinyin?: string
  role_fit?: string
}

export interface CharacterDesignRole {
  character_id: string
  role_type: string
  profile: Record<string, JsonValue>
  name_candidates: CharacterNameCandidate[]
  recommended_candidate_id: string
}

export interface ResolvedCharacter {
  character_id: string
  name: string
  role_type: string
  profile: Record<string, JsonValue>
  name_origin: JsonValue
}

export interface CharacterDesignProposal {
  naming_policy: Record<string, JsonValue>
  core_roles: CharacterDesignRole[]
  supporting_characters: ResolvedCharacter[]
  relationships: JsonValue[]
  reserved_names?: ResolvedCharacter[]
}

export interface CharacterDesignSelection {
  name_selections?: Record<string, string>
  custom_names?: Record<string, string>
}

export interface TitleSuggestion {
  title: string
  hint?: string
  category?: string
  total_score?: number
}

export interface NovelOutline {
  story_background?: string
  main_characters?: Array<Record<string, JsonValue>>
  main_plot?: Record<string, JsonValue>
  chapters?: Array<Record<string, JsonValue>>
  writing_style?: string
  total_chapters?: number
  creative_brief?: CreativeBrief
  prompt_version?: string
}

export interface NovelCreateRequest {
  novel_type: string
  title?: string
  summary?: string
  total_outline?: NovelOutline
}

export interface NovelResponse {
  id: string
  novel_type: string
  title?: string
  summary?: string
  status: 'draft' | 'writing' | 'completed' | string
  progress_percentage?: number
  thread_id?: string
  total_outline?: NovelOutline
}

export interface ProgressResponse {
  current_chapter: number
  total_chapters: number
  percentage: number
  status: string
}

export type ChapterReviewStatus =
  | 'passed'
  | 'accepted_with_issues'
  | 'accepted_unreviewed'
  | 'unknown'

export interface ChapterSummary {
  id: string
  chapter_index: number
  title: string
  word_count: number
  status: string
  version: number
  review_status: ChapterReviewStatus
  quality_score: number | null
}

export interface ChapterDetail extends ChapterSummary {
  content: string
  updated_at: string
  checkpoint_status?: 'synced' | 'not_found' | 'deferred'
}

export interface ReflectionIssue {
  issue_id?: string
  type?: string
  severity?: 'low' | 'medium' | 'high'
  location?: string
  description?: string
  suggestion?: string
  evidence?: string
  evidence_valid?: boolean
  priority_action?: 'must_fix' | 'optional' | 'can_ignore'
}

export type WorkflowEventType =
  | 'status'
  | 'reasoning'
  | 'content_delta'
  | 'chapter_persisted'
  | 'metadata_updated'
  | 'quality'
  | 'interrupt'
  | 'progress'
  | 'completed'
  | 'heartbeat'
  | 'error'

export interface WorkflowEvent {
  id: number
  type: WorkflowEventType
  thread_id: string
  command_id?: string
  node?: string
  data: Record<string, unknown>
  timestamp: string
}

export interface PendingProposal {
  proposal_id: string
  kind: string
  version: number
  payload: JsonValue
  chapter_number?: number
  prompt_version?: string
}

export type ReviewDecision =
  | { proposal_id: string; decision: 'accept' }
  | { proposal_id: string; decision: 'regenerate'; feedback?: string }
  | { proposal_id: string; decision: 'revise'; instruction: string }
  | { proposal_id: string; decision: 'replace'; value: JsonValue }

export type ReviewInterruptAction =
  | 'review_or_modify_creative_brief'
  | 'review_or_modify_character_design'
  | 'confirm_or_provide_title'
  | 'confirm_or_provide_summary'
  | 'review_or_modify_outline'
  | 'review_or_provide_chapter_outline'
  | 'review_reflection_issues'
  | 'quality_gate_exhausted'
  | 'quality_gate_human_review'
  | 'quality_review_unavailable'
  | 'summary_review_required'
  | 'confirm_revision'

export type SystemInterruptAction = 'require_novel_type' | 'ready_for_next_chapter'

interface InterruptBase {
  message?: string
  chapter_number?: number
  proposal?: PendingProposal
  proposal_id?: string
  proposal_version?: number
  proposal_kind?: string
  prompt_version?: string
  quality_score?: number
  ai_suggestions?: Array<string | TitleSuggestion>
  ai_generated_summary?: string
  ai_generated_outline?: Record<string, JsonValue>
  ai_generated_creative_brief?: CreativeBrief
  ai_generated_character_design?: CharacterDesignProposal
  issues?: ReflectionIssue[]
  [key: string]: unknown
}

export interface ReviewInterruptInfo extends InterruptBase {
  action: ReviewInterruptAction
}

export interface SystemInterruptInfo extends InterruptBase {
  action: SystemInterruptAction
}

export interface LegacyInterruptInfo extends InterruptBase {
  action: string & {}
}

export type InterruptInfo = ReviewInterruptInfo | SystemInterruptInfo | LegacyInterruptInfo

export interface WorkflowExecutionSnapshot {
  status?: 'running' | 'cancelling' | 'completed' | 'cancelled' | 'idle' | string
  active_node?: string
  command_id?: string
  message?: string
  started_at?: string
  stage_started_at?: string
  stage_elapsed_seconds?: number
  last_activity_at?: string
  is_stale?: boolean
}

export interface WorkflowSnapshot {
  thread_id: string
  status: 'running' | 'paused' | 'idle' | 'unknown'
  is_completed?: boolean
  has_interrupt: boolean
  interrupts: InterruptInfo[]
  next_nodes?: string[]
  execution?: WorkflowExecutionSnapshot
  server_time?: string
  state: Record<string, unknown>
}
