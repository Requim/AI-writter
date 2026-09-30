import { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { apiClient } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import type { AuthorConfiguration } from '@/types/creative'
import type { ChapterDetail, GenreProfile, NovelResponse } from '@/types/novel'

export const previewNovelId = '00000000-0000-0000-0000-000000000001'
const chapterTitles = ['没有寄件人的信', '雨夜来客', '交接记录', '消失的第七页', '凌晨两点的电话']
const manuscript = `许知衡抵达码头时，雨已经停了。

值班室的灯还亮着。窗台上搁着半杯凉透的茶，门后挂着一件没有干透的雨衣。他没有碰那杯茶，只把带来的交接记录平铺在桌上。

“你看过这本记录？”

老周没有回答，先去关了门。锁舌落下的声音很轻，在空荡的值班室里却格外清楚。

许知衡翻到第六页。下一页的页码是八。断口有一小段纸纤维，压在装订线下面，像是有人撕到一半，又停下来用刀割断了。

“每次交班都要签字，”老周说，“三个人，一人一个格子。”

“那天也是三个人？”

老周盯着桌角。那里有一道新磕出来的印子，颜色比周围的木头浅。他伸出手指碰了一下，又缩了回去。

许知衡合上记录，没有追问。他来之前给码头打过电话，接电话的人说，那晚只有两个人值班。

窗外传来一声汽笛。老周终于抬起头，却没有看他。

“你找的不是那一页。”`;

function chapters(): ChapterDetail[] {
  return chapterTitles.map((title, index) => ({
    id: `preview-chapter-${index + 1}`, title, chapter_index: index, content: manuscript,
    word_count: [...manuscript].length, version: 1, status: 'completed', review_status: 'passed',
    quality_score: 0.82, updated_at: '2026-09-09T08:30:00Z',
  }))
}

const genres: GenreProfile[] = [
  ['suspense', '悬疑推理'], ['urban', '都市生活'], ['fantasy', '玄幻奇幻'],
].map(([value, label]) => ({
  value, label, description: label,
  subgenres: [{ value: 'urban_mystery', label: '都市悬疑' }],
  reader_experiences: [{ value: 'truth', label: '追索真相' }],
  pace_options: [{ value: 'balanced', label: '张弛有度' }], prompt_axes: {},
}))

function previewBooks(config: AuthorConfiguration): NovelResponse[] {
  return [
    { id: previewNovelId, title: '第七码头', novel_type: 'suspense', status: 'writing', progress_percentage: 25,
      summary: '一份被撕去的交接记录，将一场普通失踪案引向七年前的雨夜。',
      thread_id: 'preview-thread', total_outline: { total_chapters: 20, author_config: config } },
    { id: 'preview-book-2', title: '长街来信', novel_type: 'urban', status: 'draft', progress_percentage: 0,
      summary: '旧城区改造前，邮递员发现一袋从未送出的信。', total_outline: { total_chapters: 12 } },
    { id: 'preview-book-3', title: '山海有归期', novel_type: 'fantasy', status: 'completed', progress_percentage: 100,
      summary: '失去名字的旅人，沿着一张残缺的地图寻找故乡。', total_outline: { total_chapters: 5 } },
  ]
}

function staticResponses() {
  return {
    '/v1/novels/genre-taxonomy': genres,
    '/v1/novels/planning-options': {
      constraints: { min_chapters: 1, max_chapters: 200, min_chapter_words: 3000, max_chapter_words: 7000, default_tolerance_ratio: 0.1, default_lock_window: 5 },
      presets: [{ preset: 'short', label: '短篇', target_chapters: 12, target_total_words: 50400, target_volumes: 1 }],
    },
    '/v1/novels/creative-options': { global_enabled: true, tenant_enabled: true, enabled: true, request_limit: 10000 },
    '/v1/tenants/current/usage': { used: 152, limit: 1000, remaining: 848, unlimited: false, ai_enabled: true, period_start: '2026-09-01' },
    '/v1/tenants/current/members': [{ user_id: 'preview-user', email: 'writer@example.test', role: 'owner', status: 'active', joined_at: '2026-09-01' }],
    '/v1/admin/tenants': [], '/v1/admin/users': [],
  } as Record<string, unknown>
}

function bookResponse(book: NovelResponse, suffix: string, drafts: ChapterDetail[]) {
  const available = book.status === 'draft' ? [] : drafts
  const total = book.total_outline?.total_chapters || 20
  if (!suffix) return book
  if (suffix === '/progress') return { current_chapter: available.length, total_chapters: total,
    percentage: book.progress_percentage, status: book.status,
    word_progress: { current: available.reduce((sum, ch) => sum + ch.word_count, 0), target: total * 4200, percentage: 3 } }
  if (suffix === '/chapters') return available
  if (suffix.startsWith('/chapters/')) return available.find((ch) => ch.id === suffix.split('/')[2])
  if (suffix === '/plan') return null
  if (suffix === '/tactical-plan') return { plan: null, version: null }
  if (suffix.endsWith('/versions') || suffix.endsWith('/conflicts')) return []
  if (suffix.endsWith('/facts')) return { entities: [], fact_heads: [] }
  return undefined
}

function fixtureAdapter(books: NovelResponse[], drafts: ChapterDetail[]) {
  const fixed = staticResponses()
  return async (request: InternalAxiosRequestConfig) => {
    const path = request.url || ''
    let data: unknown
    if (request.method === 'get') {
      data = fixed[path]
      if (path === '/v1/novels') data = books
      if (path.startsWith('/v1/workflows/')) data = { thread_id: 'preview-thread', status: 'idle',
        has_interrupt: false, interrupts: [], state: { current_chapter: 5 }, next_nodes: [] }
      const match = path.match(/^\/v1\/novels\/([^/]+)(.*)$/)
      const book = books.find((item) => item.id === match?.[1])
      if (book && match) data = bookResponse(book, match[2], drafts)
    }
    if (request.method === 'put' && path.includes('/chapters/')) {
      const chapter = drafts.find((item) => path.endsWith(`/${item.id}`))
      if (chapter) data = Object.assign(chapter, JSON.parse(request.data), { version: chapter.version + 1 })
    }
    if (request.method === 'delete' && books.some((item) => path === `/v1/novels/${item.id}`)) {
      books.splice(books.findIndex((item) => path === `/v1/novels/${item.id}`), 1)
      data = { status: 'deleted' }
    }
    if (data === undefined) throw new AxiosError('界面预览不连接真实服务，此操作未提供模拟结果', 'PREVIEW_ONLY', request)
    return { data: structuredClone(data), status: 200, statusText: 'OK', headers: {}, config: request }
  }
}

/** 仅开发入口调用；认证状态改为内存存储，禁止覆盖本机真实登录信息。 */
export function installWorkbenchFixtures(config: AuthorConfiguration) {
  if (!import.meta.env.DEV) return
  useAuthStore.persist.setOptions({ storage: { getItem: () => null, setItem: () => {}, removeItem: () => {} } })
  useAuthStore.setState({
    accessToken: undefined, refreshToken: undefined, currentTenantId: 'preview-tenant',
    user: { id: 'preview-user', email: 'writer@example.test', is_platform_admin: false, status: 'active' },
    tenants: [{ id: 'preview-tenant', name: '我的编辑部', slug: 'preview', role: 'owner', status: 'active',
      ai_enabled: true, monthly_generation_limit: 1000, monthly_generation_unlimited: false,
      novel_planning_v1_enabled: true, novel_planning_v1_effective: true }],
  })
  apiClient.defaults.adapter = fixtureAdapter(previewBooks(config), chapters())
  const fetch = window.fetch.bind(window)
  window.fetch = (input, init) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    if (new URL(url, location.href).pathname.startsWith('/api/')) {
      return Promise.resolve(Response.json({ detail: '界面预览不启动模型任务' }, { status: 503 }))
    }
    return fetch(input, init)
  }
}
