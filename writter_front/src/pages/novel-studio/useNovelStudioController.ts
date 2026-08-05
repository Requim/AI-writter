import { App } from 'antd'
import axios from 'axios'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router'
import { novelApi } from '@/api/novel'
import { tenantApi } from '@/api/auth'
import { useWorkflowStream, type WorkflowViewState } from '@/hooks/useWorkflowStream'
import { useUnsavedChangesGuard, type DiscardConfirmation } from '@/hooks/useUnsavedChangesGuard'
import { currentTenant, useAuthStore } from '@/stores/authStore'
import { useNovelStore } from '@/stores/novelStore'
import { refreshQuota } from '@/stores/quotaStore'
import type {
  ChapterDetail, ChapterSummary, NovelPlan, NovelResponse, PlanReplanRequest, ProgressResponse,
  TacticalPlanResponse, TacticalPlanVersionSummary,
} from '@/types/novel'
import {
  autoResumeValue, hasChapterChanges, interruptKey, rewindImpactText, shouldAutoResume,
} from '../novelStudioUtils'
import { useAutoRunNotifications } from './useAutoRunNotifications'

interface StudioLocationState { startInput?: Record<string, unknown> }
type AppContext = ReturnType<typeof App.useApp>
type DocumentLoadError = 'not_found' | 'forbidden' | 'network'

interface DocumentState {
  novel?: NovelResponse
  plan?: NovelPlan
  planLoadFailed?: boolean
  tacticalPlan?: TacticalPlanResponse
  tacticalVersions: TacticalPlanVersionSummary[]
  tacticalLoadFailed?: boolean
  tacticalVersionsLoadFailed?: boolean
  progress?: ProgressResponse
  chapters: ChapterSummary[]
  selectedChapter?: ChapterDetail
  editorTitle: string
  editorContent: string
  editorMode: 'read' | 'edit'
  workspaceMode: 'chapter' | 'plan'
  mobilePanel: 'chapters' | 'plan' | 'editor' | 'workflow'
  loading: boolean
  loadError?: DocumentLoadError
  saving: boolean
  saveFailed?: boolean
  lastSavedAt?: string
  rewriting: boolean
}

interface DocumentModel {
  state: DocumentState
  setState: React.Dispatch<React.SetStateAction<DocumentState>>
  selectedRef: React.MutableRefObject<ChapterDetail | undefined>
  loadedRef: React.MutableRefObject<boolean>
}

const initialDocumentState: DocumentState = {
  chapters: [], editorTitle: '', editorContent: '', editorMode: 'read',
  workspaceMode: 'chapter', mobilePanel: 'editor', loading: true,
  tacticalVersions: [], saving: false, saveFailed: false, rewriting: false,
}

const REWRITE_SYNC_CODES = new Set([
  'workflow_command_in_progress', 'workflow_command_already_applied',
])

function apiErrorCode(error: unknown): string | undefined {
  if (!axios.isAxiosError(error)) return undefined
  const payload = error.response?.data as { detail?: { code?: unknown } } | undefined
  return typeof payload?.detail?.code === 'string' ? payload.detail.code : undefined
}

function isRewriteSyncSignal(error: unknown): boolean {
  return axios.isAxiosError(error)
    && error.response?.status === 409
    && REWRITE_SYNC_CODES.has(apiErrorCode(error) || '')
}

function documentLoadError(error: unknown): DocumentLoadError {
  if (!axios.isAxiosError(error)) return 'network'
  if (error.response?.status === 404) return 'not_found'
  if ([401, 403].includes(error.response?.status || 0)) return 'forbidden'
  return 'network'
}

function useDocumentModel(): DocumentModel {
  const [state, setState] = useState<DocumentState>(initialDocumentState)
  const selectedRef = useRef<ChapterDetail | undefined>(undefined)
  const loadedRef = useRef(false)
  return { state, setState, selectedRef, loadedRef }
}

