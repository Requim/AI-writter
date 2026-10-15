import axios from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from './client'
import { parseJobSnapshots, streamWorkbenchJob, workbenchApi } from './workbench'
import { useAuthStore } from '@/stores/authStore'
import type { WorkbenchJob } from '@/types/workbench'

function job(status: string, content = ''): WorkbenchJob {
  return {
    id: 'job-1', conversation_id: 'conversation-1', message_id: 'message-1',
    status, content, error: null, sources: [], intent: 'discuss',
    chapter_index: null, target_chapter_id: null,
    created_at: '2026-10-13T08:00:00Z', updated_at: '2026-10-13T08:00:00Z',
  }
}

function streamed(parts: string[], status = 200): Response {
  const encoder = new TextEncoder()
  return new Response(new ReadableStream({
    start(controller) {
      parts.forEach((part) => controller.enqueue(encoder.encode(part)))
      controller.close()
    },
  }), { status })
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  useAuthStore.getState().clear()
})

describe('workbench job snapshots', () => {
  it('parses snapshot frames split across transport chunks', async () => {
    const running = job('running', '第一段')
    const completed = job('completed', '第一段\n\n第二段')
    const payload = `event: snapshot\ndata: ${JSON.stringify(running)}\n\nevent: snapshot\ndata: ${JSON.stringify(completed)}\n\n`
    const received: WorkbenchJob[] = []

    const latest = await parseJobSnapshots(
      streamed([payload.slice(0, 31), payload.slice(31, 109), payload.slice(109)]),
      (snapshot) => received.push(snapshot),
    )

    expect(received).toEqual([running, completed])
    expect(latest).toEqual(completed)
  })

  it('keeps the final snapshot when the stream closes without a blank delimiter', async () => {
    const completed = job('completed', '最终内容')
    const received: WorkbenchJob[] = []

    const latest = await parseJobSnapshots(
      streamed([`event: snapshot\ndata: ${JSON.stringify(completed)}`]),
      (snapshot) => received.push(snapshot),
    )

    expect(received).toEqual([completed])
    expect(latest).toEqual(completed)
  })

  it('refreshes authentication and resumes the same persisted job stream', async () => {
    useAuthStore.setState({ accessToken: 'expired', refreshToken: 'refresh', currentTenantId: 'tenant-1' })
    vi.spyOn(axios, 'post').mockResolvedValue({ data: {
      access_token: 'fresh', refresh_token: 'next', token_type: 'bearer', expires_in: 3600,
      user: { id: 'user-1', email: 'writer@example.test', is_platform_admin: false, status: 'active' },
      tenants: [{ id: 'tenant-1', name: '编辑部', slug: 'desk', role: 'owner', status: 'active', ai_enabled: true, monthly_generation_limit: 30, monthly_generation_unlimited: false }],
    } })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('', { status: 401 }))
      .mockResolvedValueOnce(streamed([`event: snapshot\ndata: ${JSON.stringify(job('completed'))}\n\n`]))
    vi.stubGlobal('fetch', fetchMock)

    await streamWorkbenchJob('novel-1', 'job-1', () => undefined)

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/novels/novel-1/workbench/jobs/job-1/stream')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/novels/novel-1/workbench/jobs/job-1/stream')
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({
      method: 'GET', headers: expect.objectContaining({
        Authorization: 'Bearer fresh', 'X-Tenant-ID': 'tenant-1',
      }),
    }))
  })
})

describe('workbench commands', () => {
  it('uses an idempotency key when creating a paid message job', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: job('queued') })

    await workbenchApi.createMessage('novel-1', 'conversation-1', {
      text: '推演这一幕', intent: 'discuss', reference_ids: ['asset-1'],
    }, 'command-1')

    expect(post).toHaveBeenCalledWith(
      '/v1/novels/novel-1/workbench/conversations/conversation-1/messages',
      { text: '推演这一幕', intent: 'discuss', reference_ids: ['asset-1'] },
      { headers: { 'Idempotency-Key': 'command-1' } },
    )
  })
})
