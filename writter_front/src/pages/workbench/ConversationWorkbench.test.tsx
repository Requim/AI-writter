import { App, ConfigProvider } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import ConversationWorkbench from './ConversationWorkbench'

const { api, novelApi } = vi.hoisted(() => ({
  api: {
    overview: vi.fn(), createConversation: vi.fn(), conversation: vi.fn(), renameConversation: vi.fn(),
    createMessage: vi.fn(), job: vi.fn(), stopJob: vi.fn(), retryJob: vi.fn(), streamJob: vi.fn(),
    createAsset: vi.fn(), updateAsset: vi.fn(), assetVersions: vi.fn(), copyAsset: vi.fn(),
    reviewAsset: vi.fn(), adoptAsset: vi.fn(), search: vi.fn(), reindex: vi.fn(),
  },
  novelApi: { list: vi.fn() },
}))

vi.mock('@/components/AppShell', () => ({ AppShell: ({ children }: { children: ReactNode }) => children }))
vi.mock('@/api/workbench', () => ({
  workbenchApi: api,
  workbenchErrorMessage: () => '请求失败',
}))
vi.mock('@/api/novel', () => ({ novelApi }))

const conversation = { id: 'conversation-1', title: '第一幕讨论', created_at: '2026-10-13T08:00:00Z', updated_at: '2026-10-13T08:00:00Z' }
const chapterAsset = {
  id: 'asset-1', title: '车站重逢', kind: 'chapter', content: '雨夜的旧车站。', version: 2,
  source_message_id: 'message-1', provenance: null, review: {
    asset_version: 2, basis: 'basis-1', content_hash: 'hash-1',
    gate: { decision: 'pass', score: 92 },
    issues: [{ severity: 'low', description: '站台空间关系可以更清楚', suggestion: '补一处方位锚点' }],
  }, adopted_chapter_id: null,
  created_at: '2026-10-13T08:00:00Z', updated_at: '2026-10-13T08:00:00Z',
}
const completedJob = {
  id: 'job-1', conversation_id: conversation.id, message_id: 'message-1', status: 'completed', content: '**先写冲突。**',
  error: null, sources: [], intent: 'discuss', chapter_index: null, target_chapter_id: null,
  created_at: '2026-10-13T08:00:00Z', updated_at: '2026-10-13T08:01:00Z',
}

function overview() {
  return {
    enabled: true,
    novel: { id: 'novel-1', novel_type: 'suspense', title: '雾站来信', status: 'draft' },
    conversations: [conversation], assets: [chapterAsset],
    chapters: [{ id: 'chapter-1', chapter_index: 0, title: '第一章', word_count: 1200, status: 'draft', version: 3, review_status: 'passed', quality_score: 91 }],
  }
}

function mount() {
  const router = createMemoryRouter([{ path: '/novels/:novelId', element: <ConversationWorkbench /> }], {
    initialEntries: ['/novels/novel-1'],
  })
  render(<ConfigProvider theme={{ token: { motion: false } }}><App><RouterProvider router={router} /></App></ConfigProvider>)
  return router
}

const browserGetComputedStyle = window.getComputedStyle.bind(window)
beforeEach(() => { vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => browserGetComputedStyle(element)) })
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks() })