function applySelectedChapter(
  setState: DocumentModel['setState'],
  selectedRef: DocumentModel['selectedRef'],
  detail: ChapterDetail,
): void {
  selectedRef.current = detail
  setState((current) => ({
    ...current, selectedChapter: detail, editorTitle: detail.title,
    editorContent: detail.content, editorMode: 'read', workspaceMode: 'chapter',
    mobilePanel: 'editor', saveFailed: false,
    lastSavedAt: current.selectedChapter?.id === detail.id ? current.lastSavedAt : undefined,
  }))
}

function useDocumentRefresh(
  model: DocumentModel,
  novelId: string,
  message: AppContext['message'],
  planningEnabled: boolean,
) {
  const { setState, selectedRef, loadedRef } = model
  return useCallback(async () => {
    if (!novelId) return
    if (!loadedRef.current) setState((current) => ({ ...current, loading: true, loadError: undefined }))
    try {
      const [novel, progress, chapters, planning] = await Promise.all([
        novelApi.get(novelId), novelApi.progress(novelId), novelApi.chapters(novelId),
        loadOptionalPlanning(novelId, planningEnabled),
      ])
      loadedRef.current = true
      setState((current) => ({
        ...current, novel, progress, chapters, plan: planning.plan,
        planLoadFailed: planning.planFailed, tacticalPlan: planning.tactical,
        tacticalVersions: planning.tacticalVersions, tacticalLoadFailed: planning.tacticalFailed,
        tacticalVersionsLoadFailed: planning.tacticalVersionsFailed,
        loadError: undefined,
      }))
      if (!selectedRef.current && chapters.length > 0) {
        applySelectedChapter(setState, selectedRef, await novelApi.chapter(novelId, chapters.at(-1)!.id))
      }
    } catch (error) {
      if (loadedRef.current) message.error('暂时无法刷新稿件')
      else setState((current) => ({ ...current, loadError: documentLoadError(error) }))
    } finally {
      setState((current) => ({ ...current, loading: false }))
    }
  }, [loadedRef, message, novelId, planningEnabled, selectedRef, setState])
}

async function loadOptionalPlan(novelId: string): Promise<{ plan?: NovelPlan; failed?: boolean }> {
  try {
    const plan = await novelApi.plan(novelId)
    return plan ? { plan } : {}
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) return {}
    return { failed: true }
  }
}

interface PlanningDocuments {
  plan?: NovelPlan
  tactical?: TacticalPlanResponse
  tacticalVersions: TacticalPlanVersionSummary[]
  planFailed?: boolean
  tacticalFailed?: boolean
  tacticalVersionsFailed?: boolean
}

async function loadOptionalPlanning(novelId: string, enabled: boolean): Promise<PlanningDocuments> {
  if (!enabled) return { tacticalVersions: [] }
  const [planning, tactical] = await Promise.all([loadOptionalPlan(novelId), loadOptionalTactical(novelId)])
  return {
    plan: planning.plan, planFailed: planning.failed, tactical: tactical.response,
    tacticalVersions: tactical.versions, tacticalFailed: tactical.responseFailed,
    tacticalVersionsFailed: tactical.versionsFailed,
  }
}

async function loadOptionalTactical(novelId: string) {
  const [response, versions] = await Promise.allSettled([
    novelApi.tacticalPlan(novelId), novelApi.tacticalPlanVersions(novelId),
  ])
  return {
    response: response.status === 'fulfilled' ? response.value : undefined,
    versions: versions.status === 'fulfilled' ? versions.value : [] as TacticalPlanVersionSummary[],
    responseFailed: response.status === 'rejected',
    versionsFailed: versions.status === 'rejected',
  }
}

function useInitialRefresh(refresh: () => Promise<void> | undefined): void {
  useEffect(() => { queueMicrotask(() => void refresh()) }, [refresh])
}

function useChapterLoader(model: DocumentModel, novelId: string) {
  const { selectedRef, setState } = model
  return useCallback(async (chapter: ChapterSummary) => {
    applySelectedChapter(setState, selectedRef, await novelApi.chapter(novelId, chapter.id))
  }, [novelId, selectedRef, setState])
}

