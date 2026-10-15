import axios from 'axios'
import { apiClient } from './client'
import { createIdempotencyKey } from './idempotency'
import { isSessionInvalid, redirectToLogin, refreshSession } from './session'
import { useAuthStore } from '@/stores/authStore'
import type {
  AdoptionReceipt,
  AdoptionRequest,
  AssetMutationRequest,
  ConversationDetail,
  CreateMessageRequest,
  WorkbenchAsset,
  WorkbenchConversation,
  WorkbenchJob,
  WorkbenchOverview,
  WorkbenchSearchResponse,
} from '@/types/workbench'

async function data<T>(request: Promise<{ data: T }>): Promise<T> {
  return (await request).data
}

function path(novelId: string): string {
  return `/v1/novels/${novelId}/workbench`
}

export class WorkbenchRequestError extends Error {
  readonly status: number
  readonly code?: string

  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'WorkbenchRequestError'
    this.status = status
    this.code = code
  }
}

export function workbenchErrorMessage(error: unknown): string {
  if (error instanceof WorkbenchRequestError) return error.message
  if (axios.isAxiosError(error)) {
    const body = error.response?.data as { code?: string; message?: string; detail?: string | { message?: string } } | undefined
    if (body?.message) return body.message
    if (typeof body?.detail === 'string') return body.detail
    if (body?.detail && typeof body.detail === 'object' && body.detail.message) return body.detail.message
    if (error.response?.status === 409) return '内容已被其他操作更新，请刷新后再试'
  }
  return '请求失败，请稍后重试'
}

export const workbenchApi = {
  overview: (novelId: string, signal?: AbortSignal) =>
    data<WorkbenchOverview>(apiClient.get(`${path(novelId)}/overview`, { signal })),
  createConversation: (novelId: string, payload: { title?: string }) =>
    data<WorkbenchConversation>(apiClient.post(`${path(novelId)}/conversations`, payload)),
  conversation: (novelId: string, conversationId: string, signal?: AbortSignal) =>
    data<ConversationDetail>(apiClient.get(`${path(novelId)}/conversations/${conversationId}`, { signal })),
  renameConversation: (novelId: string, conversationId: string, title: string) =>
    data<WorkbenchConversation>(apiClient.patch(`${path(novelId)}/conversations/${conversationId}`, { title })),
  createMessage: (
    novelId: string,
    conversationId: string,
    payload: CreateMessageRequest,
    idempotencyKey = createIdempotencyKey(),
  ) => data<WorkbenchJob>(apiClient.post(`${path(novelId)}/conversations/${conversationId}/messages`, payload, {
    headers: { 'Idempotency-Key': idempotencyKey },
  })),
  job: (novelId: string, jobId: string, signal?: AbortSignal) =>
    data<WorkbenchJob>(apiClient.get(`${path(novelId)}/jobs/${jobId}`, { signal })),
  stopJob: (novelId: string, jobId: string) =>
    data<WorkbenchJob>(apiClient.post(`${path(novelId)}/jobs/${jobId}/stop`)),
  retryJob: (novelId: string, jobId: string, idempotencyKey = createIdempotencyKey()) =>
    data<WorkbenchJob>(apiClient.post(`${path(novelId)}/jobs/${jobId}/retry`, undefined, {
      headers: { 'Idempotency-Key': idempotencyKey },
    })),
  streamJob: streamWorkbenchJob,
  createAsset: (novelId: string, payload: AssetMutationRequest & { source_message_id?: string }) =>
    data<WorkbenchAsset>(apiClient.post(`${path(novelId)}/assets`, payload)),
  updateAsset: (novelId: string, assetId: string, payload: AssetMutationRequest & { expected_version: number }) =>
    data<WorkbenchAsset>(apiClient.patch(`${path(novelId)}/assets/${assetId}`, payload)),
  assetVersions: (novelId: string, assetId: string) =>
    data<WorkbenchAsset[]>(apiClient.get(`${path(novelId)}/assets/${assetId}/versions`)),
  copyAsset: (novelId: string, assetId: string, payload: { target_novel_id: string; expected_version: number }) =>
    data<WorkbenchAsset>(apiClient.post(`${path(novelId)}/assets/${assetId}/copy`, payload)),
  reviewAsset: (novelId: string, assetId: string, expectedVersion: number) =>
    data<WorkbenchAsset>(apiClient.post(`${path(novelId)}/assets/${assetId}/review`, { expected_version: expectedVersion }, { timeout: 600_000 })),
  adoptAsset: (novelId: string, assetId: string, payload: AdoptionRequest) =>
    data<AdoptionReceipt>(apiClient.post(`${path(novelId)}/assets/${assetId}/adopt`, payload, { timeout: 600_000 })),
  search: (novelId: string, query: string, beforeChapter?: number) =>
    data<WorkbenchSearchResponse>(apiClient.get(`${path(novelId)}/search`, {
      params: { q: query, ...(beforeChapter == null ? {} : { before_chapter: beforeChapter }) },
    })),
  reindex: (novelId: string) => data<{ assets: number; chapters: number }>(apiClient.post(`${path(novelId)}/reindex`)),
}

function streamHeaders(): HeadersInit {
  const { accessToken, currentTenantId } = useAuthStore.getState()
  return {
    Accept: 'text/event-stream',
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    ...(currentTenantId ? { 'X-Tenant-ID': currentTenantId } : {}),
  }
}

function streamRequest(novelId: string, jobId: string, signal?: AbortSignal): Promise<Response> {
  return fetch(`/api${path(novelId)}/jobs/${jobId}/stream`, {
    method: 'GET', headers: streamHeaders(), signal,
  })
}

function streamError(response: Response, raw: string): WorkbenchRequestError {
  let message = `任务流读取失败（HTTP ${response.status}）`
  let code: string | undefined
  try {
    const body = JSON.parse(raw) as { code?: string; message?: string; detail?: { code?: string; message?: string } }
    code = body.code || body.detail?.code
    message = body.message || body.detail?.message || message
  } catch {
    // Plain gateway text is intentionally hidden from the author-facing error.
  }
  return new WorkbenchRequestError(message, response.status, code)
}

export async function parseJobSnapshots(
  response: Response,
  onSnapshot: (job: WorkbenchJob) => void,
): Promise<WorkbenchJob | undefined> {
  if (!response.ok) throw streamError(response, await response.text())
  if (!response.body) return undefined
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let latest: WorkbenchJob | undefined
  const consume = (frame: string) => {
    const raw = frame.split(/\r?\n/).filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart()).join('\n')
    if (!raw) return
    latest = JSON.parse(raw) as WorkbenchJob
    onSnapshot(latest)
  }
  for (;;) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() || ''
    frames.forEach(consume)
    if (done) { consume(buffer); break }
  }
  return latest
}

export async function streamWorkbenchJob(
  novelId: string,
  jobId: string,
  onSnapshot: (job: WorkbenchJob) => void,
  signal?: AbortSignal,
): Promise<WorkbenchJob | undefined> {
  let response = await streamRequest(novelId, jobId, signal)
  if (response.status === 401) {
    try {
      await refreshSession()
      response = await streamRequest(novelId, jobId, signal)
    } catch (error) {
      if (isSessionInvalid(error)) redirectToLogin()
      throw error
    }
  }
  return parseJobSnapshots(response, onSnapshot)
}
