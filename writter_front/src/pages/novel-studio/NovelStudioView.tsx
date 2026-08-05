import { Button, Dropdown, Input, Progress, Segmented, Tooltip, type MenuProps } from 'antd'
import {
  EditOutlined, FileDoneOutlined, FileTextOutlined, HistoryOutlined, LeftOutlined, MoreOutlined, PauseCircleOutlined,
  PlayCircleOutlined, ReloadOutlined, SaveOutlined, StopOutlined, UnorderedListOutlined,
} from '@ant-design/icons'
import { MarkdownManuscript } from '@/components/MarkdownManuscript'
import { WorkflowPanel } from '@/components/WorkflowPanel'
import { qualityScoreOutOfFive } from '@/components/workflow/presentation'
import type { ChapterSummary } from '@/types/novel'
import type { NovelStudioController } from './useNovelStudioController'

function WorkflowAction({ controller }: { controller: NovelStudioController }) {
  const { workflow, autoMode, autoRunActive } = controller
  const status = workflow.state.status
  const busy = ['running', 'stalled', 'cancelling'].includes(status)
  if (controller.isCompleted) return (
    <Button type="primary" icon={<FileDoneOutlined />} onClick={() => controller.setEditor({ mobilePanel: 'editor' })}>查看完稿</Button>
  )
  if (busy) return (
    <Button danger icon={<StopOutlined />} loading={status === 'cancelling'} onClick={controller.stopWriting}>停止</Button>
  )
  if (status === 'paused' && autoMode && !autoRunActive) return (
    <Button type="primary" icon={<PlayCircleOutlined />} onClick={controller.continueAutoWriting}>继续自动创作</Button>
  )
  if (status === 'paused') return (
    <Button icon={<PauseCircleOutlined />} onClick={() => controller.setEditor({ mobilePanel: 'workflow' })}>等待确认</Button>
  )
  if ((status === 'error' && workflow.state.retryable) || controller.hasRecoverableCheckpoint) return (
    <Button type="primary" icon={<ReloadOutlined />} onClick={controller.startWriting}>{controller.recoveryLabel}</Button>
  )
  return <Button type="primary" icon={<PlayCircleOutlined />} onClick={controller.startWriting}>继续创作</Button>
}

function StudioHeader({ controller }: { controller: NovelStudioController }) {
  const { novel } = controller.document
  return (
    <header className="studio-header">
      <Button type="text" icon={<LeftOutlined />} onClick={controller.goBack}>书架</Button>
      <div className="studio-title">
        <span>{controller.isCompleted ? '已完稿' : '创作中'}</span>
        <h1>{novel?.title || '未命名作品'}</h1>
      </div>
      <div className="studio-actions">
        <Segmented
          value={controller.autoMode ? 'auto' : 'manual'}
          onChange={(value) => controller.setAutoMode(value === 'auto')}
          options={[{ label: '逐步确认', value: 'manual' }, { label: '自动推进', value: 'auto' }]}
        />
        <WorkflowAction controller={controller} />
      </div>
    </header>
  )
}

function StudioProgress({ controller }: { controller: NovelStudioController }) {
  const { progress, novel } = controller.document
  const state = controller.workflow.state
  const current = state.currentChapter ?? progress?.current_chapter ?? 0
  const total = progress?.total_chapters || novel?.total_outline?.total_chapters || 0
  return (
    <div className="studio-progress">
      <span>第 {current} / {total} 章</span>
      <Progress percent={Math.round(state.progress ?? progress?.percentage ?? 0)} showInfo={false} strokeColor="#176b5b" />
    </div>
  )
}

const mobileTabs = [
  { value: 'chapters', label: '目录', icon: <UnorderedListOutlined /> },
  { value: 'editor', label: '正文', icon: <FileTextOutlined /> },
  { value: 'workflow', label: '执行', icon: <HistoryOutlined /> },
] as const

function StudioMobileTabs({ controller }: { controller: NovelStudioController }) {
  const current = controller.document.mobilePanel
  return (
    <div className="studio-mobile-tabs" role="tablist" aria-label="创作台视图">
      {mobileTabs.map((tab) => (
        <button
          key={tab.value} type="button" role="tab" aria-selected={current === tab.value}
          className={current === tab.value ? 'active' : ''}
          onClick={() => controller.setEditor({ mobilePanel: tab.value })}
        >
          {tab.icon}{tab.label}
        </button>
      ))}
    </div>
  )
}

function ChapterItem({ chapter, controller }: { chapter: ChapterSummary; controller: NovelStudioController }) {
  const selected = controller.document.selectedChapter?.id === chapter.id
  return (
    <li className={selected ? 'active' : ''}>
      <button onClick={() => controller.openChapter(chapter)}>
        <span>{String(chapter.chapter_index + 1).padStart(2, '0')}</span>
        <div><strong>{chapter.title}</strong><ChapterReviewMeta chapter={chapter} /></div>
      </button>
    </li>
  )
}

