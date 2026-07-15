import type { WorkflowEvent } from '@/types/novel'
import { useAuthStore } from '@/stores/authStore'

export interface WorkflowRequest {
  input?: Record<string, unknown>
  command?: Record<string, unknown>
}

export class WorkflowRequestError extends Error {
  readonly status: number
  readonly code?: string

  constructor(
    message: string,
    status: number,
    code?: string,
  ) {
    super(message)
    this.name = 'WorkflowRequestError'
    this.status = status
    this.code = code
  }
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
    const value = detail as { code?: unknown; message?: unknown }
    const message = typeof value.message === 'string' ? value.message : `请求失败（HTTP ${response.status}）`
    return new WorkflowRequestError(
      message,
      response.status,
      typeof value.code === 'string' ? value.code : undefined,
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
): Promise<void> {
  if (!response.ok) {
    throw responseError(response, await response.text())
  }
  if (!response.body) throw new Error('浏览器未提供可读取的响应流')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      const dataLine = frame.split(/\r?\n/).find((line) => line.startsWith('data:'))
      if (!dataLine) continue
      const parsed: unknown = JSON.parse(dataLine.slice(5).trim())
      if (isWorkflowEvent(parsed)) onEvent(parsed)
    }
    if (done) break
  }
}

export async function streamWorkflow(
  threadId: string,
  payload: WorkflowRequest,
  onEvent: (event: WorkflowEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const { accessToken, currentTenantId } = useAuthStore.getState()
  const response = await fetch(`/api/v1/workflows/${threadId}/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...(currentTenantId ? { 'X-Tenant-ID': currentTenantId } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  })
  return parseSseStream(response, onEvent)
}

function isWorkflowEvent(value: unknown): value is WorkflowEvent {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<WorkflowEvent>
  return typeof candidate.id === 'number' && typeof candidate.type === 'string' && !!candidate.data
}
