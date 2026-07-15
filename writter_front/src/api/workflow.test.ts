import { afterEach, describe, expect, it, vi } from 'vitest'
import { parseSseStream, streamWorkflow } from './workflow'
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

describe('parseSseStream', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    useAuthStore.getState().clear()
  })
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
    await parseSseStream(responseFrom([payload.slice(0, 17), payload.slice(17, 49), payload.slice(49)]), (item) => received.push(item))
    expect(received).toEqual([event])
  })

  it('sends bearer and tenant context with the SSE request', async () => {
    useAuthStore.setState({
      accessToken: 'access-token',
      currentTenantId: 'tenant-id',
    })
    const fetchMock = vi.fn().mockResolvedValue(responseFrom([]))
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