function ChapterReviewMeta({ chapter }: { chapter: ChapterSummary }) {
  const score = chapter.quality_score == null
    ? undefined : `${qualityScoreOutOfFive(chapter.quality_score).toFixed(1)} / 5`
  if (chapter.review_status === 'accepted_unreviewed') return (
    <small><span>{chapter.word_count.toLocaleString()} 字</span><b className="review-badge warning">未审读</b></small>
  )
  if (chapter.review_status === 'accepted_with_issues') return (
    <small><span>{chapter.word_count.toLocaleString()} 字</span><b className="review-badge issue">带问题通过{score ? ` · ${score}` : ''}</b></small>
  )
  if (chapter.review_status === 'unknown') return (
    <small><span>{chapter.word_count.toLocaleString()} 字</span><Tooltip title="章节已归档，但历史审读元数据不可用"><b className="review-badge muted">审读记录缺失</b></Tooltip></small>
  )
  return <small><span>{chapter.word_count.toLocaleString()} 字</span>{score && <b className="review-score">{score}</b>}</small>
}

function CompletionSummary({ controller }: { controller: NovelStudioController }) {
  if (!controller.isCompleted) return null
  const chapters = controller.document.chapters
  const words = chapters.reduce((total, chapter) => total + chapter.word_count, 0)
  const unreviewed = chapters.filter((chapter) => chapter.review_status === 'accepted_unreviewed').length
  const unknown = chapters.filter((chapter) => chapter.review_status === 'unknown').length
  return (
    <section className="completion-summary" aria-label="完稿摘要">
      <FileDoneOutlined />
      <div><strong>完稿摘要</strong><span>{chapters.length} 章 · {words.toLocaleString()} 字</span></div>
      <div className="completion-generation-status"><b>生成完成</b></div>
      <div className="completion-review-status">
        {unreviewed > 0 && <b className="review-badge warning">未审读 {unreviewed} 章</b>}
        {unknown > 0 && <Tooltip title="章节已归档，但历史审读元数据不可用"><b className="review-badge muted">审读记录缺失 {unknown} 章</b></Tooltip>}
        {!unreviewed && !unknown && <span>全部章节已完成审读</span>}
      </div>
    </section>
  )
}

function ChapterSidebar({ controller }: { controller: NovelStudioController }) {
  const { chapters, mobilePanel } = controller.document
  return (
    <aside className={`manuscript-panel studio-pane ${mobilePanel === 'chapters' ? 'mobile-active' : ''}`}>
      <div className="panel-heading">
        <div><span className="eyebrow">Manuscript</span><h2>章节目录</h2></div>
        <Tooltip title="刷新目录">
          <Button type="text" icon={<ReloadOutlined />} onClick={() => void controller.refresh()} />
        </Tooltip>
      </div>
      <ol className="chapter-list">
        {chapters.map((chapter) => <ChapterItem key={chapter.id} chapter={chapter} controller={controller} />)}
        {chapters.length === 0 && <li className="chapter-empty">章节将在这里归档</li>}
      </ol>
    </aside>
  )
}

function EditorSaveStatus({ controller }: { controller: NovelStudioController }) {
  const { saving, saveFailed, lastSavedAt } = controller.document
  const savedTime = lastSavedAt
    ? new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date(lastSavedAt))
    : undefined
  if (saving) return <span className="editor-save-status">保存中</span>
  if (saveFailed) return <button type="button" className="editor-save-status failed" onClick={() => void controller.saveChapter()}>保存失败，重试</button>
  if (controller.hasUnsavedChanges) return <span className="editor-save-status dirty">有未保存修改</span>
  return <span className="editor-save-status">已保存{savedTime ? ` · ${savedTime}` : ''}</span>
}