function useDiscardGuard(
  hasChanges: boolean,
  modal: AppContext['modal'],
) {
  const request = useCallback<DiscardConfirmation>((onConfirm, onCancel) => {
    modal.confirm({
      title: '有未保存的修改', content: '离开后，本次修改将无法恢复。',
      okText: '放弃修改并离开', cancelText: '继续编辑',
      okButtonProps: { danger: true }, onOk: onConfirm, onCancel,
    })
  }, [modal])
  return useUnsavedChangesGuard(hasChanges, request)
}

function useChapterSave(
  model: DocumentModel,
  novelId: string,
  refresh: () => Promise<void> | undefined,
  app: AppContext,
) {
  const { selectedChapter, editorTitle, editorContent } = model.state
  const { selectedRef, setState } = model
  return useCallback(async () => {
    const chapter = selectedChapter
    if (!chapter) return false
    setState((current) => ({ ...current, saving: true, saveFailed: false }))
    try {
      const updated = await novelApi.updateChapter(novelId, chapter.id, {
        title: editorTitle, content: editorContent,
        expected_version: chapter.version,
      })
      applySelectedChapter(setState, selectedRef, updated)
      setState((current) => ({
        ...current, editorMode: 'edit', saveFailed: false, lastSavedAt: new Date().toISOString(),
      }))
      app.message.success('章节已保存')
      if (updated.checkpoint_status === 'deferred') app.message.warning('正文已保存，创作现场将在服务恢复后重新同步')
      await refresh()
      return true
    } catch (error) {
      setState((current) => ({ ...current, saveFailed: true }))
      const code = apiErrorCode(error)
      if (code === 'chapter_version_conflict') {
        app.modal.confirm({
          title: '章节已在其他窗口更新', content: '当前编辑内容仍会保留。载入最新版后，本地未保存内容将被替换。',
          okText: '载入最新版', cancelText: '保留本地内容',
          onOk: () => void novelApi.chapter(novelId, chapter.id).then(
            (latest) => applySelectedChapter(setState, selectedRef, latest),
          ),
        })
      } else app.message.error(code === 'novel_busy' ? '作品正在生成，请结束任务后再编辑' : '章节保存失败，请稍后重试')
      return false
    } finally {
      setState((current) => ({ ...current, saving: false }))
    }
  }, [app, editorContent, editorTitle, novelId, refresh, selectedChapter, selectedRef, setState])
}

async function syncRewrittenChapter(
  model: DocumentModel,
  novelId: string,
  selected: Pick<ChapterSummary, 'id' | 'chapter_index'>,
  refresh: () => Promise<void> | undefined,
): Promise<void> {
  const chapters = await novelApi.chapters(novelId)
  model.setState((current) => ({ ...current, chapters }))
  const chapterId = chapters.find(
    (chapter) => chapter.chapter_index === selected.chapter_index,
  )?.id || selected.id
  const detail = await novelApi.chapter(novelId, chapterId)
  applySelectedChapter(model.setState, model.selectedRef, detail)
  await Promise.all([refresh(), refreshQuota()])
}

function useChapterRewrite(
  model: DocumentModel,
  novelId: string,
  refresh: () => Promise<void> | undefined,
  app: AppContext,
) {
  const selected = model.state.selectedChapter
  return useCallback(() => {
    if (!selected) return
    app.modal.confirm({
      title: `AI 重写第 ${selected.chapter_index + 1} 章？`,
      content: '只替换当前章节正文并重新审读，将预留 1 次生成额度；后续章节不会被删除。',
      okText: '开始重写',
      onOk: async () => {
        model.setState((current) => ({ ...current, rewriting: true }))
        try {
          const detail = await novelApi.rewriteChapter(novelId, selected.id)
          applySelectedChapter(model.setState, model.selectedRef, detail)
          await Promise.all([refresh(), refreshQuota()])
          app.message.success(`第 ${selected.chapter_index + 1} 章已重写`)
        } catch (error) {
          if (!isRewriteSyncSignal(error)) {
            app.message.error('章节重写失败，请稍后重试')
            throw error
          }
          await syncRewrittenChapter(model, novelId, selected, refresh)
          app.message.info('重写请求正在处理或已完成，已同步当前章节与额度')
        } finally {
          model.setState((current) => ({ ...current, rewriting: false }))
        }
      },
    })
  }, [app, model, novelId, refresh, selected])
}

