import {
  ArrowLeftOutlined,
  BookOutlined,
  EditOutlined,
  FolderOutlined,
  HistoryOutlined,
  LinkOutlined,
  MessageOutlined,
  PlusOutlined,
  RedoOutlined,
  SaveOutlined,
  SendOutlined,
  StopOutlined,
} from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Drawer,
  Empty,
  Input,
  Modal,
  Result,
  Segmented,
  Select,
  Skeleton,
  Space,
  Spin,
  Tag,
  Tooltip,
} from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Link, Navigate, useLocation, useParams } from 'react-router'
import { createIdempotencyKey } from '@/api/idempotency'
import { workbenchApi, workbenchErrorMessage } from '@/api/workbench'
import { AppShell } from '@/components/AppShell'
import { useAuthStore } from '@/stores/authStore'
import type {
  WorkbenchIntent,
  WorkbenchJob,
  WorkbenchMessage,
  WorkbenchOverview,
  WorkbenchSource,
} from '@/types/workbench'
import { AssetWorkspace, type AssetDraft } from './AssetWorkspace'
import './workbench.css'

const intentOptions: Array<{ value: WorkbenchIntent; label: string }> = [
  { value: 'discuss', label: '讨论' }, { value: 'setting', label: '完善设定' },
  { value: 'outline', label: '规划大纲' }, { value: 'write', label: '写作章节' },
  { value: 'continue', label: '续写' }, { value: 'rewrite', label: '改写' },
  { value: 'review', label: '审阅' },
]
const terminalStatuses = new Set(['completed', 'failed', 'stopped', 'cancelled'])

