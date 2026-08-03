import { App } from 'antd'
import axios from 'axios'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { novelApi } from '@/api/novel'
import { useWorkflowStream, type WorkflowViewState } from '@/hooks/useWorkflowStream'
import { useUnsavedChangesGuard, type DiscardConfirmation } from '@/hooks/useUnsavedChangesGuard'
import { currentTenant } from '@/stores/authStore'
import { useNovelStore } from '@/stores/novelStore'
import type { ChapterDetail, ChapterSummary, NovelResponse, ProgressResponse } from '@/types/novel'
import {
  autoResumeValue, hasChapterChanges, interruptKey, rewindImpactText, shouldAutoResume,
} from '../novelStudioUtils'

interface StudioLocationState { startInput?: Record<string, unknown> }
type AppContext = ReturnType<typeof App.useApp>

interface DocumentState {
  novel?: NovelResponse
  progress?: ProgressResponse
  chapters: ChapterSummary[]
  selectedChapter?: ChapterDetail
  editorTitle: string
  editorContent: string
  editorMode: 'read' | 'edit'
  mobilePanel: 'chapters' | 'editor' | 'workflow'
  loading: boolean
  saving: boolean
}

interface DocumentModel {
  state: DocumentState
  setState: React.Dispatch<React.SetStateAction<DocumentState>>
  selectedRef: React.MutableRefObject<ChapterDetail | undefined>
}

const initialDocumentState: DocumentState = {
  chapters: [], editorTitle: '', editorContent: '', editorMode: 'read',
  mobilePanel: 'editor', loading: true, saving: false,
}

function apiErrorCode(error: unknown): string | undefined {
  if (!axios.isAxiosError(error)) return undefined
  const payload = error.response?.data as { detail?: { code?: unknown } } | undefined
  return typeof payload?.detail?.code === 'string' ? payload.detail.code : undefined
}

function useDocumentModel(): DocumentModel {
  const [state, setState] = useState<DocumentState>(initialDocumentState)
  const selectedRef = useRef<ChapterDetail | undefined>(undefined)
  return { state, setState, selectedRef }
}

function applySelectedChapter(
  setState: DocumentModel['setState'],
  selectedRef: DocumentModel['selectedRef'],
  detail: ChapterDetail,
): void {
  selectedRef.current = detail
  setState((current) => ({
    ...current, selectedChapter: detail, editorTitle: detail.title,
    editorContent: detail.content, editorMode: 'read', mobilePanel: 'editor',
  }))
}

function useDocumentRefresh(
  model: DocumentModel,
  novelId: string,
  message: AppContext['message'],
) {
  const { setState, selectedRef } = model
  return useCallback(async () => {
    if (!novelId) return
    try {
      const [novel, progress, chapters] = await Promise.all([
        novelApi.get(novelId), novelApi.progress(novelId), novelApi.chapters(novelId),
      ])
      setState((current) => ({ ...current, novel, progress, chapters }))
      if (!selectedRef.current && chapters.length > 0) {
        applySelectedChapter(setState, selectedRef, await novelApi.chapter(novelId, chapters.at(-1)!.id))
      }
    } catch {
      message.error('无法载入稿件')
    } finally {
      setState((current) => ({ ...current, loading: false }))
    }
  }, [message, novelId, selectedRef, setState])
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
    setState((current) => ({ ...current, saving: true }))
    try {
      const updated = await novelApi.updateChapter(novelId, chapter.id, {
        title: editorTitle, content: editorContent,
        expected_version: chapter.version,
      })
      applySelectedChapter(setState, selectedRef, updated)
      app.message.success('章节已保存')
      if (updated.checkpoint_status === 'deferred') app.message.warning('正文已保存，创作现场将在服务恢复后重新同步')
      await refresh()
      return true
    } catch (error) {
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
    if (['idle', 'recoverable', 'error'].includes(status)) queueMicrotask(() => setActive(false))
  }, [setActive, status])
}