function useChapterDelete(
  model: DocumentModel,
  novelId: string,
  refresh: () => Promise<void> | undefined,
  app: AppContext,
) {
  const { chapters, selectedChapter } = model.state
  const { selectedRef, setState } = model
  return useCallback(() => {
    const selected = selectedChapter
    if (!selected) return
    const count = chapters.filter((item) => item.chapter_index >= selected.chapter_index).length || 1
    app.modal.confirm({
      title: `从第 ${selected.chapter_index + 1} 章重新创作？`,
      content: rewindImpactText(selected, chapters),
      okText: `删除 ${count} 章并回退`, okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const result = await novelApi.batchDeleteChapters(novelId, [selected.id])
          selectedRef.current = undefined
          setState((current) => ({ ...current, selectedChapter: undefined }))
          await refresh()
          app.message.success(`已删除 ${result.count} 章，下次将从第 ${selected.chapter_index + 1} 章重新创作`)
          if (result.checkpoint_status === 'deferred') app.message.warning('正文已回退，创作现场将在服务恢复后重新同步')
        } catch (error) {
          app.message.error(apiErrorCode(error) === 'novel_busy' ? '作品正在生成，暂时无法回退' : '章节回退失败')
          throw error
        }
      },
    })
  }, [app, chapters, novelId, refresh, selectedChapter, selectedRef, setState])
}

function useInitialWorkflowStart(
  novel: NovelResponse | undefined,
  autoMode: boolean,
  run: ReturnType<typeof useWorkflowStream>['run'],
  setActive: React.Dispatch<React.SetStateAction<boolean>>,
): void {
  const location = useLocation()
  const navigate = useNavigate()
  const startedRef = useRef(false)
  useEffect(() => {
    const data = location.state as StudioLocationState | null
    if (!novel || !data?.startInput || startedRef.current) return
    startedRef.current = true
    setActive(autoMode)
    void run({ input: { ...data.startInput, _auto_mode: autoMode } })
    void navigate(location.pathname, { replace: true, state: null })
  }, [autoMode, location.pathname, location.state, navigate, novel, run, setActive])
}

function useAutoResume(
  workflow: ReturnType<typeof useWorkflowStream>,
  novelType: string,
  autoMode: boolean,
  active: boolean,
  lastInterruptRef: React.MutableRefObject<string | undefined>,
): void {
  useEffect(() => {
    const interrupt = workflow.state.interrupt
    if (!interrupt || !shouldAutoResume(autoMode, active, interrupt, lastInterruptRef.current)) return
    lastInterruptRef.current = interruptKey(interrupt)
    void workflow.resume(autoResumeValue(interrupt, novelType), true)
  }, [active, autoMode, lastInterruptRef, novelType, workflow])
}

function useAutoRunReset(
  status: WorkflowViewState['status'],
  setActive: React.Dispatch<React.SetStateAction<boolean>>,
): void {
  const previousRef = useRef(status)
  useEffect(() => {
    const previous = previousRef.current
    previousRef.current = status
    if (!['running', 'paused', 'stalled', 'cancelling'].includes(previous)) return
    if (['idle', 'recoverable', 'error', 'completed'].includes(status)) queueMicrotask(() => setActive(false))
  }, [setActive, status])
}

function detachedPollDelay(): number {
  return document.visibilityState === 'hidden' ? 15_000 : 3_000
}