describe('conversation workbench', () => {
  it('hands advanced creation state to the original studio route', async () => {
    api.overview.mockResolvedValue(overview())
    const startInput = { novel_id: 'novel-1', novel_type: 'suspense' }
    const router = createMemoryRouter([
      { path: '/novels/:novelId', element: <ConversationWorkbench /> },
      { path: '/novels/:novelId/studio', element: <div>legacy studio target</div> },
    ], { initialEntries: [{ pathname: '/novels/novel-1', state: { startInput } }] })
    render(<ConfigProvider theme={{ token: { motion: false } }}><App><RouterProvider router={router} /></App></ConfigProvider>)

    expect(await screen.findByText('legacy studio target')).toBeInTheDocument()
    expect(router.state.location).toMatchObject({
      pathname: '/novels/novel-1/studio', state: { startInput },
    })
  })

  it('sends the selected asset as an explicit reference and restores message jobs', async () => {
    api.overview.mockResolvedValue(overview())
    api.conversation.mockResolvedValue({ conversation, messages: [{
      id: 'message-1', conversation_id: conversation.id, role: 'assistant', content: '**先写冲突。**',
      status: 'completed', intent: 'discuss', sources: [], job_id: 'job-1', created_at: '2026-10-13T08:01:00Z',
    }] })
    api.job.mockResolvedValue(completedJob)
    api.createMessage.mockResolvedValue({ ...completedJob, id: 'job-2', status: 'queued', content: '' })
    api.streamJob.mockImplementation(async (_novelId: string, _jobId: string, onSnapshot: (value: unknown) => void) => {
      const snapshot = { ...completedJob, id: 'job-2', status: 'completed', content: '继续推进。' }
      onSnapshot(snapshot)
      return snapshot
    })

    mount()

    expect(await screen.findByRole('heading', { name: '雾站来信' })).toBeInTheDocument()
    expect(await screen.findByText('先写冲突。')).toBeInTheDocument()
    await waitFor(() => expect(api.job).toHaveBeenCalledWith('novel-1', 'job-1', expect.anything()))
    fireEvent.click(screen.getByRole('checkbox', { name: '引用资产 车站重逢' }))
    await userEvent.type(screen.getByRole('textbox', { name: '对话内容' }), '把冲突推到站台上')
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() => expect(api.createMessage).toHaveBeenCalledWith(
      'novel-1', conversation.id,
      { text: '把冲突推到站台上', intent: 'discuss', reference_ids: ['asset-1'] },
      expect.any(String),
    ))
  })

  it('shows degraded retrieval and exposes the chapter review evidence', async () => {
    api.overview.mockResolvedValue(overview())
    api.conversation.mockResolvedValue({ conversation, messages: [{
      id: 'message-1', conversation_id: conversation.id, role: 'assistant', content: '仍按固定设定回答。',
      status: 'completed', intent: 'review', sources: [], job_id: 'job-1', retrieval_available: false,
      created_at: '2026-10-13T08:01:00Z',
    }] })
    api.job.mockResolvedValue({ ...completedJob, retrieval_available: false })

    mount()

    expect(await screen.findByText('本次关键词检索不可用，回复仍包含固定设定与明确引用。')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '查看审阅结果' }))
    expect(screen.getByText('92')).toBeInTheDocument()
    expect(screen.getByText('站台空间关系可以更清楚')).toBeInTheDocument()
  })

  it('requires a deliberate adoption choice before changing an official chapter', async () => {
    api.overview.mockResolvedValue(overview())
    api.conversation.mockResolvedValue({ conversation, messages: [] })
    api.adoptAsset.mockResolvedValue({ asset_id: 'asset-1', chapter_id: 'chapter-2', chapter_index: 1, chapter_version: 1 })

    mount()

    fireEvent.click(await screen.findByRole('button', { name: '采用为章节' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('采用章节草稿')
    expect(screen.getByText('追加为新章节')).toBeInTheDocument()
    expect(screen.getByRole('spinbutton', { name: '章节序号' })).toHaveDisplayValue('2')
    fireEvent.click(screen.getByRole('button', { name: '确认采用' }))

    await waitFor(() => expect(api.adoptAsset).toHaveBeenCalledWith('novel-1', 'asset-1', {
      expected_version: 2,
      acceptance: 'reviewed',
      chapter_index: 1,
    }))
  })

  it('allows rewrite with explicit asset references and no official chapter target', async () => {
    api.overview.mockResolvedValue(overview())
    api.conversation.mockResolvedValue({ conversation, messages: [] })
    api.createMessage.mockResolvedValue({ ...completedJob, status: 'queued', content: '' })
    api.streamJob.mockResolvedValue(completedJob)

    mount()

    fireEvent.click(await screen.findByRole('checkbox', { name: '引用资产 车站重逢' }))
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '创作意图' }))
    fireEvent.click(await screen.findByText('改写'))
    await userEvent.type(screen.getByRole('textbox', { name: '对话内容' }), '按引用草稿重写结尾')
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() => expect(api.createMessage).toHaveBeenCalledWith(
      'novel-1', conversation.id,
      { text: '按引用草稿重写结尾', intent: 'rewrite', reference_ids: ['asset-1'] },
      expect.any(String),
    ))
  })

  it('does not submit a stale chapter target after switching away from a chapter intent', async () => {
    api.overview.mockResolvedValue(overview())
    api.conversation.mockResolvedValue({ conversation, messages: [] })
    api.createMessage.mockResolvedValue({ ...completedJob, status: 'queued', content: '' })
    api.streamJob.mockResolvedValue(completedJob)

    mount()

    fireEvent.mouseDown(await screen.findByRole('combobox', { name: '创作意图' }))
    fireEvent.click(await screen.findByText('改写'))
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '目标章节' }))
    fireEvent.click(await screen.findByText(/第 1 章/))
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '创作意图' }))
    fireEvent.click(await screen.findByText('讨论'))
    await userEvent.type(screen.getByRole('textbox', { name: '对话内容' }), '只讨论下一幕')
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() => expect(api.createMessage).toHaveBeenCalledWith(
      'novel-1', conversation.id,
      { text: '只讨论下一幕', intent: 'discuss', reference_ids: [] },
      expect.any(String),
    ))
  })

  it('replaces a terminal stream subscription when the same persisted job is retried', async () => {
    const runningJob = { ...completedJob, status: 'running', content: '未完成段落' }
    const failedJob = { ...runningJob, status: 'failed', error: '连接中断' }
    const queuedJob = { ...failedJob, status: 'queued', error: null }
    const retriedJob = { ...queuedJob, status: 'completed', content: '重试后的完整段落' }
    api.overview.mockResolvedValue(overview())
    api.conversation.mockResolvedValue({ conversation, messages: [{
      id: 'message-1', conversation_id: conversation.id, role: 'assistant', content: '',
      status: 'running', intent: 'discuss', sources: [], job_id: 'job-1', created_at: '2026-10-13T08:01:00Z',
    }] })
    api.job.mockResolvedValue(runningJob)
    api.retryJob.mockResolvedValue(queuedJob)
    api.streamJob.mockImplementationOnce((_novelId: string, _jobId: string, onSnapshot: (value: unknown) => void, signal: AbortSignal) => {
      return new Promise((_resolve, reject) => {
        queueMicrotask(() => onSnapshot(failedJob))
        signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
      })
    }).mockImplementationOnce(async (_novelId: string, _jobId: string, onSnapshot: (value: unknown) => void) => {
      onSnapshot(retriedJob)
      return retriedJob
    })

    mount()

    await waitFor(() => expect(api.streamJob).toHaveBeenCalledTimes(1))
    fireEvent.click(await screen.findByRole('button', { name: /重试任务/ }))
    await waitFor(() => expect(api.streamJob).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('重试后的完整段落')).toBeInTheDocument()
  })

  it('shows exact reply sources and retained partial attempts', async () => {
    const source = {
      source_type: 'asset', source_id: 'asset-source-9', title: '人物动机', version: 4,
      start: 120, end: 248, text: '她隐瞒了车站事故。', score: 0.87,
    }
    api.overview.mockResolvedValue(overview())
    api.conversation.mockResolvedValue({ conversation, messages: [{
      id: 'message-1', conversation_id: conversation.id, role: 'assistant', content: '当前完整回复。',
      status: 'completed', intent: 'discuss', sources: [source], job_id: 'job-1', created_at: '2026-10-13T08:01:00Z',
    }] })
    api.job.mockResolvedValue({
      ...completedJob, content: '当前完整回复。', sources: [source],
      previous_attempts: [{ status: 'failed', content: '上一次保留的未完成回复。' }],
    })

    mount()

    fireEvent.click(await screen.findByRole('button', { name: '查看来源 1' }))
    expect(screen.getByText('asset-source-9')).toBeInTheDocument()
    expect(screen.getByText('版本 4')).toBeInTheDocument()
    expect(screen.getByText('偏移 120-248')).toBeInTheDocument()
    fireEvent.click(screen.getByText('查看上次未完成内容（1）'))
    expect(screen.getByText('上一次保留的未完成回复。')).toBeInTheDocument()
  })
})
