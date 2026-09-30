import {
  Alert, App, Button, Form, Input, InputNumber, Progress, Select, Switch, Tag,
} from 'antd'
import {
  CheckCircleOutlined, FileSearchOutlined, LockOutlined, ReloadOutlined,
  SafetyCertificateOutlined, SendOutlined,
} from '@ant-design/icons'
import { useCallback, useEffect, useState } from 'react'
import { AppShell } from '@/components/AppShell'
import { researchApi, researchErrorMessage } from '@/api/research'
import type {
  KnowledgePackage, ProjectGenre, ResearchCapabilities, ResearchJob, ResearchSourceCategory, SearchHit,
} from '@/types/research'
import './research.css'

const categories: Array<{ label: string; value: ResearchSourceCategory }> = [
  { label: '玄幻', value: '玄幻' }, { label: '武侠', value: '武侠' }, { label: '恐怖', value: '恐怖' },
  { label: '军事', value: '军事' }, { label: '女频', value: '女频' }, { label: '游戏', value: '游戏' },
  { label: '科幻', value: '科幻' },
]
const genres: Array<{ label: string; value: ProjectGenre }> = [
  { label: '玄幻', value: 'fantasy' }, { label: '仙侠', value: 'xianxia' }, { label: '武侠', value: 'wuxia' },
  { label: '恐怖', value: 'horror' }, { label: '悬疑', value: 'suspense' }, { label: '军事', value: 'military' },
  { label: '历史', value: 'history' }, { label: '言情', value: 'romance' }, { label: '游戏', value: 'game' },
  { label: '科幻', value: 'sci_fi' },
]
const statusLabels: Record<string, string> = {
  draft: '待审核', review: '审核中', approved: '可用于生成', rejected: '已拒绝',
}
const openingPatterns = [
  { label: '即时危机', value: 'immediate_crisis' }, { label: '谜题提问', value: 'mystery_question' },
  { label: '身份反转', value: 'status_reversal' }, { label: '系统或任务', value: 'system_or_mission' },
  { label: '重生或穿越', value: 'rebirth_or_transport' }, { label: '关系碰撞', value: 'relationship_collision' },
  { label: '日常转入事件', value: 'ordinary_to_inciting_event' }, { label: '世界揭示', value: 'world_reveal' },
]

const catalogSources: Record<ResearchSourceCategory, string> = {
  玄幻: 'https://biquge.pro/lists/42.html', 武侠: 'https://biquge.pro/lists/44.html',
  恐怖: 'https://biquge.pro/lists/46.html', 军事: 'https://biquge.pro/lists/47.html',
  女频: 'https://biquge.pro/lists/48.html', 游戏: 'https://biquge.pro/lists/49.html',
  科幻: 'https://biquge.pro/lists/51.html',
}

function sourceTemplate(selected: ResearchSourceCategory[]) {
  return JSON.stringify(Object.fromEntries(selected.map((category) => [category, {
    popular: [catalogSources[category]],
    new: [catalogSources[category]],
    recent: [catalogSources[category]],
  }])), null, 2)
}

function hasCatalogSource(value: unknown) {
  if (!value || typeof value !== 'object') return false
  return Object.values(value).some((items) => Array.isArray(items) && items.some((url) => typeof url === 'string' && url.trim()))
}

function terminal(status?: ResearchJob['status']) {
  return status === 'completed' || status === 'partial' || status === 'failed'
}

function displayPhase(phase: string, status?: ResearchJob['status']) {
  if (status === 'failed' || phase === 'failed') return '采集失败'
  if (status === 'partial' || phase === 'partial') return '部分完成'
  if (status === 'completed') return '已完成'
  const [prefix, category] = phase.split(':')
  if (!category) return prefix === 'queued' ? '等待采集' : prefix === 'completed' ? '已完成' : prefix
  return `${prefix === 'collecting' ? '采集' : prefix}：${category}`
}

function JobFailure({ job }: { job?: ResearchJob }) {
  if (!job || (job.status !== 'failed' && job.status !== 'partial')) return null
  const unavailable = /HTTP 5\d\d/.test(job.error || '')
  return <Alert className="research-footer-alert" type={job.status === 'failed' ? 'error' : 'warning'} showIcon
    title={job.status === 'failed' ? '批次执行失败' : '批次部分完成'}
    description={<><p>{unavailable ? '来源站点暂时不可用，请稍后重试。已入库样本会保留。' : '已入库样本会保留，请根据具体错误检查来源配置。'}</p><div>{job.error || '未返回具体错误'}</div></>} />
}