function useDetachedSync(
  connection: WorkflowViewState['connection'],
  status: WorkflowViewState['status'],
  sync: ReturnType<typeof useWorkflowStream>['sync'],
): void {
  useEffect(() => {
    if (connection !== 'detached' || !['running', 'stalled'].includes(status)) return
    const poll = () => void sync(true).catch(() => undefined)
    let timer = window.setInterval(poll, detachedPollDelay())
    const restart = () => {
      window.clearInterval(timer)
      poll()
      timer = window.setInterval(poll, detachedPollDelay())
    }
    document.addEventListener('visibilitychange', restart)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', restart)
    }
  }, [connection, status, sync])
}

function useQuotaRefresh(commandId?: string, chapterId?: string): void {
  const previousCommand = useRef<string | undefined>(undefined)
  const previousChapter = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (!commandId || previousCommand.current === commandId) return
    previousCommand.current = commandId
    const timer = window.setTimeout(() => void refreshQuota(), 750)
    return () => window.clearTimeout(timer)
  }, [commandId])
  useEffect(() => {
    if (!chapterId || previousChapter.current === chapterId) return
    previousChapter.current = chapterId
    void refreshQuota()
  }, [chapterId])
}

function useInitialWorkflowSync(
  ready: boolean,
  sync: ReturnType<typeof useWorkflowStream>['sync'],
): void {
  useEffect(() => {
    if (ready) queueMicrotask(() => void sync().catch(() => undefined))
  }, [ready, sync])
}

async function fetchPersistedData(novelId: string, chapterId: string, planningEnabled: boolean) {
  const [novel, progress, chapters, detail, planning] = await Promise.all([
    novelApi.get(novelId), novelApi.progress(novelId), novelApi.chapters(novelId),
    novelApi.chapter(novelId, chapterId), loadOptionalPlanning(novelId, planningEnabled),
  ])
  return { novel, progress, chapters, detail, planning }
}

function applyPersistedData(
  setState: DocumentModel['setState'],
  selectedRef: DocumentModel['selectedRef'],
  data: Awaited<ReturnType<typeof fetchPersistedData>>,
  keepEditor: boolean,
): void {
  setState((current) => ({
    ...current, novel: data.novel, progress: data.progress, chapters: data.chapters,
    plan: data.planning.plan, planLoadFailed: data.planning.planFailed,
    tacticalPlan: data.planning.tactical, tacticalVersions: data.planning.tacticalVersions,
    tacticalLoadFailed: data.planning.tacticalFailed,
    tacticalVersionsLoadFailed: data.planning.tacticalVersionsFailed,
  }))
  if (!keepEditor) applySelectedChapter(setState, selectedRef, data.detail)
}

function usePersistedChapterSync(
  model: DocumentModel,
  novelId: string,
  chapterId: string | undefined,
  hasChanges: boolean,
  message: AppContext['message'],
  planningEnabled: boolean,
): void {
  const handledRef = useRef<string | undefined>(undefined)
  const { selectedRef, setState } = model
  useEffect(() => {
    if (!chapterId || !novelId || handledRef.current === chapterId) return
    let active = true
    void fetchPersistedData(novelId, chapterId, planningEnabled).then((data) => {
      if (!active) return
      handledRef.current = chapterId
      applyPersistedData(setState, selectedRef, data, hasChanges)
      if (hasChanges) message.warning('新章节已归档，当前未保存修改仍保留在编辑器中')
    }).catch(() => { if (active) message.warning('章节已保存，目录暂时未能刷新') })
    return () => { active = false }
  }, [chapterId, hasChanges, message, novelId, planningEnabled, selectedRef, setState])
}

function useMetadataSync(model: DocumentModel, workflowState: WorkflowViewState): void {
  const { setState } = model
  useEffect(() => {
    if (!workflowState.metadataUpdatedAt || !workflowState.metadata) return
    setState((current) => ({
      ...current,
      novel: current.novel ? { ...current.novel, ...workflowState.metadata } : current.novel,
    }))
  }, [setState, workflowState.metadata, workflowState.metadataUpdatedAt])
}

