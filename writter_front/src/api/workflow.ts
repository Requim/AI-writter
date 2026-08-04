import type { WorkflowEvent } from '@/types/novel'
import { useAuthStore } from '@/stores/authStore'
import { redirectToLogin, refreshSession } from './session'

export interface WorkflowRequest {
  input?: Record<string, unknown>
  command?: Record<string, unknown>
}

function workflowHeaders(idempotencyKey?: string): HeadersInit {
  const { accessToken, currentTenantId } = useAuthStore.getState()
  return {
    'Content-Type': 'application/json',
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    ...(currentTenantId ? { 'X-Tenant-ID': currentTenantId } : {}),
    ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}),
  }
}

function postWorkflow(
  threadId: string,
  body: string,
  signal?: AbortSignal,
  idempotencyKey?: string,
): Promise<Response> {
  return fetch(`/api/v1/workflows/${threadId}/stream`, {
    method: 'POST',
    headers: workflowHeaders(idempotencyKey),
    body,
    signal,
  })
}

export class WorkflowRequestError extends Error {
  readonly status: number
  readonly code?: string
  readonly node?: string
  readonly retryable?: boolean
  readonly retryAfter?: number
  readonly retryCount?: number

  constructor(
    message: string,
    status: number,
    details: string | {
      code?: string
      node?: string
      retryable?: boolean
      retryAfter?: number
      retryCount?: number
    } = {},
  ) {
    super(message)
    this.name = 'WorkflowRequestError'
    this.status = status
    Object.assign(this, typeof details === 'string' ? { code: details } : details)
  }
}

function numeric(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function responseError(response: Response, raw: string): WorkflowRequestError {
  let detail: unknown = raw
  try {
    const payload = JSON.parse(raw) as { detail?: unknown }
    detail = payload.detail ?? payload
  } catch {
    // Non-JSON upstream responses are presented as plain text.
  }
  if (detail && typeof detail === 'object') {
    const value = detail as Record<string, unknown>
    const message = typeof value.message === 'string' ? value.message : `请求失败（HTTP ${response.status}）`
    return new WorkflowRequestError(
      message,
      response.status,
      {
        code: typeof value.code === 'string' ? value.code : undefined,
        node: typeof value.node === 'string' ? value.node : undefined,
        retryable: typeof value.retryable === 'boolean' ? value.retryable : undefined,
        retryAfter: numeric(value.retry_after),
        retryCount: numeric(value.retry_count ?? value.attempt),
      },
    )
  }
  return new WorkflowRequestError(
    typeof detail === 'string' && detail.trim() ? detail : `请求失败（HTTP ${response.status}）`,
    response.status,
  )
}

export async function parseSseStream(
  response: Response,
  onEvent: (event: WorkflowEvent) => void,
): Promise<{ terminal: boolean }> {
  if (!response.ok) {
    throw responseError(response, await response.text())
  }
  if (!response.body) throw new Error('浏览器未提供可读取的响应流')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let terminal = false
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      const dataLine = frame.split(/\r?\n/).find((line) => line.startsWith('data:'))
      if (!dataLine) continue
      const parsed: unknown = JSON.parse(dataLine.slice(5).trim())
      if (isWorkflowEvent(parsed)) {
        onEvent(parsed)
        terminal ||= ['interrupt', 'completed', 'error'].includes(parsed.type)
      }
    }
    if (done) break
  }
  return { terminal }
}

export async function streamWorkflow(
  threadId: string,
  payload: WorkflowRequest,
  onEvent: (event: WorkflowEvent) => void,
  signal?: AbortSignal,
  idempotencyKey?: string,
): Promise<{ terminal: boolean }> {
  const body = JSON.stringify(payload)
  let response = await postWorkflow(threadId, body, signal, idempotencyKey)
  if (response.status === 401) {
    try {
      await refreshSession()
      response = await postWorkflow(threadId, body, signal, idempotencyKey)
    } catch (error) {
      redirectToLogin()
      throw error
    }
  }
  if (response.status === 401) redirectToLogin()
  return parseSseStream(response, onEvent)
}

function isWorkflowEvent(value: unknown): value is WorkflowEvent {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<WorkflowEvent>
  return typeof candidate.id === 'number' && typeof candidate.type === 'string' && !!candidate.data
}
