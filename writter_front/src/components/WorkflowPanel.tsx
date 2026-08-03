import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  DisconnectOutlined,
  LoadingOutlined,
  PauseCircleOutlined,
  ReloadOutlined,
  StopOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { Button, Input, Progress, Tag, Tooltip } from 'antd'
import { useState } from 'react'
import type { WorkflowViewState } from '@/hooks/useWorkflowStream'

const nodeLabels: Record<string, string> = {
  type_confirmation: '确认题材',
  creative_brief_node: '凝练创作简报',
  title_node: '推敲书名',
  summary_node: '撰写简介',
  outline_node: '搭建总纲',
  memory_retrieval_node: '检索前文',
  chapter_outline_node: '设计细纲',
  chapter_writer_node: '撰写正文',
  reflection_node: '质量审读',
  revision_node: '修订章节',
  persist_node: '归档稿件',
  progress_check_node: '核对进度',
  router_agent: '规划下一步',
}

const nodeDescriptions: Record<string, string> = {
  type_confirmation: '正在确认作品题材和基础约束。',
  creative_brief_node: '正在明确故事母题、核心冲突与读者体验。',
  title_node: '正在生成或确认小说名称。',
  summary_node: '正在整理故事简介与核心卖点。',
  outline_node: '正在构建世界观、角色、主线和分卷结构。',
  memory_retrieval_node: '正在读取前文章节和人物状态。',
  chapter_outline_node: '正在根据总纲设计当前章节细纲。',
  chapter_writer_node: '正在根据细纲流式生成章节正文。',
  reflection_node: '正在检查情节、人物和语言质量。',
  revision_node: '正在按审读结果修订正文。',
  persist_node: '正在保存章节、进度和长期记忆。',
  progress_check_node: '正在核对章节进度并准备下一章。',
  router_agent: '正在根据当前创作状态安排下一步。',
}

