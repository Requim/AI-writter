import { Button, Input, Progress, Segmented, Tooltip } from 'antd'
import {
  EditOutlined, FileTextOutlined, HistoryOutlined, LeftOutlined, PauseCircleOutlined,
  PlayCircleOutlined, ReloadOutlined, SaveOutlined, StopOutlined, UnorderedListOutlined,
} from '@ant-design/icons'
import { MarkdownManuscript } from '@/components/MarkdownManuscript'
import { WorkflowPanel } from '@/components/WorkflowPanel'
import type { ChapterSummary } from '@/types/novel'
import type { NovelStudioController } from './useNovelStudioController'

function WorkflowAction({ controller }: { controller: NovelStudioController }) {
  const { workflow, autoMode, autoRunActive } = controller
  const status = workflow.state.status
  const busy = ['running', 'stalled', 'cancelling'].includes(status)
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
        <span>{novel?.status === 'completed' ? '已完稿' : '创作中'}</span>
        <h1>{novel?.title || '未命名作品'}</h1>
      </div>
      <div className="studio-actions">
        <Segmented
          value={controller.autoMode ? 'auto' : 'manual'}
          onChange={(value) => controller.setAutoMode(value === 'auto')}
          options={[{ label: '手动', value: 'manual' }, { label: '自动', value: 'auto' }]}
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
        <div><strong>{chapter.title}</strong><small>{chapter.word_count.toLocaleString()} 字</small></div>
      </button>
    </li>
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

function EditorActions({ controller }: { controller: NovelStudioController }) {
  const { selectedChapter, editorMode } = controller.document
  const busy = ['running', 'stalled', 'cancelling'].includes(controller.workflow.state.status)
  if (!selectedChapter) return null
  return (
    <div className="editor-actions">
      <Segmented
        size="small" disabled={busy} value={editorMode}
        onChange={(value) => controller.setEditor({ editorMode: value as 'read' | 'edit' })}
        options={[{ label: '阅读', value: 'read' }, { label: '编辑', value: 'edit' }]}
        aria-label="章节查看模式"
      />
      {controller.hasUnsavedChanges && <span className="editor-dirty-indicator">未保存</span>}
      {controller.canDelete && (
        <Tooltip title="从本章重新创作">
          <Button danger type="text" aria-label="从本章重新创作" icon={<HistoryOutlined />} onClick={controller.deleteChapter} />
        </Tooltip>
      )}
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
  return (
    <WorkflowPanel
      className={`studio-pane ${active}`} state={workflow.state}
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
      <StudioMobileTabs controller={controller} />
      <div className="studio-grid">
        <ChapterSidebar controller={controller} />
        <ChapterEditor controller={controller} />
        <WorkflowSidebar controller={controller} />
      </div>
    </div>
  )
}
