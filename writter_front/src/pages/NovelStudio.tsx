import { App, Button, Input, Progress, Segmented, Skeleton, Tooltip } from 'antd'
import {
  DeleteOutlined,
  EditOutlined,
  FileTextOutlined,
  HistoryOutlined,
  LeftOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SaveOutlined,
  StopOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { WorkflowPanel } from '@/components/WorkflowPanel'
import { novelApi, workflowApi } from '@/api/novel'
import { useWorkflowStream } from '@/hooks/useWorkflowStream'
import { useNovelStore } from '@/stores/novelStore'
import type { ChapterDetail, ChapterSummary, InterruptInfo, NovelResponse, ProgressResponse } from '@/types/novel'
import { currentTenant } from '@/stores/authStore'

interface StudioLocationState {
  startInput?: Record<string, unknown>
}

function autoResumeValue(interrupt: InterruptInfo, novelType: string): unknown {
  switch (interrupt.action) {
    case 'require_novel_type': return novelType
    case 'confirm_or_provide_title': return interrupt.ai_suggestions?.[0] || '未命名小说'
    case 'ready_for_next_chapter': return 'next'
    case 'review_reflection_issues': return 'revise'
    default: return 'accept'
  }
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
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [mobilePanel, setMobilePanel] = useState<'chapters' | 'editor' | 'workflow'>('editor')
  const startedRef = useRef(false)
  const autoInterruptRef = useRef<string | undefined>(undefined)
  const selectedChapterRef = useRef<ChapterDetail | undefined>(undefined)
  const threadId = novel?.thread_id || novelId
  const workflow = useWorkflowStream(threadId)
  const { state: workflowState, run, resume, cancel, hydrateInterrupt } = workflow

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
      }
      const snapshot = await workflowApi.state(novelData.thread_id || novelId)
      hydrateInterrupt(snapshot.interrupts[0])
    } catch {
      message.error('无法载入稿件')
    } finally {
      setLoading(false)
    }
  }, [hydrateInterrupt, message, novelId])

  useEffect(() => {
    queueMicrotask(() => void refresh())
  }, [refresh])

  useEffect(() => {
    const state = location.state as StudioLocationState | null
    if (!novel || !state?.startInput || startedRef.current) return
    startedRef.current = true
    void run({ input: { ...state.startInput, _auto_mode: autoMode } })
    window.history.replaceState({}, document.title)
  }, [autoMode, location.state, novel, run])

  useEffect(() => {
    const interrupt = workflowState.interrupt
    if (!autoMode || !interrupt) return
    const key = `${interrupt.action}-${interrupt.chapter_number ?? ''}`
    if (autoInterruptRef.current === key) return
    autoInterruptRef.current = key
    void resume(autoResumeValue(interrupt, novel?.novel_type || 'suspense'), true)
  }, [autoMode, novel?.novel_type, resume, workflowState.interrupt])

  const openChapter = async (chapter: ChapterSummary) => {
    const detail = await novelApi.chapter(novelId, chapter.id)
    selectedChapterRef.current = detail
    setSelectedChapter(detail)
    setEditorTitle(detail.title)
    setEditorContent(detail.content)
    setMobilePanel('editor')
  }

  const saveChapter = async () => {
    if (!selectedChapter) return
    setSaving(true)
    try {
      const updated = await novelApi.updateChapter(novelId, selectedChapter.id, {
        title: editorTitle,
        content: editorContent,
      })
      selectedChapterRef.current = updated
      setSelectedChapter(updated)
      message.success('章节已保存')
      await refresh()
    } finally {
      setSaving(false)
    }
  }

  const deleteChapter = () => {
    if (!selectedChapter) return
    modal.confirm({
      title: `删除《${selectedChapter.title}》？`,
      content: '进度会回退到该章节，关联记忆也会同步清理。',
      okText: '删除章节',
      okButtonProps: { danger: true },
      onOk: async () => {
        await novelApi.batchDeleteChapters(novelId, [selectedChapter.id])
        selectedChapterRef.current = undefined
        setSelectedChapter(undefined)
        await refresh()
      },
    })
  }

  const startWriting = () => run({
    input: { novel_id: novelId, novel_type: novel?.novel_type || 'suspense', _auto_mode: autoMode },
  })

  if (loading) return <AppShell><div className="studio-loading"><Skeleton active /></div></AppShell>
  if (!novel) return <AppShell><div className="studio-loading">稿件不存在</div></AppShell>

  const displayedContent = workflowState.draft || editorContent
  const isLiveDraft = Boolean(workflowState.draft)

  return (
    <AppShell>
      <div className="studio-page page-enter">
        <header className="studio-header">
          <Button type="text" icon={<LeftOutlined />} onClick={() => navigate('/')}>书架</Button>
          <div className="studio-title">
            <span>{novel.status === 'completed' ? '已完稿' : '创作中'}</span>
            <h1>{novel.title || '未命名作品'}</h1>
          </div>
          <div className="studio-actions">
            <Segmented
              value={autoMode ? 'auto' : 'manual'}
              onChange={(value) => setAutoMode(value === 'auto')}
              options={[{ label: '手动', value: 'manual' }, { label: '自动', value: 'auto' }]}
            />
            {workflowState.status === 'running' ? (
              <Button danger icon={<StopOutlined />} onClick={() => void cancel()}>停止</Button>
            ) : workflowState.status === 'error' && workflowState.retryable ? (
              <Button type="primary" icon={<ReloadOutlined />} onClick={() => void startWriting()}>重试当前步骤</Button>
            ) : (
              <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => void startWriting()}>继续创作</Button>
            )}
          </div>
        </header>

        <div className="studio-progress">
          <span>第 {progress?.current_chapter || 0} / {progress?.total_chapters || novel.total_outline?.total_chapters || 0} 章</span>
          <Progress percent={Math.round(progress?.percentage || workflowState.progress || 0)} showInfo={false} strokeColor="#176b5b" />
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
                  <button onClick={() => void openChapter(chapter)}>
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
                ) : (
                  <Input value={editorTitle} onChange={(event) => setEditorTitle(event.target.value)} bordered={false} />
                )}
              </div>
              {!isLiveDraft && selectedChapter && (
                <div>
                  {canDelete && <Tooltip title="删除章节"><Button danger type="text" icon={<DeleteOutlined />} onClick={deleteChapter} /></Tooltip>}
                  <Button icon={<SaveOutlined />} loading={saving} onClick={() => void saveChapter()}>保存</Button>
                </div>
              )}
            </div>
            {displayedContent ? (
              <Input.TextArea
                className="manuscript-editor"
                value={displayedContent}
                readOnly={isLiveDraft}
                onChange={(event) => setEditorContent(event.target.value)}
                autoSize={false}
              />
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
            autoMode={autoMode}
            onResume={(value) => void resume(value, autoMode)}
          />
        </div>
      </div>
    </AppShell>
  )
}