function setInterruptRef(
  ref: React.MutableRefObject<string | undefined>,
  value: string | undefined,
): void {
  ref.current = value
}

function recoveryDetails(state: WorkflowViewState, progress?: ProgressResponse) {
  const recoverable = Boolean(state.hasCheckpointDraft || state.hasPendingCheckpoint)
  const chapter = (state.checkpointChapterIndex ?? state.currentChapter ?? progress?.current_chapter ?? 0) + 1
  const reflection = state.hasCheckpointDraft || state.activeNode === 'reflection_node'
  const label = reflection
    ? `${state.status === 'error' ? '重试' : '继续'}第 ${chapter} 章质量审读`
    : state.status === 'error' ? '重试当前步骤' : `从第 ${chapter} 章继续`
  return { recoverable, label }
}

interface WorkflowCommandParams {
  workflow: ReturnType<typeof useWorkflowStream>
  novelId: string
  novelType: string
  autoMode: boolean
  recoverable: boolean
  setActive: React.Dispatch<React.SetStateAction<boolean>>
  lastInterruptRef: React.MutableRefObject<string | undefined>
  refresh: () => Promise<void> | undefined
}

function useWorkflowCommands(params: WorkflowCommandParams) {
  const start = useCallback(() => {
    setInterruptRef(params.lastInterruptRef, undefined)
    params.setActive(params.autoMode)
    if (params.workflow.state.retryable || params.recoverable) return params.workflow.retry(params.autoMode)
    return params.workflow.run({
      input: { novel_id: params.novelId, novel_type: params.novelType, _auto_mode: params.autoMode },
    })
  }, [params])
  const resume = useCallback(async (value: unknown) => {
    const interrupt = params.workflow.state.interrupt
    if (interrupt) setInterruptRef(params.lastInterruptRef, interruptKey(interrupt))
    params.setActive(params.autoMode)
    await params.workflow.resume(value, params.autoMode)
    await params.refresh()
  }, [params])
  const continueAuto = useCallback(async () => {
    const interrupt = params.workflow.state.interrupt
    if (!interrupt) return start()
    setInterruptRef(params.lastInterruptRef, interruptKey(interrupt))
    params.setActive(true)
    await params.workflow.resume(autoResumeValue(interrupt, params.novelType), true)
    await params.refresh()
  }, [params, start])
  const stop = useCallback(async () => {
    params.setActive(false)
    await params.workflow.cancel()
    await params.refresh()
  }, [params])
  const replan = useCallback((expectedVersion: number, request: PlanReplanRequest) => {
    setInterruptRef(params.lastInterruptRef, undefined)
    params.setActive(false)
    return params.workflow.run({
      command: { plan_replan: { expected_version: expectedVersion, ...request }, _auto_mode: false },
    })
  }, [params])
  return { start, resume, continueAuto, stop, replan }
}

function useSaveGate(
  hasChanges: boolean,
  save: () => Promise<boolean>,
  modal: AppContext['modal'],
) {
  return useCallback((action: () => void | Promise<void>) => {
    if (!hasChanges) { void action(); return }
    modal.confirm({
      title: '先保存当前修改？', content: '继续创作后，AI 可能生成并打开新章节。请先保存当前修改，避免内容丢失。',
      okText: '保存并继续', cancelText: '继续编辑',
      onOk: async () => { if (await save()) return action() },
    })
  }, [hasChanges, modal, save])
}

function runPlanReplan(
  model: DocumentModel,
  plan: NovelPlan | undefined,
  request: PlanReplanRequest,
  gate: ReturnType<typeof useSaveGate>,
  replan: ReturnType<typeof useWorkflowCommands>['replan'],
): void {
  if (!plan) return
  gate(async () => {
    model.setState((current) => ({ ...current, mobilePanel: 'workflow' }))
    await replan(plan.version, request)
  })
}

