import { apiClient } from './client'
import type {
  ChapterDetail,
  ChapterSummary,
  NovelCreateRequest,
  NovelResponse,
  ProgressResponse,
  WorkflowSnapshot,
} from '@/types/novel'

async function data<T>(request: Promise<{ data: T }>): Promise<T> {
  return (await request).data
}

export const novelApi = {
  create: (payload: NovelCreateRequest) =>
    data<{ novel_id: string; thread_id: string; status: string }>(apiClient.post('/v1/novels', payload)),
  list: () => data<NovelResponse[]>(apiClient.get('/v1/novels')),
  get: (novelId: string) => data<NovelResponse>(apiClient.get(`/v1/novels/${novelId}`)),
  progress: (novelId: string) =>
    data<ProgressResponse>(apiClient.get(`/v1/novels/${novelId}/progress`)),
  chapters: (novelId: string) =>
    data<ChapterSummary[]>(apiClient.get(`/v1/novels/${novelId}/chapters`)),
  chapter: (novelId: string, chapterId: string) =>
    data<ChapterDetail>(apiClient.get(`/v1/novels/${novelId}/chapters/${chapterId}`)),
  updateChapter: (novelId: string, chapterId: string, payload: Pick<ChapterDetail, 'title' | 'content'>) =>
    data<ChapterDetail>(apiClient.put(`/v1/novels/${novelId}/chapters/${chapterId}`, payload)),
  rewriteChapter: (novelId: string, chapterId: string) =>
    data<ChapterDetail>(apiClient.post(`/v1/novels/${novelId}/chapters/${chapterId}/rewrite`)),
  remove: (novelId: string) => data<{ status: string }>(apiClient.delete(`/v1/novels/${novelId}`)),
  batchDeleteChapters: (novelId: string, chapterIds: string[]) =>
    data<{ status: string; count: number; rewind_to: number | null }>(
      apiClient.post(`/v1/novels/${novelId}/chapters/batch-delete`, { chapter_ids: chapterIds }),
    ),
}

export const workflowApi = {
  state: (threadId: string) =>
    data<WorkflowSnapshot>(apiClient.get(`/v1/workflows/${threadId}/state`)),
  cancel: (threadId: string) =>
    data<{ thread_id: string; status: string }>(apiClient.post(`/v1/workflows/${threadId}/cancel`)),
}
