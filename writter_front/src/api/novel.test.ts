import axios, { AxiosError, type AxiosAdapter, type InternalAxiosRequestConfig } from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/authStore'
import type { AuthSession } from '@/types/auth'
import type { ChapterDetail } from '@/types/novel'
import { apiClient } from './client'
import { novelApi } from './novel'

const originalAdapter = apiClient.defaults.adapter
const chapter: ChapterDetail = {
  id: 'chapter-1', chapter_index: 0, title: '雨夜来信', content: '正文', word_count: 2,
  status: 'completed', version: 2, review_status: 'passed', quality_score: 4.6,
  updated_at: '2026-08-04T08:00:00Z',
}
const session: AuthSession = {
  access_token: 'fresh-access', refresh_token: 'fresh-refresh', token_type: 'bearer', expires_in: 3600,
  user: { id: 'user-1', email: 'writer@example.com', is_platform_admin: false, status: 'active' },
  tenants: [{ id: 'tenant-1', name: '编辑部', slug: 'desk', role: 'owner', status: 'active', ai_enabled: true, monthly_generation_limit: 30, monthly_generation_unlimited: false }],
}

afterEach(() => {
  apiClient.defaults.adapter = originalAdapter
  useAuthStore.getState().clear()
  vi.restoreAllMocks()
})

function unauthorized(config: InternalAxiosRequestConfig): AxiosError {
  return new AxiosError('unauthorized', AxiosError.ERR_BAD_REQUEST, config, undefined, {
    data: {}, status: 401, statusText: 'Unauthorized', headers: {}, config,
  })
}

describe('novelApi rewriteChapter', () => {
  it('loads genre taxonomy from the novels API namespace', async () => {
    const adapter: AxiosAdapter = vi.fn(async (request) => ({
      data: [{ value: 'horror', label: '惊悚', subgenres: [], reader_experiences: [], pace_options: [], prompt_axes: {} }],
      status: 200,
      statusText: 'OK',
      headers: {},
      config: request as InternalAxiosRequestConfig,
    }))
    apiClient.defaults.adapter = adapter

    await expect(novelApi.genreTaxonomy()).resolves.toEqual([
      { value: 'horror', label: '惊悚', subgenres: [], reader_experiences: [], pace_options: [], prompt_axes: {} },
    ])
    expect(vi.mocked(adapter).mock.calls[0][0]).toMatchObject({
      url: '/v1/novels/genre-taxonomy',
    })
  })

  it('reuses one idempotency key when a 401 response is refreshed and replayed', async () => {
    useAuthStore.setState({ accessToken: 'expired', refreshToken: 'refresh', currentTenantId: 'tenant-1' })
    vi.spyOn(axios, 'post').mockResolvedValue({ data: session })
    const keys: string[] = []
    const adapter: AxiosAdapter = vi.fn(async (request) => {
      const config = request as InternalAxiosRequestConfig
      keys.push(String(config.headers.get('Idempotency-Key')))
      if (keys.length === 1) throw unauthorized(config)
      return { data: chapter, status: 200, statusText: 'OK', headers: {}, config }
    })
    apiClient.defaults.adapter = adapter

    await expect(novelApi.rewriteChapter('novel-1', 'chapter-1')).resolves.toEqual(chapter)
    expect(keys).toHaveLength(2)
    expect(keys[0]).toMatch(/^[0-9a-f-]{36}$/)
    expect(keys[1]).toBe(keys[0])
    expect(vi.mocked(adapter).mock.calls[0][0]).toMatchObject({
      url: '/v1/novels/novel-1/chapters/chapter-1/rewrite', timeout: 600_000,
    })
  })
})