/** 小说工作台视图所需的状态与操作。 */
export interface NovelStudioController {
  novelId: string
  document: DocumentState
  workflow: ReturnType<typeof useWorkflowStream>
  autoMode: boolean
  autoRunActive: boolean
  isCompleted: boolean
  canDelete: boolean
  hasUnsavedChanges: boolean
  hasRecoverableCheckpoint: boolean
  planningEnabled: boolean
  recoveryLabel: string
  confirmDiscardChanges: ReturnType<typeof useUnsavedChangesGuard>
  refresh: () => Promise<void> | undefined
  openChapter: (chapter: ChapterSummary) => void
  saveChapter: () => Promise<boolean>
  deleteChapter: () => void
  rewriteChapter: () => void
  startWriting: () => void
  resumeWriting: (value: unknown) => void
  continueAutoWriting: () => void
  replanPlan: (request: PlanReplanRequest) => void
  stopWriting: () => void
  setAutoMode: (value: boolean) => void
  setEditor: (patch: Partial<DocumentState>) => void
  goBack: () => void
  notifySyncError: () => void
}

function useControllerEffects(
  model: DocumentModel,
  workflow: ReturnType<typeof useWorkflowStream>,
  novelId: string,
  autoMode: boolean,
  active: boolean,
  setActive: React.Dispatch<React.SetStateAction<boolean>>,
  lastInterruptRef: React.MutableRefObject<string | undefined>,
  hasChanges: boolean,
  message: AppContext['message'],
  planningEnabled: boolean,
): void {
  useInitialWorkflowSync(Boolean(model.state.novel), workflow.sync)
  useInitialWorkflowStart(model.state.novel, autoMode, workflow.run, setActive)
  useAutoResume(workflow, model.state.novel?.novel_type || 'suspense', autoMode, active, lastInterruptRef)
  useAutoRunReset(workflow.state.status, setActive)
  useDetachedSync(workflow.state.connection, workflow.state.status, workflow.sync)
  useQuotaRefresh(workflow.state.activeCommandId, workflow.state.lastPersistedChapterId)
  usePersistedChapterSync(
    model, novelId, workflow.state.lastPersistedChapterId, hasChanges, message, planningEnabled,
  )
  useMetadataSync(model, workflow.state)
}

function useStudioDocument(novelId: string, app: AppContext, planningEnabled: boolean) {
  const model = useDocumentModel()
  const refresh = useDocumentRefresh(model, novelId, app.message, planningEnabled)
  useInitialRefresh(refresh)
  const loadChapter = useChapterLoader(model, novelId)
  const saveChapter = useChapterSave(model, novelId, refresh, app)
  const deleteChapter = useChapterDelete(model, novelId, refresh, app)
  const rewriteChapter = useChapterRewrite(model, novelId, refresh, app)
  return { model, refresh, loadChapter, saveChapter, deleteChapter, rewriteChapter }
}

function studioCompleted(state: DocumentState, workflow: WorkflowViewState): boolean {
  const total = state.progress?.total_chapters || state.novel?.total_outline?.total_chapters || 0
  const current = workflow.currentChapter ?? state.progress?.current_chapter ?? 0
  const busy = ['running', 'paused', 'stalled', 'cancelling'].includes(workflow.status)
  return workflow.status === 'completed'
    || state.novel?.status === 'completed' || (!busy && total > 0 && current >= total)
}

function useEditorInteractions(
  model: DocumentModel,
  state: DocumentState,
  confirmDiscard: ReturnType<typeof useUnsavedChangesGuard>,
  loadChapter: (chapter: ChapterSummary) => Promise<void>,
  setStoredAutoMode: (value: boolean) => void,
) {
  const setEditor = useCallback((patch: Partial<DocumentState>) => {
    model.setState((current) => ({
      ...current,
      ...patch,
      saveFailed: patch.editorTitle !== undefined || patch.editorContent !== undefined ? false : current.saveFailed,
    }))
  }, [model])
  const changeAutoMode = useCallback((value: boolean) => setStoredAutoMode(value), [setStoredAutoMode])
  const openChapter = useCallback((chapter: ChapterSummary) => {
    if (chapter.id === state.selectedChapter?.id) { setEditor({ mobilePanel: 'editor' }); return }
    confirmDiscard(() => void loadChapter(chapter))
  }, [confirmDiscard, loadChapter, setEditor, state.selectedChapter?.id])
  return { setEditor, changeAutoMode, openChapter }
}

