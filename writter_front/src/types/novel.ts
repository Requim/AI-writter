export type JsonPrimitive = string | number | boolean | null
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue }

export interface NovelOutline {
  story_background?: string
  main_characters?: Array<Record<string, JsonValue>>
  main_plot?: Record<string, JsonValue>
  chapters?: Array<Record<string, JsonValue>>
  writing_style?: string
  total_chapters?: number
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
}

export interface ChapterDetail extends ChapterSummary {
  content: string
}

export interface ReflectionIssue {
  type?: string
  severity?: 'low' | 'medium' | 'high'
  location?: string
  description?: string
  suggestion?: string
}

export type WorkflowEventType =
  | 'status'
  | 'reasoning'
  | 'content_delta'
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
  ai_suggestions?: string[]
  ai_generated_summary?: string
  ai_generated_outline?: Record<string, JsonValue>
  issues?: ReflectionIssue[]
  [key: string]: unknown
}

export interface WorkflowSnapshot {
  thread_id: string
  status: 'running' | 'idle' | 'unknown'
  has_interrupt: boolean
  interrupts: InterruptInfo[]
  state: Record<string, unknown>
}
