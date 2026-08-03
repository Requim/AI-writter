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

export interface ChapterSummary {
  id: string
  chapter_index: number
  title: string
  word_count: number
  status: string
  version: number
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
  node?: string
  data: Record<string, unknown>
  timestamp: string
}

export interface InterruptInfo {
  action: string
  message?: string
  chapter_number?: number
  quality_score?: number
  ai_suggestions?: Array<string | TitleSuggestion>
  ai_generated_summary?: string
  ai_generated_outline?: Record<string, JsonValue>
  ai_generated_creative_brief?: CreativeBrief
  issues?: ReflectionIssue[]
  [key: string]: unknown
}

export interface WorkflowExecutionSnapshot {
  status?: 'running' | 'cancelling' | 'completed' | 'cancelled' | 'idle' | string
  active_node?: string
  message?: string
  started_at?: string
  last_activity_at?: string
  is_stale?: boolean
}

export interface WorkflowSnapshot {
  thread_id: string
  status: 'running' | 'paused' | 'idle' | 'unknown'
  has_interrupt: boolean
  interrupts: InterruptInfo[]
  next_nodes?: string[]
  execution?: WorkflowExecutionSnapshot
  server_time?: string
  state: Record<string, unknown>
}