function useDetachedSync(workflow: ReturnType<typeof useWorkflowStream>): void {
  const { connection, status } = workflow.state
  useEffect(() => {
    if (connection !== 'detached' || !['running', 'stalled'].includes(status)) return
    const timer = window.setInterval(() => void workflow.sync().catch(() => undefined), 15_000)
    return () => window.clearInterval(timer)
  }, [connection, status, workflow])
}

function useInitialWorkflowSync(
  ready: boolean,
  sync: ReturnType<typeof useWorkflowStream>['sync'],
): void {
  useEffect(() => {
    if (ready) queueMicrotask(() => void sync().catch(() => undefined))
  }, [ready, sync])
}

async function fetchPersistedData(novelId: string, chapterId: string) {
  const [novel, progress, chapters, detail] = await Promise.all([
    novelApi.get(novelId), novelApi.progress(novelId), novelApi.chapters(novelId),
    novelApi.chapter(novelId, chapterId),
  ])
  return { novel, progress, chapters, detail }
}

function applyPersistedData(
  setState: DocumentModel['setState'],
  selectedRef: DocumentModel['selectedRef'],
  data: Awaited<ReturnType<typeof fetchPersistedData>>,
  keepEditor: boolean,
): void {
  setState((current) => ({ ...current, novel: data.novel, progress: data.progress, chapters: data.chapters }))
  if (!keepEditor) applySelectedChapter(setState, selectedRef, data.detail)
}

