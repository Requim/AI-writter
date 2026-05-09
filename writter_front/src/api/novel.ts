import apiClient from './client'

// 类型定义
export interface NovelCreateRequest {
  novel_type: string
  title?: string
  summary?: string
  total_outline?: Record<string, any>
}

export interface NovelResponse {
  id: string
  novel_type: string
  title?: string
  summary?: string
  status: string
  progress_percentage?: number
  thread_id?: string
  total_outline?: {
    total_chapters?: number
    [key: string]: any
  }
}

export interface ProgressResponse {
  current_chapter: number
  total_chapters: number
  percentage: number
  status: string
}

export interface ChapterResponse {
  id: string
  chapter_index: number
  title: string
  word_count: number
  status: string
}

export interface WorkflowInvokeResponse {
  __interrupt__?: Array<{ value: InterruptInfo }>
  [key: string]: any
}

export interface WordCountAnalysis {
  total_count: number
  effective_density: number
  is_valid_word_count: boolean
}

export interface ReflectionIssue {
  type: string
  severity: 'low' | 'medium' | 'high'
  location: string
  description: string
  evidence?: string
  suggestion?: string
}

export interface InterruptInfo {
  action: string
  message: string
  data?: Record<string, any>
  // AI-generated content fields
  ai_suggestions?: string[]
  ai_generated_summary?: string
  ai_generated_outline?: Record<string, any>
  // Reflection fields
  issues?: ReflectionIssue[]
  chapter_number?: number
  quality_score?: number
  word_count?: number
  word_count_analysis?: WordCountAnalysis
  chapter_content_preview?: string
  revised_content_preview?: string
  // Logic chain & foreshadowing checks (from reflection)
  logic_chain_status?: string
  foreshadowing_check?: string
  // Chapter progress fields
  current_chapter?: number
  total_chapters?: number
  progress_percentage?: number
  // Outline validation
  validation?: {
    issues: string[]
    [key: string]: any
  }
  // Outline note
  note?: string
}

// Novel API
export const novelApi = {
  createNovel: (data: NovelCreateRequest) =>
    apiClient.post('/v1/novels', data),

  getNovels: () =>
    apiClient.get('/v1/novels'),

  getNovel: (novelId: string) =>
    apiClient.get(`/v1/novels/${novelId}`),

  getProgress: (novelId: string) =>
    apiClient.get(`/v1/novels/${novelId}/progress`),

  getChapters: (novelId: string) =>
    apiClient.get(`/v1/novels/${novelId}/chapters`),

  getChapter: (novelId: string, chapterId: string) =>
    apiClient.get(`/v1/novels/${novelId}/chapters/${chapterId}`),

  updateChapter: (novelId: string, chapterId: string, data: any) =>
    apiClient.put(`/v1/novels/${novelId}/chapters/${chapterId}`, data),

  deleteNovel: (novelId: string) =>
    apiClient.delete(`/v1/novels/${novelId}`),

  rewriteChapter: (novelId: string, chapterId: string) =>
    apiClient.post(`/v1/novels/${novelId}/chapters/${chapterId}/rewrite`),

  batchDeleteChapters: (novelId: string, chapterIds: string[]) =>
    apiClient.post(`/v1/novels/${novelId}/chapters/batch-delete`, { chapter_ids: chapterIds }),
}

// Workflow API
export const workflowApi = {
  invokeWorkflow: (threadId: string, data?: any) =>
    apiClient.post(`/v1/workflows/${threadId}/invoke`, data),

  getWorkflowState: (threadId: string) =>
    apiClient.get(`/v1/workflows/${threadId}/state`),

  /** SSE 流式调用（返回 fetch Response，由调用方读取流） */
  streamWorkflow: (threadId: string, data?: any): Promise<Response> =>
    fetch(`/api/v1/workflows/${threadId}/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data || {}),
    }),

  streamWorkflowGet: (threadId: string) => {
    const eventSource = new EventSource(
      `${window.location.origin}/api/v1/workflows/${threadId}/stream`
    )
    return eventSource
  }
}
