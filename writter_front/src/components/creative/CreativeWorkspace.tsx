import { Alert, App, Button, Collapse, Drawer, Form, Input, InputNumber, Select, Space, Spin, Tabs, Tag, Tooltip, Upload } from 'antd'
import { BulbOutlined, ExperimentOutlined, FileSearchOutlined, ReadOutlined, ReloadOutlined, SaveOutlined, TeamOutlined, UploadOutlined, HighlightOutlined } from '@ant-design/icons'
import { useCallback, useEffect, useState } from 'react'
import { creativeApi } from '@/api/creative'
import type { CreativeOverview, CreativeRecord } from '@/types/creative'
import type { ChapterDetail } from '@/types/novel'
import { CreativeRecords } from './CreativeRecords'
import { CreativeFeedbackForm } from './CreativeFeedbackForm'
import { AuthorStylePanel } from './AuthorStylePanel'
import './creative.css'

interface Props { novelId: string; chapter?: ChapterDetail | null; revision?: number }

export function CreativeWorkspace({ novelId, chapter, revision }: Props) {
  const [open, setOpen] = useState(false)
  const [overview, setOverview] = useState<CreativeOverview>()
  const [records, setRecords] = useState<CreativeRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)
  const reload = useCallback(async () => {
    setLoading(true); setFailed(false)
    try {
      const [value, artifacts] = await Promise.all([creativeApi.overview(novelId), creativeApi.artifacts(novelId)])
      setOverview(value); setRecords(artifacts)
    } catch { setFailed(true) } finally { setLoading(false) }
  }, [novelId])
  useEffect(() => {
    if (!open) return
    let active = true
    Promise.all([creativeApi.overview(novelId), creativeApi.artifacts(novelId)])
      .then(([value, artifacts]) => { if (active) { setOverview(value); setRecords(artifacts); setFailed(false) } })
      .catch(() => { if (active) setFailed(true) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [open, novelId, revision])
  const select = (...kinds: string[]) => records.filter((r) => kinds.includes(r.kind))
  return <>
    <Tooltip title="创作决策与证据"><Button icon={<ExperimentOutlined />} onClick={() => { setLoading(true); setOpen(true) }}>作家工作台</Button></Tooltip>
    <Drawer title="作家工作台" open={open} onClose={() => setOpen(false)} size={1040} className="creative-workspace"
      extra={<Tooltip title="刷新成果"><Button aria-label="刷新创作成果" icon={<ReloadOutlined />} onClick={() => void reload()} loading={loading} /></Tooltip>}>
      {failed && <Alert type="error" showIcon title="创作成果读取失败" action={<Button onClick={() => void reload()}>重试</Button>} />}
      {loading && !overview && <Spin />}
      {overview && <>
        <BudgetPanel overview={overview} novelId={novelId} onSaved={() => void reload()} />
        {overview.session.stage.startsWith('postprocess:') && <Alert type="warning" showIcon title="正文已保存，后处理待恢复" />}
        <Tabs items={[
          { key: 'decisions', label: '创作决策', icon: <BulbOutlined />, children: <CreativeRecords records={select('candidate', 'engine', 'selection', 'pilot', 'evaluation', 'decision', 'replan')} /> },
          { key: 'characters', label: '人物主线', icon: <TeamOutlined />, children: <CreativeRecords records={select('character', 'role_slot', 'relationship', 'secret', 'foreshadow')} /> },
          { key: 'readers', label: '读者复盘', icon: <ReadOutlined />, children: <CreativeRecords records={select('reader_state', 'engine_review')} /> },
          { key: 'style', label: '作者审美', icon: <HighlightOutlined />, children: <><AuthorStylePanel novelId={novelId} overview={overview} onSaved={() => void reload()} /><CreativeRecords records={select('style_application')} /></> },
          { key: 'feedback', label: '反馈实验', icon: <ExperimentOutlined />, children: <><CreativeFeedbackForm novelId={novelId} chapter={chapter} onSaved={() => void reload()} />
            <HumanReview novelId={novelId} records={select('experiment')} onSaved={() => void reload()} />
            <CreativeRecords records={select('feedback', 'hypothesis', 'experiment', 'adoption')} /></> },
          { key: 'sources', label: '资料', icon: <FileSearchOutlined />, children: <><SourcePanel novelId={novelId} onSaved={() => void reload()} /><CreativeRecords records={select('source')} /></> },
        ]} />
      </>}
    </Drawer>
  </>
}

function BudgetPanel({ overview, novelId, onSaved }: { overview: CreativeOverview; novelId: string; onSaved: () => void }) {
  const { session } = overview
  const used = Object.entries(session.counters).filter(([key]) => !key.includes('search')).reduce((sum, [, value]) => sum + value, 0)
  const { message } = App.useApp()
  const [saving, setSaving] = useState(false)
  const save = async (limits: unknown) => {
    setSaving(true)
    try { await creativeApi.budget(novelId, { expected_version: session.version, limits }); onSaved() }
    catch { message.error('预算更新失败，请在章边界刷新版本后重试') }
    finally { setSaving(false) }
  }
  return <section className="creative-budget">
    <div className="creative-statistics">
      <div><span>模型请求</span><strong>{used}<small> / {session.limits.total}</small></strong></div>
      <div><span>资料检索</span><strong>{session.counters.search || 0}<small> / {session.limits.search}</small></strong></div>
      <div><span>真人效果验收</span><Tag>尚未完成</Tag></div>
    </div>
    <Collapse ghost items={[{ key: 'budget', label: '调用预算', children: <Form name="creative-budget" key={session.version} layout="vertical"
      initialValues={{ preparation: session.limits.preparation, chapter: session.limits.chapter, review: session.limits.review,
        search: session.limits.search, preparation_search: session.limits.preparation_search }} onFinish={(values) => void save(values)}>
      <div className="creative-form-grid">{([
        ['preparation', '准备', 60], ['chapter', '每章', 32], ['review', '复盘共享', 20 + 8 * session.limits.chapters],
        ['search', '全书检索', 12], ['preparation_search', '立项检索', 6],
      ] as const).map(([key, label, max]) => <Form.Item key={key} name={key} label={label}><InputNumber min={key === 'preparation' || key === 'chapter' ? 1 : 0} max={max} /></Form.Item>)}</div>
      <Button htmlType="submit" icon={<SaveOutlined />} loading={saving}>更新预算</Button>
    </Form> }]} />
  </section>
}

function SourcePanel({ novelId, onSaved }: { novelId: string; onSaved: () => void }) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const save = async (values: Record<string, unknown>) => {
    setSaving(true)
    try { await creativeApi.sources(novelId, { ...values, origin: 'user_text', observed_at: new Date().toISOString() }); form.resetFields(); onSaved() }
    catch { message.error('资料保存失败') } finally { setSaving(false) }
  }
  return <Form name="creative-source" form={form} layout="vertical" onFinish={(values) => void save(values)} initialValues={{ category: 'model_hypothesis' }}>
    <div className="creative-form-grid">
      <Form.Item name="title" label="资料标题" rules={[{ required: true }]}><Input maxLength={240} /></Form.Item>
      <Form.Item name="category" label="证据分类"><Select options={[{ value: 'traceable_fact', label: '可追溯事实' }, { value: 'market_observation', label: '市场观察' }, { value: 'model_hypothesis', label: '模型假设 / 未核实' }]} /></Form.Item>
    </div>
    <Form.Item name="text" label="原始资料" rules={[{ required: true }]}><Input.TextArea rows={4} maxLength={50000} /></Form.Item>
    <Form.Item name="source_url" label="来源地址"><Input maxLength={2000} /></Form.Item>
    <Form.Item name="applicable_scope" label="适用范围" rules={[{ required: true }]}><Input maxLength={1000} /></Form.Item>
    <Space wrap><Button htmlType="submit" icon={<SaveOutlined />} loading={saving}>收录资料</Button>
      <Upload accept=".txt,.md,.markdown" showUploadList={false} beforeUpload={async (file) => {
        try { await creativeApi.upload(novelId, file); onSaved() } catch { message.error('仅支持符合大小限制的UTF-8文本资料') }
        return false
      }}><Button icon={<UploadOutlined />}>导入 TXT / Markdown</Button></Upload></Space>
  </Form>
}

function HumanReview({ novelId, records, onSaved }: { novelId: string; records: CreativeRecord[]; onSaved: () => void }) {
  const { message } = App.useApp()
  const latest = new Map(records.map((record) => [record.key, record]))
  const [saving, setSaving] = useState(false)
  const save = async (values: Record<string, unknown>) => {
    const experiment = records.find((record) => record.id === values.experiment_id)
    if (!experiment) return
    setSaving(true)
    try { await creativeApi.humanReview(novelId, experiment.id, { expected_version: experiment.version,
      reader_id: values.reader_id, order: values.order, winner: values.winner, reason: values.reason }); onSaved() }
    catch { message.error('真人配对评价保存失败，请检查版本与读者是否重复') }
    finally { setSaving(false) }
  }
  if (!latest.size) return null
  return <section className="creative-section"><h3>真人配对评价</h3><Form name="human-paired-review" layout="vertical" initialValues={{ order: 'AB', winner: 'tie' }} onFinish={(values) => void save(values)}>
    <div className="creative-form-grid">
      <Form.Item name="experiment_id" label="实验" rules={[{ required: true }]}><Select options={[...latest.values()].map((r) => ({ value: r.id, label: String(r.payload.factor) }))} /></Form.Item>
      <Form.Item name="reader_id" label="独立读者标识" rules={[{ required: true }]}><Input /></Form.Item>
      <Form.Item name="order" label="呈现顺序"><Select options={[{ value: 'AB', label: 'A → B' }, { value: 'BA', label: 'B → A' }]} /></Form.Item>
      <Form.Item name="winner" label="阅读选择"><Select options={[{ value: 'A', label: 'A 稿' }, { value: 'B', label: 'B 稿' }, { value: 'tie', label: '无差别' }]} /></Form.Item>
    </div>
    <Form.Item name="reason" label="评价理由" rules={[{ required: true }]}><Input.TextArea rows={2} /></Form.Item>
    <Button htmlType="submit" icon={<SaveOutlined />} loading={saving}>记录真人复测</Button>
  </Form></section>
}