function prettyValue(value: unknown) {
  return JSON.stringify(value, null, 2)
}

function useResearchJob(job: ResearchJob | undefined, setJob: (value: ResearchJob) => void, onError: (error: unknown) => void) {
  const jobId = job?.job_id
  const status = job?.status
  useEffect(() => {
    if (!jobId || terminal(status)) return
    const timer = window.setInterval(() => {
      void researchApi.job(jobId).then(setJob).catch(onError)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [jobId, onError, setJob, status])
}

function SectionHeading({ title }: { title: string }) {
  return <div className="research-section-heading"><h2>{title}</h2></div>
}

function ConnectionPanel({ loading, error, onConnect }: { loading: boolean; error: string; onConnect: () => void }) {
  return <section className="research-connection research-section" aria-label="连接研究服务">
    <div className="research-connection-form"><div className="research-auth-state"><LockOutlined /><span>使用当前登录态自动鉴权</span></div><Button type="primary" icon={<SafetyCertificateOutlined />} loading={loading} onClick={onConnect}>重新连接</Button></div>
    {error && <Alert className="research-connection-alert" type="error" showIcon title={error} />}
  </section>
}

function CollectionPanel({ job, onJob, capabilities }: { job?: ResearchJob; onJob: (value: ResearchJob) => void; capabilities?: ResearchCapabilities }) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [selectedCategories, setSelectedCategories] = useState<ResearchSourceCategory[]>(['玄幻'])
  const [loading, setLoading] = useState(false)
  const submit = async (values: Record<string, unknown>) => {
    let sources: Record<string, unknown>
    try { sources = JSON.parse(String(values.sources_json || '{}')) as Record<string, unknown> } catch { return message.error('来源配置不是合法 JSON') }
    const selected = values.categories as ResearchSourceCategory[]
    const missing = selected.filter((category) => !hasCatalogSource(sources[category]))
    if (missing.length) return message.error(`请为以下分类配置至少一个目录来源：${missing.join('、')}`)
    setLoading(true)
    try {
      const batchId = `research-${Date.now()}`
      const accepted = await researchApi.createBatch({ batch_id: batchId, categories: values.categories, sample_target_per_category: values.sample_target_per_category, sources, authorized_opening: Boolean(values.authorized_opening) })
      onJob({ job_id: accepted.job_id, batch_id: accepted.batch_id, status: accepted.status, phase: 'queued', processed: 0, total: 0, error: null })
      message.success('采集批次已入队')
    } catch (error) { message.error(researchErrorMessage(error)) } finally { setLoading(false) }
  }
  const refreshJob = () => { if (job) void researchApi.job(job.job_id).then(onJob).catch((error) => message.error(researchErrorMessage(error))) }
  const percent = job?.total ? Math.min(100, Math.round(job.processed / job.total * 100)) : 0
  return <section className="research-section" aria-label="采集新资料">
    <SectionHeading title="采集新资料" />
    <Form form={form} layout="vertical" onFinish={(values) => void submit(values)} initialValues={{ categories: selectedCategories, sample_target_per_category: 10, sources_json: sourceTemplate(selectedCategories), authorized_opening: false }}>
      <Form.Item name="categories" label="来源分类" rules={[{ required: true, message: '至少选择一个分类' }]}><Select mode="multiple" options={categories} onChange={(value) => { const next = value as ResearchSourceCategory[]; setSelectedCategories(next); form.setFieldValue('sources_json', sourceTemplate(next)) }} /></Form.Item>
      <div className="research-result-terms">{selectedCategories.map((category) => <Tag key={category}>{category} → {(capabilities?.source_to_project_genres?.[category] || []).map((genre) => capabilities?.genre_labels?.[genre] || genre).join('、')}</Tag>)}</div>
      <div className="research-form-row"><Form.Item name="sample_target_per_category" label="每类样本数"><InputNumber min={1} max={100} /></Form.Item><Form.Item name="authorized_opening" label="授权读取首章" valuePropName="checked" extra="默认关闭，只有明确授权时才会临时读取。"><Switch /></Form.Item></div>
      <Form.Item name="sources_json" label="目录来源 JSON" rules={[{ required: true, message: '请填写来源配置' }]} extra="按热门、新书、最近更新分组；每个 URL 一行写在数组中。"><Input.TextArea rows={7} spellCheck={false} className="research-json-input" /></Form.Item>
      <Button type="primary" htmlType="submit" icon={<SendOutlined />} loading={loading}>提交批次</Button>
    </Form>
    {job && <div className="research-job" aria-live="polite"><div className="research-job-header"><strong>批次 {job.batch_id}</strong><Tag color={job.status === 'failed' ? 'error' : job.status === 'partial' ? 'warning' : terminal(job.status) ? 'success' : 'processing'}>{displayPhase(job.phase, job.status)}</Tag></div><Progress percent={percent} status={job.status === 'failed' ? 'exception' : undefined} /><div className="research-job-meta"><span>{displayPhase(job.phase, job.status)}</span><span>{job.processed} / {job.total || '等待统计'}</span><Button type="text" icon={<ReloadOutlined />} aria-label="刷新任务状态" onClick={refreshJob} /></div>{job.error && <Alert type="warning" showIcon title={job.error} />}</div>}
  </section>
}

function RetrievalPanel({ onPackage, capabilities, currentPackage }: { onPackage: (value: KnowledgePackage) => void; capabilities?: ResearchCapabilities; currentPackage?: KnowledgePackage }) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [hits, setHits] = useState<SearchHit[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)
  const options = capabilities?.genre_labels ? Object.entries(capabilities.genre_labels).map(([value, label]) => ({ value, label })) : genres
  useEffect(() => {
    if (currentPackage) setHits((items) => items.map((item) => item.knowledge_version_id === currentPackage.knowledge_version_id ? { ...item, status: currentPackage.status, content: { ...currentPackage } } : item))
  }, [currentPackage])
  const search = async (values: Record<string, unknown>) => {
    setLoading(true)
    try { const result = await researchApi.search({ project_genre: String(values.project_genre), q: String(values.q || ''), opening_pattern: values.opening_pattern as string | undefined, approved_only: Boolean(values.approved_only), limit: 8 }); setHits(result.items); setSearched(true) } catch (error) { setHits([]); message.error(researchErrorMessage(error)) } finally { setLoading(false) }
  }
  const loadCurrent = async () => {
    try { onPackage(await researchApi.current(String(form.getFieldValue('project_genre') || 'suspense'))) } catch (error) { message.error(researchErrorMessage(error)) }
  }
  return <section className="research-section research-primary" aria-label="查找写作素材">
    <SectionHeading title="查找写作素材" />
    <Form form={form} layout="vertical" onFinish={(values) => void search(values)} initialValues={{ project_genre: 'fantasy', approved_only: false }}>
      <div className="research-search-row"><Form.Item name="project_genre" label="题材"><Select options={options} /></Form.Item><Form.Item name="q" label="关键词"><Input placeholder="例如：开局、反转、追读、关系冲突" allowClear /></Form.Item><Button type="primary" htmlType="submit" icon={<FileSearchOutlined />} loading={loading}>检索</Button></div>
      <Form.Item name="approved_only" label="仅可用于生成" valuePropName="checked"><Switch /></Form.Item>
      <details className="research-filter-toggle"><summary>更多筛选</summary><Form.Item name="opening_pattern" label="开局模式"><Select allowClear options={openingPatterns} placeholder="不限定开局模式" /></Form.Item></details>
      <Button type="link" onClick={() => void loadCurrent()}>查看当前版本</Button>
    </Form>
    <div className="research-results" aria-live="polite">{hits.length ? hits.map((hit) => <details className="research-result" key={`${hit.knowledge_version_id}-${hit.version}`}><summary className="research-result-heading"><strong>版本 {hit.version}</strong><Tag>{statusLabels[hit.status] || hit.status}</Tag><span>{String(hit.content.sample_count || 0)} 个样本</span></summary><div className="research-result-terms">{hit.matched_terms.map((term) => <Tag key={term}>{term}</Tag>)}</div><PackageView value={hit.content as unknown as KnowledgePackage} /><Button icon={<SafetyCertificateOutlined />} onClick={() => onPackage(hit.content as unknown as KnowledgePackage)}>选择此版本审核</Button></details>) : <div className="research-empty">{searched ? '没有匹配素材。' : '暂无检索结果。'}</div>}</div>
  </section>
}

function ReviewPanel({ currentPackage, onPackage }: { currentPackage?: KnowledgePackage; onPackage: (value: KnowledgePackage) => void }) {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm()
  useEffect(() => { if (currentPackage) form.setFieldValue('version_id', currentPackage.knowledge_version_id) }, [currentPackage, form])
  const submit = async (values: Record<string, unknown>) => {
    const versionId = currentPackage?.knowledge_version_id || String(values.version_id || '')
    if (!versionId) return message.warning('先查看一个知识版本')
    setLoading(true)
    try { onPackage(await researchApi.review(versionId, { decision: values.decision, reviewer: values.reviewer, comment: values.comment || '' })); message.success(values.decision === 'approve' ? '知识版本已审核通过' : '知识版本已标记为拒绝') } catch (error) { message.error(researchErrorMessage(error)) } finally { setLoading(false) }
  }
  return <section className="research-section research-knowledge" aria-label="审核知识版本">
    <div className="research-review-grid"><Form form={form} layout="vertical" onFinish={(values) => void submit(values)} initialValues={{ decision: 'approve' }}>{currentPackage ? <div className="research-selected-version"><span>当前版本</span><strong>{currentPackage.project_genre} · v{currentPackage.version}</strong></div> : <Form.Item name="version_id" label="知识版本 ID"><Input placeholder="knowledge-version-..." /></Form.Item>}<Form.Item name="reviewer" label="审核人" rules={[{ required: true, message: '填写审核人' }]}><Input placeholder="姓名或账号" /></Form.Item><Form.Item name="decision" label="审核决定"><Select options={[{ value: 'approve', label: '通过' }, { value: 'reject', label: '拒绝' }]} /></Form.Item><Form.Item name="comment" label="备注"><Input.TextArea rows={2} /></Form.Item><Button htmlType="submit" icon={<SafetyCertificateOutlined />} loading={loading}>提交审核</Button></Form>{currentPackage && <PackageView value={currentPackage} />}</div>
  </section>
}

function PackageView({ value }: { value: KnowledgePackage }) {
  return <div className="research-package-view"><div className="research-package-meta"><Tag color={value.status === 'approved' ? 'success' : 'warning'}>{statusLabels[value.status] || value.status}</Tag><strong>{value.project_genre} · v{value.version}</strong><span>{value.sample_count} 个样本</span></div><PackageList title="写作参考" values={value.writing_guidance} /><PackageList title="原创边界" values={value.originality_rules} /><PackageList title="适用限制" values={value.limitations} /><details><summary>查看完整结构化内容</summary><pre>{prettyValue(value)}</pre></details></div>
}

function PackageList({ title, values }: { title: string; values: string[] }) {
  if (!values.length) return null
  return <div><h3>{title}</h3><ul>{values.slice(0, 4).map((item) => <li key={item}>{item}</li>)}</ul></div>
}

export default function ResearchConsole() {
  const { message } = App.useApp()
  const [capabilities, setCapabilities] = useState<ResearchCapabilities>()
  const [connecting, setConnecting] = useState(false)
  const [connectionError, setConnectionError] = useState('')
  const [job, setJob] = useState<ResearchJob>()
  const [currentPackage, setCurrentPackage] = useState<KnowledgePackage>()
  useResearchJob(job, setJob, (error) => message.error(researchErrorMessage(error)))
  const connect = useCallback(async (notify = false) => {
    setConnecting(true); setConnectionError('')
    try { const value = await researchApi.capabilities(); setCapabilities(value); if (notify) message.success('研究服务已连接') } catch (error) { setCapabilities(undefined); setConnectionError(researchErrorMessage(error)) } finally { setConnecting(false) }
  }, [message])
  useEffect(() => {
    sessionStorage.removeItem('novel-writer-research-token')
    const timer = window.setTimeout(() => void connect(), 0)
    return () => window.clearTimeout(timer)
  }, [connect])
  const connected = Boolean(capabilities)
  return <AppShell><div className="research-page page-enter"><header className="research-intro"><h1>写作素材库</h1><Tag icon={connected ? <CheckCircleOutlined /> : <LockOutlined />} color={connected ? 'success' : 'default'}>{connected ? '已连接' : '未连接'}</Tag></header><ConnectionPanel loading={connecting} error={connectionError} onConnect={() => void connect(true)} /><RetrievalPanel onPackage={setCurrentPackage} capabilities={capabilities} currentPackage={currentPackage} /><details className="research-secondary" open={Boolean(job && job.status !== 'completed')}><summary>采集新资料{job && <span className="research-secondary-status">{displayPhase(job.phase, job.status)}</span>}</summary><div className="research-secondary-content"><CollectionPanel job={job} onJob={setJob} capabilities={capabilities} /></div></details><details className="research-secondary" open={Boolean(currentPackage)}><summary>审核写作素材{currentPackage && <span className="research-secondary-status">已选择 v{currentPackage.version}</span>}</summary><div className="research-secondary-content"><ReviewPanel currentPackage={currentPackage} onPackage={setCurrentPackage} /></div></details><JobFailure job={job} /></div></AppShell>
}
