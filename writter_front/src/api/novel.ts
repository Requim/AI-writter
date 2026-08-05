import { apiClient } from './client'
import { createIdempotencyKey } from './idempotency'
import type {
  ChapterDetail,
  ChapterSummary,
  GenreProfile,
  NovelCreateRequest,
  NovelPlan,
  NovelPlanVersionSummary,
  NovelResponse,
  PlanningOptions,
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
  genreTaxonomy: () => data<GenreProfile[]>(apiClient.get('/v1/novels/genre-taxonomy')),
  planningOptions: () => data<PlanningOptions>(apiClient.get('/v1/novels/planning-options')),
  plan: (novelId: string) => data<NovelPlan | null>(apiClient.get(`/v1/novels/${novelId}/plan`)),
  planVersions: (novelId: string) =>
    data<NovelPlanVersionSummary[]>(apiClient.get(`/v1/novels/${novelId}/plan/versions`)),
  progress: (novelId: string) =>
    data<ProgressResponse>(apiClient.get(`/v1/novels/${novelId}/progress`)),
  chapters: (novelId: string) =>
    data<ChapterSummary[]>(apiClient.get(`/v1/novels/${novelId}/chapters`)),
  chapter: (novelId: string, chapterId: string) =>
    data<ChapterDetail>(apiClient.get(`/v1/novels/${novelId}/chapters/${chapterId}`)),
  updateChapter: (
    novelId: string,
    chapterId: string,
    payload: Pick<ChapterDetail, 'title' | 'content'> & { expected_version: number },
  ) =>
    data<ChapterDetail>(apiClient.put(`/v1/novels/${novelId}/chapters/${chapterId}`, payload)),
  rewriteChapter: (novelId: string, chapterId: string) => data<ChapterDetail>(apiClient.post(
    `/v1/novels/${novelId}/chapters/${chapterId}/rewrite`,
    undefined,
    { headers: { 'Idempotency-Key': createIdempotencyKey() }, timeout: 600_000 },
  )),
  remove: (novelId: string) => data<{ status: string }>(apiClient.delete(`/v1/novels/${novelId}`)),
  batchDeleteChapters: (novelId: string, chapterIds: string[]) =>
    data<{
      status: string
      count: number
      rewind_to: number | null
      checkpoint_status: 'synced' | 'not_found' | 'deferred'
    }>(
      apiClient.post(`/v1/novels/${novelId}/chapters/batch-delete`, { chapter_ids: chapterIds }),
    ),
}

export const workflowApi = {
  state: (threadId: string) =>
    data<WorkflowSnapshot>(apiClient.get(`/v1/workflows/${threadId}/state`)),
  cancel: (threadId: string) =>
    data<{ thread_id: string; status: string }>(apiClient.post(
      `/v1/workflows/${threadId}/cancel`,
      undefined,
      { headers: { 'Idempotency-Key': createIdempotencyKey() } },
    )),
}
