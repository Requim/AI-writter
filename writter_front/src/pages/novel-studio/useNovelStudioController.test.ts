import { act, renderHook, waitFor } from '@testing-library/react'
import { AxiosError } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'
const { apiMock, appMock, quotaRefreshMock, setAutoModeMock, tenantListMock, workflowMock } = vi.hoisted(() => ({
  apiMock: {
    get: vi.fn(), progress: vi.fn(), chapters: vi.fn(), chapter: vi.fn(),
    plan: vi.fn(), tacticalPlan: vi.fn(), tacticalPlanVersions: vi.fn(),
    updateChapter: vi.fn(), rewriteChapter: vi.fn(), batchDeleteChapters: vi.fn(),
  },
  appMock: {
    message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
    modal: { confirm: vi.fn() }, notification: { open: vi.fn() },
  },
  quotaRefreshMock: vi.fn(),
  setAutoModeMock: vi.fn(),
  tenantListMock: vi.fn(),
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
vi.mock('react-router', () => ({
  useLocation: () => ({ state: undefined }), useNavigate: () => vi.fn(),
  useParams: () => ({ novelId: 'novel-1' }),
}))
vi.mock('@/api/novel', () => ({ novelApi: apiMock }))
vi.mock('@/api/auth', () => ({ tenantApi: { list: tenantListMock } }))
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
import { useAuthStore } from '@/stores/authStore'

function setPlanningEnabled(enabled: boolean): void {
  useAuthStore.setState({
    currentTenantId: 'tenant-1',
    tenants: [{ id: 'tenant-1', name: '编辑部', slug: 'desk', role: 'owner', status: 'active',
      ai_enabled: true, monthly_generation_limit: 30, monthly_generation_unlimited: false,
      novel_planning_v1_enabled: enabled, novel_planning_v1_effective: enabled }],
  })
}

function rewriteConflict(code: string): AxiosError {
  return new AxiosError(
    'duplicate', AxiosError.ERR_BAD_REQUEST, undefined, undefined,
    { data: { detail: { code } }, status: 409,
      statusText: 'Conflict', headers: {}, config: {} as never },
  )
}

describe('useNovelStudioController auto preference', () => {
  beforeEach(() => {
    setAutoModeMock.mockReset()
    workflowMock.run.mockReset().mockResolvedValue(undefined)
    workflowMock.sync.mockReset().mockResolvedValue(undefined)
    quotaRefreshMock.mockReset().mockResolvedValue(undefined)
    tenantListMock.mockReset().mockImplementation(async () => useAuthStore.getState().tenants)
    appMock.modal.confirm.mockReset()
    appMock.message.info.mockReset()
    apiMock.get.mockResolvedValue({ id: 'novel-1', novel_type: 'suspense', status: 'writing' })
    apiMock.progress.mockResolvedValue({ current_chapter: 0, total_chapters: 3, percentage: 0, status: 'writing' })
    apiMock.chapters.mockResolvedValue([])
    apiMock.chapter.mockReset()
    apiMock.rewriteChapter.mockReset()
    apiMock.plan.mockReset().mockResolvedValue(null)
    apiMock.tacticalPlan.mockReset().mockResolvedValue({ status: 'missing', window: null, assembled_slots: [] })
    apiMock.tacticalPlanVersions.mockReset().mockResolvedValue([])
    useAuthStore.setState({ tenants: [], currentTenantId: undefined })
  })

  it('keeps the current automatic run active when changing the next-command preference', () => {
    const { result } = renderHook(() => useNovelStudioController())
    act(() => result.current.startWriting())
    expect(result.current.autoRunActive).toBe(true)
    act(() => result.current.setAutoMode(false))
    expect(setAutoModeMock).toHaveBeenCalledWith(false)
    expect(result.current.autoRunActive).toBe(true)
  })

  it('relocates a rewritten chapter by index when the recovered row has a new id', async () => {
    const original = {
      id: 'chapter-1', chapter_index: 0, title: '雨夜来信', word_count: 4,
      status: 'completed', version: 1, review_status: 'passed' as const, quality_score: 4.2,
    }
    const rewritten = { ...original, id: 'chapter-rewritten', version: 2 }
    const originalDetail = { ...original, content: '旧正文', updated_at: '2026-08-04T07:00:00Z' }
    const rewrittenDetail = { ...rewritten, content: '最新正文', updated_at: '2026-08-04T08:00:00Z' }
    apiMock.chapters.mockResolvedValueOnce([original]).mockResolvedValue([rewritten])
    apiMock.chapter.mockResolvedValueOnce(originalDetail).mockResolvedValue(rewrittenDetail)
    apiMock.rewriteChapter.mockRejectedValue(rewriteConflict('workflow_command_already_applied'))
    const { result } = renderHook(() => useNovelStudioController())
    await waitFor(() => expect(result.current.document.selectedChapter?.id).toBe('chapter-1'))
    act(() => result.current.rewriteChapter())
    const modal = appMock.modal.confirm.mock.calls.at(-1)?.[0] as { onOk: () => Promise<void> }
    await act(async () => modal.onOk())
    expect(apiMock.chapter).toHaveBeenLastCalledWith('novel-1', 'chapter-rewritten')
    expect(quotaRefreshMock).toHaveBeenCalled()
    expect(result.current.document.selectedChapter?.id).toBe('chapter-rewritten')
    expect(result.current.document.selectedChapter?.content).toBe('最新正文')
    expect(appMock.message.info).toHaveBeenCalledWith(expect.stringContaining('已同步'))
  })

  it('keeps using the stable chapter id during an in-progress rewrite recovery', async () => {
    const summary = {
      id: 'chapter-1', chapter_index: 0, title: '雨夜来信', word_count: 4,
      status: 'completed', version: 2, review_status: 'passed' as const, quality_score: 4.2,
    }
    const initial = { ...summary, version: 1, content: '旧正文', updated_at: '2026-08-04T07:00:00Z' }
    const rewritten = { ...summary, content: '稳定 ID 的新正文', updated_at: '2026-08-04T08:00:00Z' }
    apiMock.chapters.mockResolvedValue([summary])
    apiMock.chapter.mockResolvedValueOnce(initial).mockResolvedValue(rewritten)
    apiMock.rewriteChapter.mockRejectedValue(rewriteConflict('workflow_command_in_progress'))
    const { result } = renderHook(() => useNovelStudioController())
    await waitFor(() => expect(result.current.document.selectedChapter?.content).toBe('旧正文'))
    act(() => result.current.rewriteChapter())
    const modal = appMock.modal.confirm.mock.calls.at(-1)?.[0] as { onOk: () => Promise<void> }
    await act(async () => modal.onOk())
    expect(apiMock.chapter).toHaveBeenLastCalledWith('novel-1', 'chapter-1')
    expect(result.current.document.selectedChapter?.content).toBe('稳定 ID 的新正文')
    expect(quotaRefreshMock).toHaveBeenCalled()
  })

  it('starts manual replanning with the accepted plan version', async () => {
    setPlanningEnabled(true)
    apiMock.plan.mockResolvedValue({ version: 7 })
    const { result } = renderHook(() => useNovelStudioController())
    await waitFor(() => expect(result.current.document.plan?.version).toBe(7))

    act(() => result.current.startWriting())
    expect(result.current.autoRunActive).toBe(true)
    act(() => result.current.replanPlan({ scope: 'scale', instruction: '压缩为两卷并保留结局' }))

    expect(workflowMock.run).toHaveBeenLastCalledWith({
      command: {
        plan_replan: { expected_version: 7, scope: 'scale', instruction: '压缩为两卷并保留结局' },
        _auto_mode: false,
      },
    })
    expect(result.current.autoRunActive).toBe(false)
    expect(result.current.document.mobilePanel).toBe('workflow')
  })

  it('loads tactical documents only for an effectively enabled tenant', async () => {
    setPlanningEnabled(true)
    apiMock.plan.mockResolvedValue({ version: 3 })
    apiMock.tacticalPlan.mockResolvedValue({ status: 'active', window: { version: 4 }, assembled_slots: [] })
    apiMock.tacticalPlanVersions.mockResolvedValue([{ version: 4 }])
    const { result } = renderHook(() => useNovelStudioController())

    await waitFor(() => expect(result.current.document.tacticalPlan?.status).toBe('active'))
    expect(result.current.planningEnabled).toBe(true)
    expect(apiMock.tacticalPlan).toHaveBeenCalledWith('novel-1')
    expect(apiMock.tacticalPlanVersions).toHaveBeenCalledWith('novel-1')
  })

  it('refreshes the effective tenant feature when the studio opens', async () => {
    const enabledTenant = {
      id: 'tenant-1', name: '编辑部', slug: 'desk', role: 'owner' as const, status: 'active',
      ai_enabled: true, monthly_generation_limit: 30, monthly_generation_unlimited: false,
      novel_planning_v1_enabled: true, novel_planning_v1_effective: true,
    }
    tenantListMock.mockResolvedValue([enabledTenant])
    const { result } = renderHook(() => useNovelStudioController())

    await waitFor(() => expect(result.current.planningEnabled).toBe(true))
    expect(apiMock.plan).toHaveBeenCalledWith('novel-1')
  })

  it('keeps tactical history failures separate from the current window', async () => {
    setPlanningEnabled(true)
    apiMock.tacticalPlan.mockResolvedValue({ status: 'active', window: { version: 4 }, assembled_slots: [] })
    apiMock.tacticalPlanVersions.mockRejectedValue(new Error('history unavailable'))
    const { result } = renderHook(() => useNovelStudioController())

    await waitFor(() => expect(result.current.document.tacticalPlan?.status).toBe('active'))
    expect(result.current.document.tacticalLoadFailed).toBe(false)
    expect(result.current.document.tacticalVersionsLoadFailed).toBe(true)
  })

  it('refreshes accepted planning documents after a workflow resume', async () => {
    setPlanningEnabled(true)
    apiMock.plan.mockResolvedValue({ version: 3 })
    const { result } = renderHook(() => useNovelStudioController())
    await waitFor(() => expect(result.current.document.plan?.version).toBe(3))
    apiMock.plan.mockResolvedValue({ version: 4 })

    act(() => result.current.resumeWriting({ decision: 'accept' }))

    await waitFor(() => expect(result.current.document.plan?.version).toBe(4))
    expect(workflowMock.resume).toHaveBeenCalled()
  })

  it('keeps planning endpoints and workspace entry off for an unenabled tenant', async () => {
    const { result } = renderHook(() => useNovelStudioController())
    await waitFor(() => expect(result.current.document.loading).toBe(false))
    expect(result.current.planningEnabled).toBe(false)
    expect(apiMock.plan).not.toHaveBeenCalled()
    expect(apiMock.tacticalPlan).not.toHaveBeenCalled()
  })
})