function usePersistedChapterSync(
  model: DocumentModel,
  novelId: string,
  chapterId: string | undefined,
  hasChanges: boolean,
  message: AppContext['message'],
): void {
  const handledRef = useRef<string | undefined>(undefined)
  const { selectedRef, setState } = model
  useEffect(() => {
    if (!chapterId || !novelId || handledRef.current === chapterId) return
    let active = true
    void fetchPersistedData(novelId, chapterId).then((data) => {
      if (!active) return
      handledRef.current = chapterId
      applyPersistedData(setState, selectedRef, data, hasChanges)
      if (hasChanges) message.warning('新章节已归档，当前未保存修改仍保留在编辑器中')
    }).catch(() => { if (active) message.warning('章节已保存，目录暂时未能刷新') })
    return () => { active = false }
  }, [chapterId, hasChanges, message, novelId, selectedRef, setState])
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
  const resume = useCallback((value: unknown) => {
    const interrupt = params.workflow.state.interrupt
    if (interrupt) setInterruptRef(params.lastInterruptRef, interruptKey(interrupt))
    params.setActive(params.autoMode)
    return params.workflow.resume(value, params.autoMode)
  }, [params])
  const continueAuto = useCallback(() => {
    const interrupt = params.workflow.state.interrupt
    if (!interrupt) return start()
    setInterruptRef(params.lastInterruptRef, interruptKey(interrupt))
    params.setActive(true)
    return params.workflow.resume(autoResumeValue(interrupt, params.novelType), true)
  }, [params, start])
  const stop = useCallback(async () => {
    params.setActive(false)
    await params.workflow.cancel()
    await params.refresh()
  }, [params])
  return { start, resume, continueAuto, stop }
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

/** 小说工作台视图所需的状态与操作。 */
export interface NovelStudioController {
  novelId: string
  document: DocumentState
  workflow: ReturnType<typeof useWorkflowStream>
  autoMode: boolean
  autoRunActive: boolean
  canDelete: boolean
  hasUnsavedChanges: boolean
  hasRecoverableCheckpoint: boolean
  recoveryLabel: string
  confirmDiscardChanges: ReturnType<typeof useUnsavedChangesGuard>
  refresh: () => Promise<void> | undefined
  openChapter: (chapter: ChapterSummary) => void
  saveChapter: () => Promise<boolean>
  deleteChapter: () => void
  startWriting: () => void
  resumeWriting: (value: unknown) => void
  continueAutoWriting: () => void
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
): void {
  useInitialWorkflowSync(Boolean(model.state.novel), workflow.sync)
  useInitialWorkflowStart(model.state.novel, autoMode, workflow.run, setActive)
  useAutoResume(workflow, model.state.novel?.novel_type || 'suspense', autoMode, active, lastInterruptRef)
  useAutoRunReset(workflow.state.status, setActive)
  useDetachedSync(workflow)
  usePersistedChapterSync(model, novelId, workflow.state.lastPersistedChapterId, hasChanges, message)
  useMetadataSync(model, workflow.state)
}

function useStudioDocument(novelId: string, app: AppContext) {
  const model = useDocumentModel()
  const refresh = useDocumentRefresh(model, novelId, app.message)
  useInitialRefresh(refresh)
  const loadChapter = useChapterLoader(model, novelId)
  const saveChapter = useChapterSave(model, novelId, refresh, app)
  const deleteChapter = useChapterDelete(model, novelId, refresh, app)
  return { model, refresh, loadChapter, saveChapter, deleteChapter }
}

export function useNovelStudioController(): NovelStudioController {
  const { novelId = '' } = useParams<{ novelId: string }>()
  const navigate = useNavigate()
  const app = App.useApp()
  const autoMode = useNovelStore((state) => state.autoMode)
  const setStoredAutoMode = useNovelStore((state) => state.setAutoMode)
  const document = useStudioDocument(novelId, app)
  const threadId = document.model.state.novel?.thread_id || novelId
  const workflow = useWorkflowStream(threadId)
  const [autoRunActive, setAutoRunActive] = useState(false)
  const lastInterruptRef = useRef<string | undefined>(undefined)
  const state = document.model.state
  const hasChanges = hasChapterChanges(state.selectedChapter, state.editorTitle, state.editorContent)
  const confirmDiscard = useDiscardGuard(hasChanges, app.modal)
  const recovery = recoveryDetails(workflow.state, state.progress)
  const commands = useWorkflowCommands({
    workflow, novelId, novelType: state.novel?.novel_type || 'suspense', autoMode,
    recoverable: recovery.recoverable, setActive: setAutoRunActive,
    lastInterruptRef, refresh: document.refresh,
  })
  const gated = useSaveGate(hasChanges, document.saveChapter, app.modal)
  useControllerEffects(document.model, workflow, novelId, autoMode, autoRunActive, setAutoRunActive, lastInterruptRef, hasChanges, app.message)
  const setEditor = useCallback((patch: Partial<DocumentState>) => {
    document.model.setState((current) => ({ ...current, ...patch }))
  }, [document.model])
  const changeAutoMode = useCallback((value: boolean) => {
    setStoredAutoMode(value)
    setAutoRunActive(value && workflow.state.status === 'running')
  }, [setStoredAutoMode, workflow.state.status])
  const openChapter = useCallback((chapter: ChapterSummary) => {
    if (chapter.id === state.selectedChapter?.id) { setEditor({ mobilePanel: 'editor' }); return }
    confirmDiscard(() => void document.loadChapter(chapter))
  }, [confirmDiscard, document, setEditor, state.selectedChapter?.id])
  return {
    novelId, document: state, workflow, autoMode, autoRunActive,
    canDelete: ['owner', 'admin'].includes(currentTenant()?.role || ''),
    hasUnsavedChanges: hasChanges, hasRecoverableCheckpoint: recovery.recoverable,
    recoveryLabel: recovery.label, confirmDiscardChanges: confirmDiscard,
    refresh: document.refresh, openChapter, saveChapter: document.saveChapter,
    deleteChapter: document.deleteChapter, startWriting: () => gated(commands.start),
    resumeWriting: (value) => gated(() => commands.resume(value)),
    continueAutoWriting: () => gated(commands.continueAuto),
    stopWriting: () => void commands.stop(), setAutoMode: changeAutoMode, setEditor,
    goBack: () => confirmDiscard(() => navigate('/')),
    notifySyncError: () => app.message.error('暂时无法同步任务状态'),
  }
}
