import { act, renderHook, waitFor } from '@testing-library/react'
import { AxiosError } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'
const { apiMock, appMock, quotaRefreshMock, setAutoModeMock, workflowMock } = vi.hoisted(() => ({
  apiMock: {
    get: vi.fn(), progress: vi.fn(), chapters: vi.fn(), chapter: vi.fn(),
    updateChapter: vi.fn(), rewriteChapter: vi.fn(), batchDeleteChapters: vi.fn(),
  },
  appMock: {
    message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
    modal: { confirm: vi.fn() }, notification: { open: vi.fn() },
  },
  quotaRefreshMock: vi.fn(),
  setAutoModeMock: vi.fn(),
  workflowMock: {
    state: {
      status: 'idle', connection: 'idle', draft: '', issues: [], events: [],
      consecutiveSyncFailures: 0, connectionRecovering: false,
    },
    run: vi.fn(), retry: vi.fn(), resume: vi.fn(),
    cancel: vi.fn(), sync: vi.fn(), hydrateInterrupt: vi.fn(), hydrateSnapshot: vi.fn(),
  },
}))

vi.mock('antd', () => ({ App: { useApp: () => appMock } }))
vi.mock('react-router-dom', () => ({
  useLocation: () => ({ state: undefined }), useNavigate: () => vi.fn(),
  useParams: () => ({ novelId: 'novel-1' }),
}))
vi.mock('@/api/novel', () => ({ novelApi: apiMock }))
vi.mock('@/hooks/useWorkflowStream', () => ({ useWorkflowStream: () => workflowMock }))
vi.mock('@/hooks/useUnsavedChangesGuard', () => ({
  useUnsavedChangesGuard: () => (action: () => void) => action(),
}))
vi.mock('@/stores/novelStore', () => ({
  useNovelStore: (select: (state: { autoMode: boolean; setAutoMode: typeof setAutoModeMock }) => unknown) => (
    select({ autoMode: true, setAutoMode: setAutoModeMock })
  ),
}))
vi.mock('@/stores/quotaStore', () => ({ refreshQuota: quotaRefreshMock }))

import { useNovelStudioController } from './useNovelStudioController'

describe('useNovelStudioController auto preference', () => {
  beforeEach(() => {
    setAutoModeMock.mockReset()
    workflowMock.run.mockReset().mockResolvedValue(undefined)
    workflowMock.sync.mockReset().mockResolvedValue(undefined)
    quotaRefreshMock.mockReset().mockResolvedValue(undefined)
    appMock.modal.confirm.mockReset()
    appMock.message.info.mockReset()
    apiMock.get.mockResolvedValue({ id: 'novel-1', novel_type: 'suspense', status: 'writing' })
    apiMock.progress.mockResolvedValue({ current_chapter: 0, total_chapters: 3, percentage: 0, status: 'writing' })
    apiMock.chapters.mockResolvedValue([])
  })

  it('keeps the current automatic run active when changing the next-command preference', () => {
    const { result } = renderHook(() => useNovelStudioController())
    act(() => result.current.startWriting())
    expect(result.current.autoRunActive).toBe(true)
    act(() => result.current.setAutoMode(false))
    expect(setAutoModeMock).toHaveBeenCalledWith(false)
    expect(result.current.autoRunActive).toBe(true)
  })

  it('syncs the chapter and quota after a duplicate rewrite response', async () => {
    const summary = {
      id: 'chapter-1', chapter_index: 0, title: '雨夜来信', word_count: 4,
      status: 'completed', version: 1, review_status: 'passed' as const, quality_score: 4.2,
    }
    const detail = { ...summary, content: '最新正文', updated_at: '2026-08-04T08:00:00Z' }
    apiMock.chapters.mockResolvedValue([summary])
    apiMock.chapter.mockResolvedValue(detail)
    apiMock.rewriteChapter.mockRejectedValue(new AxiosError(
      'duplicate', AxiosError.ERR_BAD_REQUEST, undefined, undefined,
      { data: { detail: { code: 'workflow_command_already_applied' } }, status: 409,
        statusText: 'Conflict', headers: {}, config: {} as never },
    ))
    const { result } = renderHook(() => useNovelStudioController())
    await waitFor(() => expect(result.current.document.selectedChapter?.id).toBe('chapter-1'))
    act(() => result.current.rewriteChapter())
    const modal = appMock.modal.confirm.mock.calls.at(-1)?.[0] as { onOk: () => Promise<void> }
    await act(async () => modal.onOk())
    expect(apiMock.chapter.mock.calls.length).toBeGreaterThanOrEqual(2)
    expect(quotaRefreshMock).toHaveBeenCalled()
    expect(result.current.document.selectedChapter?.content).toBe('最新正文')
    expect(appMock.message.info).toHaveBeenCalledWith(expect.stringContaining('已同步'))
  })
})