function formatTime(value?: string): string {
  if (!value) return '尚无记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '尚无记录'
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

function chapterNumberFromState(state: WorkflowViewState): number | undefined {
  const interruptChapter = state.interrupt?.chapter_number
  if (typeof interruptChapter === 'number') return interruptChapter
  if (typeof state.checkpointChapterIndex === 'number') return state.checkpointChapterIndex + 1
  const match = state.reasoning?.match(/第\s*(\d+)\s*章/)
  return match ? Number(match[1]) : undefined
}

function stagePresentation(state: WorkflowViewState, chapterPrefix: string) {
  const nodeLabel = nodeLabels[state.activeNode ?? ''] ?? '当前步骤'
  const chapterLabel = ['chapter_outline_node', 'chapter_writer_node', 'reflection_node', 'revision_node', 'persist_node']
    .includes(state.activeNode ?? '')
    ? `${chapterPrefix}${nodeLabel}`
    : nodeLabel
  if (state.status === 'error') return {
    label: `${chapterLabel}失败`,
    description: state.error || '当前步骤未能完成，请查看错误信息后重试。',
  }
  if (state.status === 'recoverable') return {
    label: `${chapterLabel}可继续`,
    description: state.hasCheckpointDraft
      ? '本章草稿和创作进度均已保留，继续后不会重写前文。'
      : '创作进度已保留，可以从当前步骤继续。',
  }
  if (state.activeNode === 'chapter_outline_node') return {
    label: state.status === 'paused' ? `${chapterPrefix}细纲待审阅` : `正在生成${chapterPrefix}细纲`,
    description: nodeDescriptions.chapter_outline_node,
  }
  return {
    label: nodeLabels[state.activeNode ?? ''] ?? '等待开始创作',
    description: nodeDescriptions[state.activeNode ?? ''] ?? '尚未开始本轮创作。',
  }
}

function emptyTimelineLabel(status: WorkflowViewState['status']): string {
  if (status === 'recoverable') return '草稿已保留，等待继续'
  if (status === 'error') return '当前步骤未完成'
  return '尚未开始执行'
}

function primaryResumeLabel(action?: string): string {
  if (action === 'review_or_modify_creative_brief') return '确认创作简报'
  if (action === 'review_or_provide_chapter_outline') return '使用细纲，生成正文'
  if (action === 'review_reflection_issues') return '接受本章'
  if (action === 'ready_for_next_chapter') return '生成下一章'
  if (action === 'confirm_revision') return '接受修订'
  if (action === 'quality_gate_exhausted' || action === 'quality_gate_human_review') return '人工接受本章'
  return '接受并继续'
}

interface WorkflowPanelProps {
  className?: string
  state: WorkflowViewState
  autoMode: boolean
  onResume: (value: unknown) => void
  onRetry: () => void
  onCancel: () => void
  onRefresh: () => void
}

export function WorkflowPanel({
  className = '',
  state,
  autoMode,
  onResume,
  onRetry,
  onCancel,
  onRefresh,
}: WorkflowPanelProps) {
  const [instruction, setInstruction] = useState('')
  const interrupt = state.interrupt
  const chapterNumber = chapterNumberFromState(state)
  const chapterPrefix = chapterNumber ? `第 ${chapterNumber} 章` : '本章'
  const stage = stagePresentation(state, chapterPrefix)
  const stageLabel = stage.label
  const stageDescription = state.status === 'paused' && interrupt
    ? interrupt.message || '当前结果已生成，请审阅后继续。'
    : stage.description
  const completedTimeline = state.events
    .filter((event) => event.type === 'status' && event.data.status === 'completed' && event.node && event.node !== 'router_agent')
    .map((event) => event.node as string)
    .filter((node, index, nodes) => index === 0 || node !== nodes[index - 1])
    .slice(-7)
  const activeTimelineNode = state.activeNode && state.activeNode !== 'router_agent'
    && ['running', 'paused', 'stalled', 'cancelling'].includes(state.status)
    ? state.activeNode
    : undefined
  const timelineNodes = activeTimelineNode && completedTimeline.at(-1) !== activeTimelineNode
    ? [...completedTimeline, activeTimelineNode]
    : completedTimeline
  const aiOutline = interrupt?.ai_generated_outline
  const outlineTitle = typeof aiOutline?.title === 'string' ? aiOutline.title : undefined
  const outlineGoal = typeof aiOutline?.chapter_goal === 'string' ? aiOutline.chapter_goal : undefined
  const outlineEvents = Array.isArray(aiOutline?.key_events)
    ? aiOutline.key_events.filter((item): item is string => typeof item === 'string').slice(0, 4)
    : []
  const titleSuggestions = Array.isArray(interrupt?.ai_suggestions)
    ? interrupt.ai_suggestions.map((item) => typeof item === 'string' ? { title: item } : item)
    : []
  const generatedSummary = typeof interrupt?.ai_generated_summary === 'string'
    ? interrupt.ai_generated_summary
    : undefined
  const aiCreativeBrief = interrupt?.action === 'review_or_modify_creative_brief'
    ? interrupt.ai_generated_creative_brief
    : undefined
  const creativeBriefRows = aiCreativeBrief
    ? [
        ['核心设想', aiCreativeBrief.core_premise],
        ['主角驱动力', aiCreativeBrief.protagonist_drive],
        ['核心冲突', aiCreativeBrief.core_conflict],
        ['主题命题', aiCreativeBrief.theme_question],
        ['读者体验', aiCreativeBrief.reader_promise],
      ].filter((row): row is [string, string] => typeof row[1] === 'string' && Boolean(row[1].trim()))
    : []
  const canRegenerate = interrupt?.action !== 'ready_for_next_chapter'
  const canProvideInstruction = !['ready_for_next_chapter', 'require_novel_type'].includes(interrupt?.action ?? '')
  const requiresHumanReview = ['quality_gate_exhausted', 'quality_gate_human_review']
    .includes(interrupt?.action ?? '')
  const acceptedValue = interrupt?.action === 'review_or_modify_creative_brief' && aiCreativeBrief
    ? aiCreativeBrief
    : interrupt?.action === 'confirm_or_provide_title' && titleSuggestions[0]
      ? titleSuggestions[0]
      : interrupt?.action === 'confirm_or_provide_summary' && generatedSummary
        ? generatedSummary
        : ['review_or_modify_outline', 'review_or_provide_chapter_outline'].includes(interrupt?.action ?? '') && aiOutline
          ? aiOutline
          : 'accept'
  const statusMeta = {
    running: { label: '执行中', color: 'processing' as const, icon: <LoadingOutlined /> },
    paused: { label: '待确认', color: 'warning' as const, icon: <PauseCircleOutlined /> },
    recoverable: { label: '可继续', color: 'warning' as const, icon: <ReloadOutlined /> },
    stalled: { label: '状态异常', color: 'error' as const, icon: <WarningOutlined /> },
    cancelling: { label: '正在结束', color: 'processing' as const, icon: <LoadingOutlined /> },
    error: { label: '失败', color: 'error' as const, icon: <WarningOutlined /> },
    idle: { label: '空闲', color: 'default' as const, icon: <CheckCircleOutlined /> },
  }[state.status]
  const isBusy = ['running', 'stalled', 'cancelling'].includes(state.status)
  return (
    <aside className={`workflow-panel ${className}`.trim()} aria-label="创作执行状态">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">AI 编辑台</span>
          <h2>执行记录</h2>
        </div>
        <Tag color={statusMeta.color} icon={statusMeta.icon}>
          {statusMeta.label}
        </Tag>
      </div>

      {typeof state.progress === 'number' && (
        <Progress percent={Math.round(state.progress)} showInfo={false} strokeColor="#176b5b" />
      )}

      <section className="execution-overview" data-state={state.status} aria-live="polite">
        <div className="execution-stage">
          <span className="stage-marker" aria-hidden="true" />
          <div>
            <small>当前阶段</small>
            <strong>{stageLabel}</strong>
          </div>
        </div>
        <p>{stageDescription}</p>
        {(state.startedAt || state.lastActivityAt) && (
          <dl className="execution-times">
            <div><dt><ClockCircleOutlined /> 开始</dt><dd>{formatTime(state.startedAt)}</dd></div>
            <div><dt>最后进展</dt><dd>{formatTime(state.lastActivityAt)}</dd></div>
          </dl>
        )}
        {state.connection === 'detached' && state.status === 'running' && (
          <div className="connection-note"><DisconnectOutlined /> 页面正在同步后台任务状态</div>
        )}
        {state.status === 'stalled' && (
          <div className="stalled-note">
            <strong>任务长时间没有新进展</strong>
            <span>可以先刷新状态；若仍无变化，结束异常任务后从已保留的创作进度继续。</span>
          </div>
        )}
        {(isBusy || state.connection === 'detached') && (
          <div className="execution-actions">
            <Tooltip title="从服务器重新读取当前节点">
              <Button size="small" icon={<ReloadOutlined />} onClick={onRefresh}>刷新状态</Button>
            </Tooltip>
            <Button
              size="small"
              danger
              icon={<StopOutlined />}
              loading={state.status === 'cancelling'}
              onClick={onCancel}
            >
              结束任务
            </Button>
          </div>
        )}
      </section>

      {state.status === 'running' && state.reasoning && state.reasoning !== stageDescription && (
        <div className="reasoning-block">
          <span>流程判断</span>
          <p>{state.reasoning}</p>
        </div>
      )}

      <ol className="event-list">
        {timelineNodes.map((node, index) => {
          const isActive = node === activeTimelineNode && index === timelineNodes.length - 1
          return (
          <li key={`${node}-${index}`} data-active={isActive || undefined}>
            {isActive
              ? state.status === 'paused' ? <PauseCircleOutlined /> : <LoadingOutlined />
              : <CheckCircleOutlined />}
            <span>{node === 'chapter_outline_node' && isActive ? stageLabel : nodeLabels[node] ?? node}</span>
          </li>
          )
        })}
        {timelineNodes.length === 0 && <li className="muted">{emptyTimelineLabel(state.status)}</li>}
      </ol>

      {typeof state.qualityScore === 'number' && (
        <section className="quality-block">
          <div><span>质量评分</span><strong>{Math.round(state.qualityScore * 100)}</strong></div>
          <Progress percent={Math.round(state.qualityScore * 100)} showInfo={false} strokeColor="#8d2f3d" />
          {state.issues.slice(0, 3).map((issue, index) => (
            <p key={`${issue.type}-${index}`}>{issue.description || issue.type || '待处理问题'}</p>
          ))}
        </section>
      )}

      {interrupt && (!autoMode || requiresHumanReview) && (
        <section className="interrupt-block">
          <div className="interrupt-title"><PauseCircleOutlined /> 需要你的决定</div>
          <p>{interrupt.message || '请审阅当前结果后继续。'}</p>
          {aiOutline && (
            <div className="outline-review">
              <span>{chapterPrefix}细纲</span>
              {outlineTitle && <strong>{outlineTitle}</strong>}
              {outlineGoal && <p>{outlineGoal}</p>}
              {outlineEvents.length > 0 && (
                <ol>{outlineEvents.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ol>
              )}
            </div>
          )}
          {titleSuggestions.length > 0 && (
            <div className="outline-review title-suggestions">
              <span>书名候选</span>
              {titleSuggestions.slice(0, 8).map((item) => (
                <Button key={item.title} type="text" block onClick={() => onResume(item)}>
                  <strong>{item.title}</strong>
                  {item.hint && <small>{item.hint}</small>}
                </Button>
              ))}
            </div>
          )}
          {generatedSummary && (
            <div className="outline-review">
              <span>简介提案</span>
              <p>{generatedSummary}</p>
            </div>
          )}
          {creativeBriefRows.length > 0 && (
            <div className="outline-review creative-brief-review">
              <span>创作简报</span>
              <dl>
                {creativeBriefRows.map(([label, value]) => (
                  <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
                ))}
              </dl>
            </div>
          )}
          <div className="interrupt-actions">
            <Button type="primary" onClick={() => onResume(acceptedValue)}>{primaryResumeLabel(interrupt.action)}</Button>
            {canRegenerate && <Button onClick={() => onResume('regenerate')}>重新生成</Button>}
          </div>
          {canProvideInstruction && (
            <>
              <Input.TextArea
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
                placeholder="输入具体修改要求"
                autoSize={{ minRows: 2, maxRows: 5 }}
              />
              <Button
                disabled={!instruction.trim()}
                onClick={() => {
                  onResume(instruction.trim())
                  setInstruction('')
                }}
              >
                按要求修订
              </Button>
            </>
          )}
        </section>
      )}

      {state.error && state.status !== 'stalled' && (
        <div className="error-note">
          {state.error}
          {state.retryable && <small>本章草稿和创作进度已保留，可直接重试当前步骤。</small>}
          {state.retryable && (
            <Button size="small" icon={<ReloadOutlined />} onClick={onRetry}>
              {state.activeNode === 'reflection_node' && chapterNumber
                ? `重试第 ${chapterNumber} 章质量审读`
                : '重试当前步骤'}
            </Button>
          )}
        </div>
      )}
    </aside>
  )
}
