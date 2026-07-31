import { App, Button, Input, Progress, Segmented, Skeleton, Tooltip } from 'antd'
import axios from 'axios'
import {
  EditOutlined,
  FileTextOutlined,
  HistoryOutlined,
  LeftOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SaveOutlined,
  StopOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { MarkdownManuscript } from '@/components/MarkdownManuscript'
import { WorkflowPanel } from '@/components/WorkflowPanel'
import { novelApi, workflowApi } from '@/api/novel'
import { useWorkflowStream } from '@/hooks/useWorkflowStream'
import { useUnsavedChangesGuard, type DiscardConfirmation } from '@/hooks/useUnsavedChangesGuard'
import { useNovelStore } from '@/stores/novelStore'
import type { ChapterDetail, ChapterSummary, NovelResponse, ProgressResponse } from '@/types/novel'
import { currentTenant } from '@/stores/authStore'
import {
  autoResumeValue,
  hasChapterChanges,
  interruptKey,
  rewindImpactText,
  shouldAutoResume,
} from './novelStudioUtils'

interface StudioLocationState {
  startInput?: Record<string, unknown>
}

function apiErrorCode(error: unknown): string | undefined {
  if (!axios.isAxiosError(error)) return undefined
  const payload = error.response?.data as { detail?: { code?: unknown } } | undefined
  return typeof payload?.detail?.code === 'string' ? payload.detail.code : undefined
}

export default function NovelStudio() {
  const { novelId = '' } = useParams<{ novelId: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const { message, modal } = App.useApp()
  const autoMode = useNovelStore((state) => state.autoMode)
  const canDelete = ['owner', 'admin'].includes(currentTenant()?.role || '')
  const setAutoMode = useNovelStore((state) => state.setAutoMode)
  const [novel, setNovel] = useState<NovelResponse>()
  const [progress, setProgress] = useState<ProgressResponse>()
  const [chapters, setChapters] = useState<ChapterSummary[]>([])
  const [selectedChapter, setSelectedChapter] = useState<ChapterDetail>()
  const [editorTitle, setEditorTitle] = useState('')
  const [editorContent, setEditorContent] = useState('')
  const [editorMode, setEditorMode] = useState<'read' | 'edit'>('read')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [autoRunActive, setAutoRunActive] = useState(false)
  const [mobilePanel, setMobilePanel] = useState<'chapters' | 'editor' | 'workflow'>('editor')
  const startedRef = useRef(false)
  const autoInterruptRef = useRef<string | undefined>(undefined)
  const handledPersistedChapterRef = useRef<string | undefined>(undefined)
  const selectedChapterRef = useRef<ChapterDetail | undefined>(undefined)
  const threadId = novel?.thread_id || novelId
  const workflow = useWorkflowStream(threadId)
  const { state: workflowState, run, retry, resume, cancel, sync, hydrateSnapshot } = workflow
  const previousWorkflowStatusRef = useRef(workflowState.status)
  const hasUnsavedChanges = hasChapterChanges(selectedChapter, editorTitle, editorContent)

  const requestDiscardConfirmation = useCallback<DiscardConfirmation>((onConfirm, onCancel) => {
    modal.confirm({
      title: '有未保存的修改',
      content: '离开后，本次修改将无法恢复。',
      okText: '放弃修改并离开',
      cancelText: '继续编辑',
      okButtonProps: { danger: true },
      onOk: onConfirm,
      onCancel,
    })
  }, [modal])
  const confirmDiscardChanges = useUnsavedChangesGuard(hasUnsavedChanges, requestDiscardConfirmation)

  const refresh = useCallback(async () => {
    if (!novelId) return
    try {
      const [novelData, progressData, chapterData] = await Promise.all([
        novelApi.get(novelId), novelApi.progress(novelId), novelApi.chapters(novelId),
      ])
      setNovel(novelData)
      setProgress(progressData)
      setChapters(chapterData)
      if (!selectedChapterRef.current && chapterData.length > 0) {
        const latest = await novelApi.chapter(novelId, chapterData.at(-1)!.id)
        selectedChapterRef.current = latest
        setSelectedChapter(latest)
        setEditorTitle(latest.title)
        setEditorContent(latest.content)
        setEditorMode('read')
      }
      const snapshot = await workflowApi.state(novelData.thread_id || novelId)
      hydrateSnapshot(snapshot)
    } catch {
      message.error('无法载入稿件')
    } finally {
      setLoading(false)
    }
  }, [hydrateSnapshot, message, novelId])

  useEffect(() => {
    queueMicrotask(() => void refresh())
  }, [refresh])

  useEffect(() => {
    const state = location.state as StudioLocationState | null
    if (!novel || !state?.startInput || startedRef.current) return
    startedRef.current = true
    setAutoRunActive(autoMode)
    void run({ input: { ...state.startInput, _auto_mode: autoMode } })
    void navigate(location.pathname, { replace: true, state: null })
  }, [autoMode, location.pathname, location.state, navigate, novel, run])

  useEffect(() => {
    const interrupt = workflowState.interrupt
    if (!interrupt || !shouldAutoResume(autoMode, autoRunActive, interrupt, autoInterruptRef.current)) return
    const key = interruptKey(interrupt)
    autoInterruptRef.current = key
    void resume(autoResumeValue(interrupt, novel?.novel_type || 'suspense'), true)
  }, [autoMode, autoRunActive, novel?.novel_type, resume, workflowState.interrupt])

  useEffect(() => {
    const previousStatus = previousWorkflowStatusRef.current
    previousWorkflowStatusRef.current = workflowState.status
    if (!['running', 'paused', 'stalled', 'cancelling'].includes(previousStatus)) return
    if (!['idle', 'recoverable', 'error'].includes(workflowState.status)) return
    queueMicrotask(() => setAutoRunActive(false))
  }, [workflowState.status])

  useEffect(() => {
    if (workflowState.connection !== 'detached' || !['running', 'stalled'].includes(workflowState.status)) return
    const refreshState = () => void sync().catch(() => undefined)
    const timer = window.setInterval(refreshState, 15_000)
    return () => window.clearInterval(timer)
  }, [sync, workflowState.connection, workflowState.status])

  useEffect(() => {
    const chapterId = workflowState.lastPersistedChapterId
    if (!chapterId || !novelId || handledPersistedChapterRef.current === chapterId) return
    let active = true
    const syncPersistedChapter = async () => {
      try {
        const [novelData, progressData, chapterData, detail] = await Promise.all([
          novelApi.get(novelId),
          novelApi.progress(novelId),
          novelApi.chapters(novelId),
          novelApi.chapter(novelId, chapterId),
        ])
        if (!active) return
        handledPersistedChapterRef.current = chapterId
        setNovel(novelData)
        setProgress(progressData)
        setChapters(chapterData)
        if (hasUnsavedChanges) {
          message.warning('新章节已归档，当前未保存修改仍保留在编辑器中')
          return
        }
        selectedChapterRef.current = detail
        setSelectedChapter(detail)
        setEditorTitle(detail.title)
        setEditorContent(detail.content)
        setEditorMode('read')
      } catch {
        if (active) message.warning('章节已保存，目录暂时未能刷新')
      }
    }
    void syncPersistedChapter()
    return () => { active = false }
  }, [hasUnsavedChanges, message, novelId, workflowState.lastPersistedChapterId])

  const loadChapter = async (chapter: ChapterSummary) => {
    const detail = await novelApi.chapter(novelId, chapter.id)
    selectedChapterRef.current = detail
    setSelectedChapter(detail)
    setEditorTitle(detail.title)
    setEditorContent(detail.content)
    setEditorMode('read')
    setMobilePanel('editor')
  }

  const openChapter = (chapter: ChapterSummary) => {
    if (chapter.id === selectedChapter?.id) {
      setMobilePanel('editor')
      return
    }
    confirmDiscardChanges(() => loadChapter(chapter))
  }

  const saveChapter = async () => {
    if (!selectedChapter) return false
    setSaving(true)
    try {
      const updated = await novelApi.updateChapter(novelId, selectedChapter.id, {
        title: editorTitle,
        content: editorContent,
        expected_version: selectedChapter.version,
      })
      selectedChapterRef.current = updated
      setSelectedChapter(updated)
      setEditorMode('read')
      message.success('章节已保存')
      if (updated.checkpoint_status === 'deferred') {
        message.warning('正文已保存，创作现场将在服务恢复后重新同步')
      }
      await refresh()
      return true
    } catch (error) {
      const errorCode = apiErrorCode(error)
      if (errorCode !== 'chapter_version_conflict') {
        message.error(errorCode === 'novel_busy' ? '作品正在生成，请结束任务后再编辑' : '章节保存失败，请稍后重试')
        return false
      }
      modal.confirm({
        title: '章节已在其他窗口更新',
        content: '当前编辑内容仍会保留。载入最新版后，本地未保存内容将被替换。',
        okText: '载入最新版',
        cancelText: '保留本地内容',
        onOk: () => void loadChapter(selectedChapter),
      })
      return false
    } finally {
      setSaving(false)
    }
  }

  const deleteChapter = () => {
    if (!selectedChapter) return
    const rewindCount = chapters.filter(
      (chapter) => chapter.chapter_index >= selectedChapter.chapter_index,
    ).length || 1
    modal.confirm({
      title: `从第 ${selectedChapter.chapter_index + 1} 章重新创作？`,
      content: rewindImpactText(selectedChapter, chapters),
      okText: `删除 ${rewindCount} 章并回退`,
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const result = await novelApi.batchDeleteChapters(novelId, [selectedChapter.id])
          selectedChapterRef.current = undefined
          setSelectedChapter(undefined)
          await refresh()
          message.success(`已删除 ${result.count} 章，下次将从第 ${selectedChapter.chapter_index + 1} 章重新创作`)
          if (result.checkpoint_status === 'deferred') {
            message.warning('正文已回退，创作现场将在服务恢复后重新同步')
          }
        } catch (error) {
          message.error(apiErrorCode(error) === 'novel_busy' ? '作品正在生成，暂时无法回退' : '章节回退失败')
          throw error
        }
      },
    })
  }

  const hasRecoverableCheckpoint = Boolean(
    workflowState.hasCheckpointDraft || workflowState.hasPendingCheckpoint,
  )
  const recoveryChapterNumber = (
    workflowState.checkpointChapterIndex
    ?? workflowState.currentChapter
    ?? progress?.current_chapter
    ?? 0
  ) + 1
  const isReflectionRecovery = workflowState.hasCheckpointDraft
    || workflowState.activeNode === 'reflection_node'
  const recoveryLabel = isReflectionRecovery
    ? `${workflowState.status === 'error' ? '重试' : '继续'}第 ${recoveryChapterNumber} 章质量审读`
    : workflowState.status === 'error'
      ? '重试当前步骤'
      : `从第 ${recoveryChapterNumber} 章继续`
  const startWriting = () => {
    autoInterruptRef.current = undefined
    setAutoRunActive(autoMode)
    return workflowState.retryable || hasRecoverableCheckpoint
      ? retry(autoMode)
      : run({
        input: { novel_id: novelId, novel_type: novel?.novel_type || 'suspense', _auto_mode: autoMode },
      })
  }

  const resumeWriting = (value: unknown) => {
    if (workflowState.interrupt) autoInterruptRef.current = interruptKey(workflowState.interrupt)
    setAutoRunActive(autoMode)
    return resume(value, autoMode)
  }

  const continueAutoWriting = () => {
    const interrupt = workflowState.interrupt
    if (!interrupt) return startWriting()
    autoInterruptRef.current = interruptKey(interrupt)
    setAutoRunActive(true)
    return resume(autoResumeValue(interrupt, novel?.novel_type || 'suspense'), true)
  }

  const runAfterSaving = (action: () => void | Promise<void>) => {
    if (!hasUnsavedChanges) {
      void action()
      return
    }
    modal.confirm({
      title: '先保存当前修改？',
      content: '继续创作后，AI 可能生成并打开新章节。请先保存当前修改，避免内容丢失。',
      okText: '保存并继续',
      cancelText: '继续编辑',
      onOk: async () => {
        if (await saveChapter()) return action()
      },
    })
  }

  const stopWriting = async () => {
    setAutoRunActive(false)
    await cancel()
    await refresh()
  }

  if (loading) return <AppShell><div className="studio-loading"><Skeleton active /></div></AppShell>
  if (!novel) return <AppShell><div className="studio-loading">稿件不存在</div></AppShell>

  const displayedContent = workflowState.draft || editorContent
  const isLiveDraft = Boolean(workflowState.draft)
  const isBusy = ['running', 'stalled', 'cancelling'].includes(workflowState.status)
  const isEditing = !isLiveDraft && editorMode === 'edit'

  return (
    <AppShell onBeforeNavigate={confirmDiscardChanges}>
      <div className="studio-page page-enter">
        <header className="studio-header">
          <Button type="text" icon={<LeftOutlined />} onClick={() => confirmDiscardChanges(() => navigate('/'))}>书架</Button>
          <div className="studio-title">
            <span>{novel.status === 'completed' ? '已完稿' : '创作中'}</span>
            <h1>{novel.title || '未命名作品'}</h1>
          </div>
          <div className="studio-actions">
            <Segmented
              value={autoMode ? 'auto' : 'manual'}
              onChange={(value) => {
                const nextAutoMode = value === 'auto'
                setAutoMode(nextAutoMode)
                setAutoRunActive(nextAutoMode && workflowState.status === 'running')
              }}
              options={[{ label: '手动', value: 'manual' }, { label: '自动', value: 'auto' }]}
            />
            {isBusy ? (
              <Button danger icon={<StopOutlined />} loading={workflowState.status === 'cancelling'} onClick={() => void stopWriting()}>停止</Button>
            ) : workflowState.status === 'paused' && autoMode && !autoRunActive ? (
              <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => runAfterSaving(() => continueAutoWriting())}>
                继续自动创作
              </Button>
            ) : workflowState.status === 'paused' ? (
              <Button icon={<PauseCircleOutlined />} onClick={() => setMobilePanel('workflow')}>等待确认</Button>
            ) : workflowState.status === 'error' && workflowState.retryable ? (
              <Button type="primary" icon={<ReloadOutlined />} onClick={() => runAfterSaving(() => startWriting())}>{recoveryLabel}</Button>
            ) : hasRecoverableCheckpoint ? (
              <Button type="primary" icon={<ReloadOutlined />} onClick={() => runAfterSaving(() => startWriting())}>
                {recoveryLabel}
              </Button>
            ) : (
              <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => runAfterSaving(() => startWriting())}>继续创作</Button>
            )}
          </div>
        </header>

        <div className="studio-progress">
          <span>第 {workflowState.currentChapter ?? progress?.current_chapter ?? 0} / {progress?.total_chapters || novel.total_outline?.total_chapters || 0} 章</span>
          <Progress percent={Math.round(workflowState.progress ?? progress?.percentage ?? 0)} showInfo={false} strokeColor="#176b5b" />
        </div>

        <div className="studio-mobile-tabs" role="tablist" aria-label="创作台视图">
          <button type="button" role="tab" aria-selected={mobilePanel === 'chapters'} className={mobilePanel === 'chapters' ? 'active' : ''} onClick={() => setMobilePanel('chapters')}>
            <UnorderedListOutlined />目录
          </button>
          <button type="button" role="tab" aria-selected={mobilePanel === 'editor'} className={mobilePanel === 'editor' ? 'active' : ''} onClick={() => setMobilePanel('editor')}>
            <FileTextOutlined />正文
          </button>
          <button type="button" role="tab" aria-selected={mobilePanel === 'workflow'} className={mobilePanel === 'workflow' ? 'active' : ''} onClick={() => setMobilePanel('workflow')}>
            <HistoryOutlined />执行
          </button>
        </div>

        <div className="studio-grid">
          <aside className={`manuscript-panel studio-pane ${mobilePanel === 'chapters' ? 'mobile-active' : ''}`}>
            <div className="panel-heading">
              <div><span className="eyebrow">Manuscript</span><h2>章节目录</h2></div>
              <Tooltip title="刷新目录"><Button type="text" icon={<ReloadOutlined />} onClick={() => void refresh()} /></Tooltip>
            </div>
            <ol className="chapter-list">
              {chapters.map((chapter) => (
                <li key={chapter.id} className={selectedChapter?.id === chapter.id ? 'active' : ''}>
                  <button onClick={() => openChapter(chapter)}>
                    <span>{String(chapter.chapter_index + 1).padStart(2, '0')}</span>
                    <div><strong>{chapter.title}</strong><small>{chapter.word_count.toLocaleString()} 字</small></div>
                  </button>
                </li>
              ))}
              {chapters.length === 0 && <li className="chapter-empty">章节将在这里归档</li>}
            </ol>
          </aside>

          <section className={`editor-panel studio-pane ${mobilePanel === 'editor' ? 'mobile-active' : ''}`}>
            <div className="editor-toolbar">
              <div>
                <span className="eyebrow">{isLiveDraft ? 'Live Draft' : 'Chapter Editor'}</span>
                {isLiveDraft ? (
                  <h2>AI 正在撰写第 {progress?.current_chapter ? progress.current_chapter + 1 : 1} 章</h2>
                ) : isEditing ? (
                  <Input value={editorTitle} onChange={(event) => setEditorTitle(event.target.value)} variant="borderless" />
                ) : (
                  <h2>{editorTitle || '未命名章节'}</h2>
                )}
              </div>
              {!isLiveDraft && selectedChapter && (
                <div className="editor-actions">
                  <Segmented
                    size="small"
                    disabled={isBusy}
                    value={editorMode}
                    onChange={(value) => setEditorMode(value as 'read' | 'edit')}
                    options={[{ label: '阅读', value: 'read' }, { label: '编辑', value: 'edit' }]}
                    aria-label="章节查看模式"
                  />
                  {hasUnsavedChanges && <span className="editor-dirty-indicator">未保存</span>}
                  {canDelete && <Tooltip title="从本章重新创作"><Button danger type="text" aria-label="从本章重新创作" icon={<HistoryOutlined />} onClick={deleteChapter} /></Tooltip>}
                  {isEditing && <Button icon={<SaveOutlined />} loading={saving} disabled={!hasUnsavedChanges} onClick={() => void saveChapter()}>保存</Button>}
                </div>
              )}
            </div>
            {displayedContent ? (
              isEditing ? (
                <Input.TextArea
                  className="manuscript-editor"
                  value={editorContent}
                  onChange={(event) => setEditorContent(event.target.value)}
                  onKeyDown={(event) => {
                    if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 's') return
                    event.preventDefault()
                    if (hasUnsavedChanges) void saveChapter()
                  }}
                  autoSize={false}
                />
              ) : (
                <MarkdownManuscript content={displayedContent} live={isLiveDraft} />
              )
            ) : (
              <div className="blank-page">
                <EditOutlined />
                <h2>稿纸已经铺好</h2>
                <p>点击“继续创作”，或从左侧选择已经完成的章节。</p>
              </div>
            )}
          </section>

          <WorkflowPanel
            className={`studio-pane ${mobilePanel === 'workflow' ? 'mobile-active' : ''}`}
            state={workflowState}
            autoMode={autoMode && autoRunActive}
            onResume={(value) => runAfterSaving(() => resumeWriting(value))}
            onRetry={() => runAfterSaving(() => startWriting())}
            onCancel={() => void stopWriting()}
            onRefresh={() => void sync().catch(() => message.error('暂时无法同步任务状态'))}
          />
        </div>
      </div>
    </AppShell>
  )
}