function EditorActions({ controller }: { controller: NovelStudioController }) {
  const { selectedChapter, editorMode } = controller.document
  const busy = controller.document.rewriting
    || ['running', 'stalled', 'cancelling'].includes(controller.workflow.state.status)
  if (!selectedChapter) return null
  const chapterActionMenu: MenuProps = {
    items: [
      { key: 'rewrite', icon: <ReloadOutlined />, label: 'AI 重写本章', disabled: busy },
      ...(controller.canDelete
        ? [{ key: 'rewind', icon: <HistoryOutlined />, label: '从本章重新创作', danger: true, disabled: busy }]
        : []),
    ],
    onClick: ({ key }) => {
      if (key === 'rewrite') controller.rewriteChapter()
      if (key === 'rewind') controller.deleteChapter()
    },
  }
  return (
    <div className="editor-actions">
      <Segmented
        size="small" disabled={busy} value={editorMode}
        onChange={(value) => controller.setEditor({ editorMode: value as 'read' | 'edit' })}
        options={[{ label: '阅读', value: 'read' }, { label: '编辑', value: 'edit' }]}
        aria-label="章节查看模式"
      />
      <EditorSaveStatus controller={controller} />
      <div className="desktop-chapter-actions">
        <Tooltip title="AI 重写本章">
          <Button type="text" aria-label="AI 重写本章" icon={<ReloadOutlined />} disabled={busy} loading={controller.document.rewriting} onClick={controller.rewriteChapter} />
        </Tooltip>
        {controller.canDelete && (
          <Tooltip title="从本章重新创作">
            <Button danger disabled={busy} type="text" aria-label="从本章重新创作" icon={<HistoryOutlined />} onClick={controller.deleteChapter} />
          </Tooltip>
        )}
      </div>
      <Dropdown menu={chapterActionMenu} trigger={['click']}>
        <Button className="mobile-chapter-actions" aria-label="章节操作" icon={<MoreOutlined />} disabled={busy}>章节操作</Button>
      </Dropdown>
      {editorMode === 'edit' && (
        <Button icon={<SaveOutlined />} loading={controller.document.saving} disabled={!controller.hasUnsavedChanges} onClick={() => void controller.saveChapter()}>保存</Button>
      )}
    </div>
  )
}

function EditorToolbar({ controller, live }: { controller: NovelStudioController; live: boolean }) {
  const { editorMode, editorTitle, progress } = controller.document
  return (
    <div className="editor-toolbar">
      <div>
        <span className="eyebrow">{live ? 'Live Draft' : 'Chapter Editor'}</span>
        {live ? (
          <h2>AI 正在撰写第 {progress?.current_chapter ? progress.current_chapter + 1 : 1} 章</h2>
        ) : editorMode === 'edit' ? (
          <Input value={editorTitle} onChange={(event) => controller.setEditor({ editorTitle: event.target.value })} variant="borderless" />
        ) : <h2>{editorTitle || '未命名章节'}</h2>}
      </div>
      {!live && <EditorActions controller={controller} />}
    </div>
  )
}

function EmptyEditor() {
  return (
    <div className="blank-page">
      <EditOutlined />
      <h2>稿纸已经铺好</h2>
      <p>点击“继续创作”，或从左侧选择已经完成的章节。</p>
    </div>
  )
}

function EditorBody({ controller, live }: { controller: NovelStudioController; live: boolean }) {
  const { editorContent, editorMode } = controller.document
  const content = controller.workflow.state.draft || editorContent
  if (!content) return <EmptyEditor />
  if (!live && editorMode === 'edit') return (
    <Input.TextArea
      className="manuscript-editor" value={editorContent} autoSize={false}
      onChange={(event) => controller.setEditor({ editorContent: event.target.value })}
      onKeyDown={(event) => {
        if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 's') return
        event.preventDefault()
        if (controller.hasUnsavedChanges) void controller.saveChapter()
      }}
    />
  )
  return <MarkdownManuscript content={content} live={live} />
}

function ChapterEditor({ controller }: { controller: NovelStudioController }) {
  const live = Boolean(controller.workflow.state.draft)
  const active = controller.document.mobilePanel === 'editor' ? 'mobile-active' : ''
  return (
    <section className={`editor-panel studio-pane ${active}`}>
      <EditorToolbar controller={controller} live={live} />
      <EditorBody controller={controller} live={live} />
    </section>
  )
}

function WorkflowSidebar({ controller }: { controller: NovelStudioController }) {
  const workflow = controller.workflow
  const active = controller.document.mobilePanel === 'workflow' ? 'mobile-active' : ''
  const state = controller.isCompleted && workflow.state.status === 'idle'
    ? { ...workflow.state, status: 'completed' as const } : workflow.state
  return (
    <WorkflowPanel
      className={`studio-pane ${active}`} state={state}
      autoMode={controller.autoMode && controller.autoRunActive}
      onResume={controller.resumeWriting} onRetry={controller.startWriting}
      onCancel={controller.stopWriting}
      onRefresh={() => void workflow.sync().catch(controller.notifySyncError)}
    />
  )
}

export function NovelStudioView({ controller }: { controller: NovelStudioController }) {
  return (
    <div className="studio-page page-enter">
      <StudioHeader controller={controller} />
      <StudioProgress controller={controller} />
      <CompletionSummary controller={controller} />
      <StudioMobileTabs controller={controller} />
      <div className="studio-grid">
        <ChapterSidebar controller={controller} />
        <ChapterEditor controller={controller} />
        <WorkflowSidebar controller={controller} />
      </div>
    </div>
  )
}
