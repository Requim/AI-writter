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
  genre_context?: GenreContext
}

export interface GenreContext {
  main_type?: string
  subgenre?: string
  reader_experience?: string
  narrative_pace?: string
}

export interface GenreOption {
  value: string
  label: string
  description?: string
}

export interface GenreProfile {
  value: string
  label: string
  description: string
  subgenres: GenreOption[]
  reader_experiences: GenreOption[]
  pace_options: GenreOption[]
  prompt_axes: Record<string, JsonValue>
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
  volumes?: Array<Record<string, JsonValue>>
  writing_style?: string
  total_chapters?: number
  scale?: ScaleContract
  creative_brief?: CreativeBrief
  prompt_version?: string
}

export type PlanningPreset = 'short' | 'medium' | 'long' | 'epic' | 'custom'

export interface PlanningConstraints {
  min_chapters: number
  max_chapters: number
  min_chapter_words: number
  max_chapter_words: number
  default_tolerance_ratio: number
  default_lock_window: number
}

export interface PlanningPresetOption {
  preset: Exclude<PlanningPreset, 'custom'>
  label: string
  target_chapters: number
  target_total_words: number
  target_volumes: number
}

export interface PlanningOptions {
  constraints: PlanningConstraints
  presets: PlanningPresetOption[]
}

export interface NovelPlanningInput {
  preset: PlanningPreset
  target_chapters: number
  target_total_words: number
}

export interface ScaleContract extends NovelPlanningInput {
  tolerance_ratio: number
  average_chapter_words: number
  target_volumes: number
  lock_window: number
}

export interface VolumePlan {
  volume_id: string
  title: string
  start_chapter: number
  end_chapter: number
  target_words: number
  opening_state: string
  midpoint_turn: string
  climax: string
  ending_state: string
  reader_promises: string[]
  setup_ids: string[]
  payoff_ids: string[]
}

export interface StoryArcEscalationPoint {
  chapter_number: number
  description?: string
  [key: string]: JsonValue | undefined
}

export interface StoryArc {
  arc_id: string
  arc_type: string
  start_chapter: number
  end_chapter: number
  goal: string
  escalation_points: StoryArcEscalationPoint[]
  resolution_condition: string
  is_core: boolean
}

export type ChapterPlanDetailLevel = 'skeleton' | 'detailed'
export type ChapterPlanStatus = 'planned' | 'locked' | 'completed' | string

export interface ChapterSlot {
  chapter_number: number
  volume_id: string
  arc_ids: string[]
  story_function: string
  must_happen: string[]
  planned_state_delta: string
  target_words: number
  setup_ids: string[]
  payoff_ids: string[]
  detail_level: ChapterPlanDetailLevel
  status: ChapterPlanStatus
}

export interface NovelPlan {
  schema_version: number
  version: number
  source: string
  scale: ScaleContract
  ending_contract: Record<string, JsonValue>
  volumes: VolumePlan[]
  arcs: StoryArc[]
  chapter_slots: ChapterSlot[]
  executions?: PlanExecution[]
  created_at: string
}

export interface PlanExecution {
  chapter_number: number
  plan_version: number
  status: string
  actual_words: number
  fulfillment: Record<string, JsonValue>
  drift_severity: 'none' | 'minor' | 'major' | string
  updated_at: string
}

export interface NovelPlanVersionSummary {
  version: number
  source: string
  trigger_chapter?: number | null
  change_summary?: string | null
  created_by_user_id?: string | null
  created_at: string
}

export type PlanReplanScope = 'future' | 'volume' | 'scale'

export interface PlanReplanRequest {
  scope: PlanReplanScope
  instruction: string
}

export interface NovelCreateRequest {
  novel_type: string
  title?: string
  summary?: string
  total_outline?: NovelOutline
  planning: NovelPlanningInput
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
  chapter_progress?: {
    current: number
    total: number
    percentage: number
  }
  word_progress?: {
    current: number
    target: number
    percentage: number
  }
  volume_progress?: {
    current: number
    total: number
    percentage: number
  }
  plan_version?: number
  plan_status?: 'missing' | 'draft' | 'accepted' | string
  drift_severity?: 'none' | 'minor' | 'major' | string
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
  | 'review_or_modify_novel_plan'
  | 'review_novel_plan'
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
