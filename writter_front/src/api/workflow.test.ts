import { afterEach, describe, expect, it, vi } from 'vitest'
import axios from 'axios'
import { orderedEvents, parseSseStream, streamWorkflow, WorkflowRequestError } from './workflow'
import type { WorkflowEvent } from '@/types/novel'
import { useAuthStore } from '@/stores/authStore'

function responseFrom(parts: string[]): Response {
  const encoder = new TextEncoder()
  return new Response(new ReadableStream({
    start(controller) {
      parts.forEach((part) => controller.enqueue(encoder.encode(part)))
      controller.close()
    },
  }))
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  useAuthStore.getState().clear()
})

describe('parseSseStream', () => {
  it('parses events split across transport chunks', async () => {
    const event: WorkflowEvent = {
      id: 1,
      type: 'content_delta',
      thread_id: 'thread-1',
      node: 'chapter_writer_node',
      data: { operation: 'append', text: '第一句。' },
      timestamp: '2026-07-15T00:00:00Z',
    }
    const payload = `id: 1\nevent: content_delta\ndata: ${JSON.stringify(event)}\n\n`
    const received: WorkflowEvent[] = []
    const result = await parseSseStream(responseFrom([payload.slice(0, 17), payload.slice(17, 49), payload.slice(49)]), (item) => received.push(item))
    expect(received).toEqual([event])
    expect(result.terminal).toBe(false)
  })

  it('recognizes an interrupt as a normal terminal event', async () => {
    const event: WorkflowEvent = {
      id: 2, type: 'interrupt', thread_id: 'thread-1', data: { interrupts: [] },
      timestamp: '2026-07-15T00:00:01Z',
    }
    const payload = `event: interrupt\ndata: ${JSON.stringify(event)}\n\n`
    const result = await parseSseStream(responseFrom([payload]), () => undefined)
    expect(result.terminal).toBe(true)
  })

  it('sends bearer and tenant context with the SSE request', async () => {
    useAuthStore.setState({
      accessToken: 'access-token',
      currentTenantId: 'tenant-id',
    })
    const fetchMock = vi.fn().mockImplementation(async () => responseFrom([]))
    vi.stubGlobal('fetch', fetchMock)
    await streamWorkflow('novel-id', { input: {} }, () => undefined)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/workflows/novel-id/stream',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer access-token',
          'X-Tenant-ID': 'tenant-id',
        }),
      }),
    )
  })
})

describe('durable replay', () => {
  it('deduplicates replay and detects missing sequence', () => {
    const receive = vi.fn()
    const ordered = orderedEvents(receive)
    const event = { id: 10, type: 'status', thread_id: 'n', data: {}, timestamp: '2026-09-07T00:00:00Z' } as WorkflowEvent
    ordered.receive(event)
    ordered.receive(event)
    expect(receive).toHaveBeenCalledTimes(1)
    expect(() => ordered.receive({ ...event, id: 12 })).toThrow('缺口')
    expect(ordered.cursor()).toBe(10)
  })
  it('reconnects with GET and Last-Event-ID without another command', async () => {
    const event = { id: 7, type: 'status', thread_id: 'n', data: {}, timestamp: '2026-09-07T00:00:00Z' }
    const fetchMock = vi.fn().mockResolvedValueOnce(responseFrom([`data: ${JSON.stringify(event)}\n\n`]))
      .mockResolvedValueOnce(responseFrom([`data: ${JSON.stringify({ ...event, id: 8, type: 'completed' })}\n\n`]))
    vi.stubGlobal('fetch', fetchMock)
    const result = await streamWorkflow('n', { input: {} }, () => undefined)
    expect(result.terminal).toBe(true)
    expect(fetchMock.mock.calls[1]).toEqual(['/api/v1/workflows/n/events', expect.objectContaining({ headers: expect.objectContaining({ 'Last-Event-ID': '7' }) })])
    expect(fetchMock.mock.calls.filter(call => call[1].method === 'POST')).toHaveLength(1)
  })
})

describe('workflow request recovery', () => {
  it('extracts a readable FastAPI detail instead of exposing raw JSON', async () => {
    const response = new Response(JSON.stringify({
      detail: {
        code: 'workflow_already_running',
        message: '该作品已有创作任务，请查看当前阶段或先结束任务',
      },
    }), { status: 409, headers: { 'Content-Type': 'application/json' } })

    const error = await parseSseStream(response, () => undefined).catch((reason: unknown) => reason)
    expect(error).toBeInstanceOf(WorkflowRequestError)
    expect(error).toMatchObject({
      status: 409,
      code: 'workflow_already_running',
      message: '该作品已有创作任务，请查看当前阶段或先结束任务',
    })
  })

  it('refreshes once after 401 and replays with the same idempotency key', async () => {
    useAuthStore.setState({ accessToken: 'expired', refreshToken: 'refresh', currentTenantId: 'tenant-id' })
    vi.spyOn(axios, 'post').mockResolvedValue({ data: {
      access_token: 'fresh', refresh_token: 'next-refresh', token_type: 'bearer', expires_in: 3600,
      user: { id: 'user-1', email: 'writer@example.com', is_platform_admin: false, status: 'active' },
      tenants: [{ id: 'tenant-id', name: '编辑部', slug: 'desk', role: 'owner', status: 'active', ai_enabled: true, monthly_generation_limit: 30, monthly_generation_unlimited: false }],
    } })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('', { status: 401 }))
      .mockResolvedValueOnce(responseFrom([]))
      .mockResolvedValueOnce(responseFrom([]))
    vi.stubGlobal('fetch', fetchMock)
    await streamWorkflow('novel-id', { command: { retry: true } }, () => undefined, undefined, 'command-7')
    const firstHeaders = fetchMock.mock.calls[0][1].headers
    const secondHeaders = fetchMock.mock.calls[1][1].headers
    expect(firstHeaders['Idempotency-Key']).toBe('command-7')
    expect(secondHeaders['Idempotency-Key']).toBe('command-7')
    expect(secondHeaders.Authorization).toBe('Bearer fresh')
  })
})