function MessageMarkdown({ content }: { content: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>{content}</ReactMarkdown>
}

function ReplySourcesDrawer({ sources, open, onClose }: {
  sources: WorkbenchSource[]
  open: boolean
  onClose: () => void
}) {
  return <Drawer title="回复来源" open={open} onClose={onClose} size="large">
    <div className="reply-source-list">
      {sources.map((source, index) => <article key={`${source.source_type}:${source.source_id}:${source.version}:${source.start}:${index}`}>
        <header><strong>{source.title}</strong><Tag>{source.source_type}</Tag></header>
        <dl>
          <div><dt>来源 ID</dt><dd>{source.source_id}</dd></div>
          <div><dt>版本</dt><dd>版本 {source.version}</dd></div>
          <div><dt>文本位置</dt><dd>偏移 {source.start}-{source.end}</dd></div>
          <div><dt>相关度</dt><dd>{source.score}</dd></div>
        </dl>
        <p>{source.text}</p>
      </article>)}
    </div>
  </Drawer>
}

function MessageCard({ message, job, onSave }: {
  message: WorkbenchMessage
  job?: WorkbenchJob
  onSave: (draft: AssetDraft) => void
}) {
  const bodyRef = useRef<HTMLDivElement>(null)
  const [selected, setSelected] = useState('')
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const content = job?.content || message.content
  const assistant = message.role === 'assistant'
  const sources = job?.sources?.length ? job.sources : message.sources || []
  const previousAttempts = (job?.previous_attempts || message.previous_attempts || []).filter((attempt) => attempt.content.trim())
  const rememberSelection = () => {
    const selection = window.getSelection()
    if (!selection || selection.isCollapsed || !bodyRef.current?.contains(selection.anchorNode)) return setSelected('')
    setSelected(selection.toString().trim())
  }
  return <article className={`conversation-message ${assistant ? 'assistant' : 'user'}`}>
    <header><strong>{assistant ? '写作助手' : '我'}</strong>
      {message.intent && <Tag>{intentOptions.find((item) => item.value === message.intent)?.label || message.intent}</Tag>}
      {job && !terminalStatuses.has(job.status) && <Tag color="processing">{job.status}</Tag>}
    </header>
    <div className="message-markdown" ref={bodyRef} onMouseUp={rememberSelection}>
      {content ? <MessageMarkdown content={content} /> : <Spin size="small" />}
    </div>
    {(job?.retrieval_available ?? message.retrieval_available) === false && <Alert className="message-retrieval-warning"
      type="warning" showIcon title="本次关键词检索不可用，回复仍包含固定设定与明确引用。" />}
    {job?.error && <Alert type="error" showIcon title={job.error} />}
    {assistant && previousAttempts.length > 0 && <details className="message-previous-attempts">
      <summary><HistoryOutlined />查看上次未完成内容（{previousAttempts.length}）</summary>
      {previousAttempts.map((attempt, index) => <section key={`${attempt.status}:${index}`}>
        <Tag>{attempt.status}</Tag><MessageMarkdown content={attempt.content} />
      </section>)}
    </details>}
    {assistant && (content || sources.length > 0) && <footer>
      {sources.length > 0 && <Button type="text" size="small" icon={<LinkOutlined />} aria-label={`查看来源 ${sources.length}`}
        onClick={() => setSourcesOpen(true)}>查看来源 ({sources.length})</Button>}
      {content && <Button type="text" size="small" icon={<SaveOutlined />} onClick={() => onSave({
        content, sourceMessageId: message.id, title: '对话摘录',
      })}>保存全文</Button>}
      {content && <Button type="text" size="small" disabled={!selected} onClick={() => onSave({
        content: selected, sourceMessageId: message.id, title: '对话选段',
      })}>保存选中</Button>}
    </footer>}
    <ReplySourcesDrawer sources={sources} open={sourcesOpen} onClose={() => setSourcesOpen(false)} />
  </article>
}

function ConversationList({ overview, activeId, loading, onSelect, onCreate, onRename }: {
  overview?: WorkbenchOverview
  activeId?: string
  loading: boolean
  onSelect: (id: string) => void
  onCreate: () => void
  onRename: (id: string, title: string) => void
}) {
  const [renaming, setRenaming] = useState<{ id: string; title: string }>()
  return <aside className="workbench-conversations" aria-label="创作会话">
    <header className="pane-heading"><div><span>SESSIONS</span><h2>创作会话</h2></div>
      <Tooltip title="新建会话"><Button aria-label="新建会话" icon={<PlusOutlined />} onClick={onCreate} /></Tooltip></header>
    <div className="conversation-list">
      {loading ? <Skeleton active paragraph={{ rows: 6 }} /> : overview?.conversations.length ? overview.conversations.map((conversation) =>
        <button type="button" className={activeId === conversation.id ? 'active' : ''} key={conversation.id}
          onClick={() => onSelect(conversation.id)}>
          <span><MessageOutlined /></span><span><strong>{conversation.title}</strong><small>{new Date(conversation.updated_at).toLocaleString('zh-CN')}</small></span>
          <span role="button" tabIndex={0} aria-label={`重命名 ${conversation.title}`} onClick={(event) => {
            event.stopPropagation(); setRenaming({ id: conversation.id, title: conversation.title })
          }}><EditOutlined /></span>
        </button>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无会话" />}
    </div>
    <Modal title="重命名会话" open={Boolean(renaming)} onCancel={() => setRenaming(undefined)} okText="保存"
      onOk={() => { if (renaming?.title.trim()) onRename(renaming.id, renaming.title.trim()); setRenaming(undefined) }}>
      <Input aria-label="会话名称" value={renaming?.title || ''} maxLength={80}
        onChange={(event) => setRenaming((value) => value ? { ...value, title: event.target.value } : value)} />
    </Modal>
  </aside>
}

function ConversationComposer({ disabled, assetsCount, chapters, onSend }: {
  disabled: boolean
  assetsCount: number
  chapters: WorkbenchOverview['chapters']
  onSend: (text: string, intent: WorkbenchIntent, targetChapterId?: string) => Promise<boolean>
}) {
  const [text, setText] = useState('')
  const [intent, setIntent] = useState<WorkbenchIntent>('discuss')
  const [chapterId, setChapterId] = useState<string>()
  const [sending, setSending] = useState(false)
  const needsChapter = ['continue', 'rewrite', 'review'].includes(intent)
  const missingContext = needsChapter && !chapterId && assetsCount === 0
  const send = async () => {
    if (!text.trim() || missingContext) return
    setSending(true)
    const sent = await onSend(text.trim(), intent, needsChapter ? chapterId : undefined)
    if (sent) setText('')
    setSending(false)
  }
  return <footer className="conversation-composer">
    <div className="composer-controls">
      <Select aria-label="创作意图" value={intent} onChange={(value) => {
        setIntent(value)
        if (!['continue', 'rewrite', 'review'].includes(value)) setChapterId(undefined)
      }} options={intentOptions} />
      {needsChapter && <Select aria-label="目标章节" value={chapterId} onChange={setChapterId}
        placeholder={assetsCount ? '可选：选择正式章节' : '选择章节或引用资产'}
        options={chapters.map((chapter) => ({ value: chapter.id, label: `第 ${chapter.chapter_index + 1} 章 · ${chapter.title}` }))} />}
      <span>{assetsCount ? `已引用 ${assetsCount} 项资产` : '未引用资产'}</span>
    </div>
    <Input.TextArea aria-label="对话内容" value={text} onChange={(event) => setText(event.target.value)}
      autoSize={{ minRows: 2, maxRows: 7 }} placeholder="写下要讨论、规划或创作的内容"
      onPressEnter={(event) => { if (!event.shiftKey) { event.preventDefault(); void send() } }} />
    <Button type="primary" aria-label="发送" icon={<SendOutlined />} loading={sending}
      disabled={disabled || !text.trim() || missingContext} onClick={() => void send()} />
  </footer>
}

export default function ConversationWorkbench() {
  const { novelId = '' } = useParams<{ novelId: string }>()
  const location = useLocation()
  const state = location.state as { startInput?: unknown } | null
  if (state?.startInput) return <Navigate to={`/novels/${novelId}/studio`} state={location.state} replace />
  return <ConversationWorkbenchView novelId={novelId} />
}

function ConversationWorkbenchView({ novelId }: { novelId: string }) {
  const tenantId = useAuthStore((state) => state.currentTenantId)
  const { message } = App.useApp()
  const [overview, setOverview] = useState<WorkbenchOverview>()
  const [overviewLoading, setOverviewLoading] = useState(true)
  const [fatalError, setFatalError] = useState('')
  const [activeConversationId, setActiveConversationId] = useState<string>()
  const [messages, setMessages] = useState<WorkbenchMessage[]>([])
  const [jobs, setJobs] = useState<Record<string, WorkbenchJob>>({})
  const [conversationLoading, setConversationLoading] = useState(false)
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([])
  const [assetDraft, setAssetDraft] = useState<AssetDraft>()
  const [mobilePane, setMobilePane] = useState<'sessions' | 'chat' | 'assets'>('chat')
  const [streamError, setStreamError] = useState('')
  const streams = useRef(new Map<string, AbortController>())
  const scopeRef = useRef('')
  const scopeKey = `${tenantId || ''}:${novelId}:${activeConversationId || ''}`
  useEffect(() => { scopeRef.current = scopeKey }, [scopeKey])

  const loadOverview = useCallback(async (signal?: AbortSignal) => {
    const value = await workbenchApi.overview(novelId, signal)
    setOverview(value)
    setActiveConversationId((current) => value.conversations.some((item) => item.id === current)
      ? current : value.conversations[0]?.id)
  }, [novelId])

  useEffect(() => {
    const controller = new AbortController()
    queueMicrotask(() => {
      if (controller.signal.aborted) return
      setOverviewLoading(true); setFatalError(''); setSelectedAssetIds([])
      void loadOverview(controller.signal).catch((error) => {
        if (!controller.signal.aborted) setFatalError(workbenchErrorMessage(error))
      }).finally(() => { if (!controller.signal.aborted) setOverviewLoading(false) })
    })
    return () => controller.abort()
  }, [loadOverview, tenantId])

  const watchJob = useCallback((job: WorkbenchJob, expectedScope: string, replace = false) => {
    if (terminalStatuses.has(job.status)) return
    const existing = streams.current.get(job.id)
    if (existing && !replace) return
    existing?.abort()
    const controller = new AbortController()
    streams.current.set(job.id, controller)
    void workbenchApi.streamJob(novelId, job.id, (snapshot) => {
      if (scopeRef.current !== expectedScope) return
      setJobs((current) => ({ ...current, [snapshot.id]: snapshot }))
      if (terminalStatuses.has(snapshot.status) && streams.current.get(snapshot.id) === controller) {
        streams.current.delete(snapshot.id)
        controller.abort()
      }
    }, controller.signal).then((snapshot) => {
      if (snapshot && scopeRef.current === expectedScope) setJobs((current) => ({ ...current, [snapshot.id]: snapshot }))
    }).catch((error) => {
      if (!controller.signal.aborted && scopeRef.current === expectedScope) {
        setStreamError(`${workbenchErrorMessage(error)}。任务已持久化，可刷新状态。`)
      }
    }).finally(() => {
      if (streams.current.get(job.id) === controller) streams.current.delete(job.id)
    })
  }, [novelId])

  const loadConversation = useCallback(async (conversationId: string, signal?: AbortSignal) => {
    const expectedScope = `${tenantId || ''}:${novelId}:${conversationId}`
    const detail = await workbenchApi.conversation(novelId, conversationId, signal)
    if (scopeRef.current !== expectedScope) return
    setMessages(detail.messages)
    const ids = [...new Set(detail.messages.map((item) => item.job_id).filter((id): id is string => Boolean(id)))]
    const snapshots = await Promise.allSettled(ids.map((id) => workbenchApi.job(novelId, id, signal)))
    if (scopeRef.current !== expectedScope) return
    const restored = snapshots.flatMap((result) => result.status === 'fulfilled' ? [result.value] : [])
    setJobs(Object.fromEntries(restored.map((item) => [item.id, item])))
    restored.forEach((item) => watchJob(item, expectedScope))
  }, [novelId, tenantId, watchJob])

  useEffect(() => {
    streams.current.forEach((controller) => controller.abort())
    streams.current.clear()
    const controller = new AbortController()
    queueMicrotask(() => {
      if (!controller.signal.aborted) {
        setMessages([]); setJobs({}); setStreamError(''); setConversationLoading(Boolean(activeConversationId))
      }
    })
    if (!activeConversationId) return () => controller.abort()
    void loadConversation(activeConversationId, controller.signal).catch((error) => {
      if (!controller.signal.aborted) message.error(workbenchErrorMessage(error))
    }).finally(() => { if (!controller.signal.aborted) setConversationLoading(false) })
    return () => controller.abort()
  }, [activeConversationId, loadConversation, message])

  const createConversation = async () => {
    try {
      const created = await workbenchApi.createConversation(novelId, { title: '新对话' })
      await loadOverview()
      setActiveConversationId(created.id)
      setMobilePane('chat')
    } catch (error) { message.error(workbenchErrorMessage(error)) }
  }
  const renameConversation = async (id: string, title: string) => {
    try { await workbenchApi.renameConversation(novelId, id, title); await loadOverview() }
    catch (error) { message.error(workbenchErrorMessage(error)) }
  }
  const send = async (text: string, intent: WorkbenchIntent, targetChapterId?: string) => {
    if (!activeConversationId) return false
    const chapter = overview?.chapters.find((item) => item.id === targetChapterId)
    const temp: WorkbenchMessage = {
      id: `local-${createIdempotencyKey()}`, conversation_id: activeConversationId, role: 'user', content: text,
      status: 'persisting', intent, sources: [], job_id: null, created_at: new Date().toISOString(),
    }
    setMessages((current) => [...current, temp])
    try {
      const job = await workbenchApi.createMessage(novelId, activeConversationId, {
        text, intent, reference_ids: selectedAssetIds,
        ...(chapter ? { chapter_index: chapter.chapter_index, target_chapter_id: chapter.id } : {}),
      }, createIdempotencyKey())
      setJobs((current) => ({ ...current, [job.id]: job }))
      await loadConversation(activeConversationId)
      watchJob(job, `${tenantId || ''}:${novelId}:${activeConversationId}`)
      return true
    } catch (error) {
      setMessages((current) => current.filter((item) => item.id !== temp.id))
      message.error(workbenchErrorMessage(error))
      return false
    }
  }
  const stop = async (job: WorkbenchJob) => {
    try { const value = await workbenchApi.stopJob(novelId, job.id); setJobs((current) => ({ ...current, [value.id]: value })) }
    catch (error) { message.error(workbenchErrorMessage(error)) }
  }
  const retry = async (job: WorkbenchJob) => {
    try {
      const value = await workbenchApi.retryJob(novelId, job.id, createIdempotencyKey())
      setJobs((current) => ({ ...current, [value.id]: value }))
      watchJob(value, scopeRef.current, true)
    } catch (error) { message.error(workbenchErrorMessage(error)) }
  }

  const jobsByMessage = useMemo(() => Object.fromEntries(Object.values(jobs).map((job) => [job.message_id, job])), [jobs])
  const pendingJobs = Object.values(jobs).filter((job) => !messages.some((item) => item.id === job.message_id))
  if (fatalError) return <AppShell><Result status="error" title="工作台无法加载" subTitle={fatalError}
    extra={<Space><Button onClick={() => window.location.reload()}>重新加载</Button><Link to={`/novels/${novelId}/studio`}>进入原工作台</Link></Space>} /></AppShell>
  if (overviewLoading || !overview) return <AppShell><div className="workbench-loading"><Skeleton active paragraph={{ rows: 12 }} /></div></AppShell>
  if (!overview.enabled) return <AppShell><Result status="info" title="对话工作台暂未启用"
    extra={<Link to={`/novels/${novelId}/studio`}><Button type="primary">进入原工作台</Button></Link>} /></AppShell>

  return <AppShell minimal>
    <main className="conversation-workbench">
      <header className="workbench-header">
        <Link to="/"><Button type="text" aria-label="返回书架" icon={<ArrowLeftOutlined />} /></Link>
        <div><span>{overview.novel.novel_type}</span><h1>{overview.novel.title || '未命名作品'}</h1></div>
        <Space><Tag>{overview.chapters.length} 章</Tag><Link to={`/novels/${novelId}/studio`}><Button icon={<BookOutlined />}>原工作台</Button></Link></Space>
      </header>
      <Segmented className="workbench-mobile-tabs" block value={mobilePane} onChange={setMobilePane} options={[
        { value: 'sessions', label: <span><MessageOutlined />会话</span> },
        { value: 'chat', label: <span><EditOutlined />对话</span> },
        { value: 'assets', label: <span><FolderOutlined />资产</span> },
      ]} />
      <div className="workbench-grid">
        <div className={mobilePane === 'sessions' ? 'mobile-active' : ''}><ConversationList overview={overview}
          activeId={activeConversationId} loading={overviewLoading} onSelect={(id) => { setActiveConversationId(id); setMobilePane('chat') }}
          onCreate={() => void createConversation()} onRename={(id, title) => void renameConversation(id, title)} /></div>
        <section className={`workbench-chat ${mobilePane === 'chat' ? 'mobile-active' : ''}`} aria-label="对话编辑区">
          {streamError && <Alert closable type="warning" showIcon message={streamError} onClose={() => setStreamError('')} />}
          <div className="message-list" aria-live="polite">
            {conversationLoading ? <Skeleton active paragraph={{ rows: 8 }} /> : !activeConversationId ? <Empty description="新建一个会话开始创作" />
              : messages.length || pendingJobs.length ? <>
                {messages.map((item) => <MessageCard key={item.id} message={item} job={jobsByMessage[item.id]} onSave={setAssetDraft} />)}
                {pendingJobs.map((job) => <MessageCard key={job.id} job={job} onSave={setAssetDraft} message={{
                  id: job.message_id, conversation_id: job.conversation_id, role: 'assistant', content: job.content,
                  status: job.status, intent: job.intent, sources: job.sources, job_id: job.id, created_at: job.created_at,
                }} />)}
              </> : <Empty description="当前会话还没有消息" />}
          </div>
          {Object.values(jobs).some((job) => !terminalStatuses.has(job.status)) && <div className="active-job-bar">
            <span>正在生成回复</span>{Object.values(jobs).filter((job) => !terminalStatuses.has(job.status)).map((job) =>
              <Button key={job.id} danger size="small" icon={<StopOutlined />} onClick={() => void stop(job)}>停止生成</Button>)}
          </div>}
          {Object.values(jobs).filter((job) => ['failed', 'stopped', 'cancelled'].includes(job.status)).map((job) =>
            <div className="failed-job-bar" key={job.id}><span>{job.error || '任务未完成'}</span>
              <Button size="small" icon={<RedoOutlined />} onClick={() => void retry(job)}>重试任务</Button></div>)}
          <ConversationComposer disabled={!activeConversationId} assetsCount={selectedAssetIds.length} chapters={overview.chapters} onSend={send} />
        </section>
        <div className={mobilePane === 'assets' ? 'mobile-active' : ''}><AssetWorkspace novelId={novelId} assets={overview.assets}
          legacySources={overview.legacy_sources || []} chapters={overview.chapters} selectedIds={selectedAssetIds} draft={assetDraft} onDraftConsumed={() => setAssetDraft(undefined)}
          onSelectionChange={setSelectedAssetIds} onChanged={() => void loadOverview()} /></div>
      </div>
    </main>
  </AppShell>
}