function planningEffectivelyEnabled(state: ReturnType<typeof useAuthStore.getState>): boolean {
  return Boolean(state.tenants.find((tenant) => tenant.id === state.currentTenantId)
    ?.novel_planning_v1_effective)
}


function usePlanningFeatureStatus(): boolean {
  const setTenants = useAuthStore((state) => state.setTenants)
  useEffect(() => {
    let active = true
    void tenantApi.list().then((tenants) => {
      if (active) setTenants(tenants)
    }).catch(() => undefined)
    return () => { active = false }
  }, [setTenants])
  return useAuthStore(planningEffectivelyEnabled)
}


export function useNovelStudioController(): NovelStudioController {
  const { novelId = '' } = useParams<{ novelId: string }>()
  const navigate = useNavigate()
  const app = App.useApp()
  const autoMode = useNovelStore((state) => state.autoMode)
  const setStoredAutoMode = useNovelStore((state) => state.setAutoMode)
  const planningEnabled = usePlanningFeatureStatus()
  const document = useStudioDocument(novelId, app, planningEnabled)
  const threadId = document.model.state.novel?.thread_id || novelId
  const workflow = useWorkflowStream(threadId)
  const [autoRunActive, setAutoRunActive] = useState(false)
  const lastInterruptRef = useRef<string | undefined>(undefined)
  const state = document.model.state
  const hasChanges = hasChapterChanges(state.selectedChapter, state.editorTitle, state.editorContent)
  const confirmDiscard = useDiscardGuard(hasChanges, app.modal)
  const recovery = recoveryDetails(workflow.state, state.progress)
  const isCompleted = studioCompleted(state, workflow.state)
  useAutoRunNotifications(autoRunActive, workflow.state, isCompleted, app.notification)
  const commands = useWorkflowCommands({
    workflow, novelId, novelType: state.novel?.novel_type || 'suspense', autoMode,
    recoverable: recovery.recoverable, setActive: setAutoRunActive,
    lastInterruptRef, refresh: document.refresh,
  })
  const gated = useSaveGate(hasChanges, document.saveChapter, app.modal)
  useControllerEffects(
    document.model, workflow, novelId, autoMode, autoRunActive, setAutoRunActive,
    lastInterruptRef, hasChanges, app.message, planningEnabled,
  )
  const interactions = useEditorInteractions(
    document.model, state, confirmDiscard, document.loadChapter, setStoredAutoMode,
  )
  return {
    novelId, document: state, workflow, autoMode, autoRunActive, isCompleted,
    canDelete: ['owner', 'admin'].includes(currentTenant()?.role || ''),
    hasUnsavedChanges: hasChanges, hasRecoverableCheckpoint: recovery.recoverable, planningEnabled,
    recoveryLabel: recovery.label, confirmDiscardChanges: confirmDiscard,
    refresh: document.refresh, openChapter: interactions.openChapter, saveChapter: document.saveChapter,
    deleteChapter: document.deleteChapter,
    rewriteChapter: () => confirmDiscard(document.rewriteChapter),
    startWriting: () => gated(commands.start),
    resumeWriting: (value) => gated(() => commands.resume(value)),
    continueAutoWriting: () => gated(commands.continueAuto),
    replanPlan: (request) => runPlanReplan(
      document.model, state.plan, request, gated, commands.replan,
    ),
    stopWriting: () => void commands.stop(), setAutoMode: interactions.changeAutoMode, setEditor: interactions.setEditor,
    goBack: () => confirmDiscard(() => navigate('/')),
    notifySyncError: () => app.message.error('暂时无法同步任务状态'),
  }
}
