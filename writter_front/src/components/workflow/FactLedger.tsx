import { Alert, Button, Drawer, Empty, Form, Input, InputNumber, Modal, Select, Space, Table, Tabs, Tag, Tooltip } from 'antd'
import { DatabaseOutlined, ReloadOutlined } from '@ant-design/icons'
import { useState } from 'react'
import axios from 'axios'
import { apiClient } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import type { InterruptInfo } from '@/types/novel'
import { FactReview } from './FactReview'

type Entity = { id: string; name: string; kind: string; entity_key: string }
type Fact = { subject_id: string; predicate: string; value_text?: string; object_entity_id?: string; version: number; status: string; valid_from_chapter: number; valid_to_chapter?: number; evidence: { quote: string; source_ref: string } }
type Ledger = { entities: Entity[]; fact_heads: Fact[] }
type Preview = { token: string; previous: Fact | null; proposal: { fact: Fact; expected_version: number } }
type Conflict = { chapter_id: string; chapter_number: number; title: string; status: string; report?: { reasons: string[]; findings: { message: string; expected_evidence?: { quote: string }; actual_evidence?: { quote: string } }[] } }
const predicates: Record<string, string> = { surname: '姓氏', family: '家族', ancestral_hall_owner: '祠堂归属', location: '地点', life_status: '生命状态' }
const states: Record<string, string> = { confirmed: '已确认', retracted: '已撤回', pass: '已核对', unknown: '存在未确认事实', blocked: '明确冲突', legacy_unverified: '历史章节未验证', manual_edit_unverified: '手工修改后未验证' }

function errorText(error: unknown) {
  if (axios.isAxiosError(error) && typeof error.response?.data?.detail === 'string') return error.response.data.detail
  return '事实台账暂时不可用，请重试'
}

type Props = { novelId: string; activeReview?: InterruptInfo; onResume?: (value: unknown) => void }

export function FactLedger(props: Props) {
  const tenant = useAuthStore(state => state.currentTenantId)
  return <FactLedgerView key={tenant + ':' + props.novelId} {...props} />
}

function useLedger(novelId: string) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<Ledger>({ entities: [], fact_heads: [] })
  const [conflicts, setConflicts] = useState<Conflict[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<Preview | null>(null)
  const [history, setHistory] = useState<Fact[] | null>(null)
  const [form] = Form.useForm()
  const [entityForm] = Form.useForm()
  const predicate = Form.useWatch('predicate', form)
  const base = '/v1/novels/' + novelId + '/facts'
  const name = (id?: string) => data.entities.find(entity => entity.id === id)?.name || '未登记'
  const value = (fact: Fact) => fact.value_text || name(fact.object_entity_id)
  const load = async () => {
    setBusy(true); setError('')
    try {
      const [ledger, reports] = await Promise.all([apiClient.get<Ledger>(base), apiClient.get<Conflict[]>(base + '/conflicts')])
      setData(ledger.data); setConflicts(reports.data)
    } catch (failure) { setError(errorText(failure)) } finally { setBusy(false) }
  }
  const showHistory = async (fact: Fact) => {
    try { setHistory((await apiClient.get<Fact[]>(base + '/history/' + fact.subject_id + '/' + fact.predicate)).data) }
    catch (failure) { setError(errorText(failure)) }
  }
  return { open, setOpen, data, conflicts, busy, setBusy, error, setError, preview, setPreview, history, setHistory,
    form, entityForm, predicate, base, name, value, load, showHistory }
}
type LedgerState = ReturnType<typeof useLedger>

function ledgerActions(model: LedgerState) {
  const { form, entityForm, data, setBusy, setError, base, setPreview, preview, load } = model
  const propose = async () => {
    try {
      const input = await form.validateFields()
      setBusy(true); setError('')
      const previous = data.fact_heads.find(fact => fact.subject_id === input.subject_id && fact.predicate === input.predicate)
      const relation = ['family', 'ancestral_hall_owner', 'location'].includes(input.predicate)
      const response = await apiClient.post<Preview>(base + '/proposals', { ...input,
        value_text: relation ? null : input.value_text, object_entity_id: relation ? input.object_entity_id : null,
        expected_version: previous?.version || 0 })
      setPreview(response.data)
    } catch (failure) { setError(errorText(failure)) } finally { setBusy(false) }
  }
  const confirm = async () => {
    if (!preview) return
    setBusy(true)
    try { await apiClient.post(base + '/confirm', { token: preview.token }); setPreview(null); form.resetFields(); await load() }
    catch (failure) { setPreview(null); setError(errorText(failure)) } finally { setBusy(false) }
  }
  const createEntity = async () => {
    try {
      const input = await entityForm.validateFields(); setBusy(true)
      await apiClient.post(base + '/entities', { ...input, entity_key: 'manual:' + crypto.randomUUID() })
      entityForm.resetFields(); await load()
    } catch (failure) { setError(errorText(failure)) } finally { setBusy(false) }
  }
  return { propose, confirm, createEntity }
}
type LedgerModel = LedgerState & ReturnType<typeof ledgerActions>

function LedgerTable({ model }: { model: LedgerModel }) {
  const { name, value, form, showHistory, data, busy } = model
  const columns = [
    { title: '主体', key: 'subject', render: (_: unknown, fact: Fact) => name(fact.subject_id) },
    { title: '属性', dataIndex: 'predicate', render: (text: string) => predicates[text] || '其他属性' },
    { title: '事实', key: 'value', render: (_: unknown, fact: Fact) => value(fact) },
    { title: '版本', dataIndex: 'version' },
    { title: '状态', dataIndex: 'status', render: (text: string) => states[text] || '待核对' },
    { title: '操作', key: 'actions', render: (_: unknown, fact: Fact) => <Space><Button aria-label="纠错" onClick={() => form.setFieldsValue({ ...fact, reason: '' })}>纠错</Button><Button onClick={() => void showHistory(fact)}>历史</Button></Space> },
  ]
  return <Table rowKey={fact => fact.subject_id + ':' + fact.predicate} dataSource={data.fact_heads} columns={columns} loading={busy} scroll={{ x: 680 }} pagination={{ pageSize: 8 }} />
}

function LedgerForm({ model }: { model: LedgerModel }) {
  const { form, entityForm, predicate, data, busy, setPreview, propose, createEntity } = model
  return <>
          <h3>新增或修正事实</h3>
          <Form form={form} layout="vertical" initialValues={{ predicate: 'surname', status: 'confirmed', valid_from_chapter: 1 }} onValuesChange={() => setPreview(null)}>
            <Form.Item name="subject_id" label="事实主体" rules={[{ required: true }]}><Select showSearch optionFilterProp="label" options={data.entities.map(entity => ({ value: entity.id, label: entity.name }))} /></Form.Item>
            <Form.Item name="predicate" label="属性" rules={[{ required: true }]}><Select options={Object.entries(predicates).map(([value, label]) => ({ value, label }))} /></Form.Item>
            {['family', 'ancestral_hall_owner', 'location'].includes(predicate)
              ? <Form.Item name="object_entity_id" label="归属对象或地点" rules={[{ required: true }]}><Select options={data.entities.map(entity => ({ value: entity.id, label: entity.name }))} /></Form.Item>
              : <Form.Item name="value_text" label="事实内容" rules={[{ required: true }]}><Input maxLength={2000} /></Form.Item>}
            <Space wrap><Form.Item name="valid_from_chapter" label="生效起始章" rules={[{ required: true }]}><InputNumber min={1} precision={0} /></Form.Item>
              <Form.Item name="valid_to_chapter" label="生效结束章"><InputNumber min={1} precision={0} /></Form.Item>
              <Form.Item name="status" label="状态"><Select style={{ width: 140 }} options={[{ value: 'confirmed', label: '确认事实' }, { value: 'retracted', label: '撤回事实' }]} /></Form.Item></Space>
            <Form.Item name="reason" label="确认依据或纠错原因" rules={[{ required: true }]}><Input.TextArea maxLength={2000} rows={3} /></Form.Item>
            <Button aria-label="预览事实变更" type="primary" loading={busy} onClick={() => void propose()}>预览事实变更</Button>
          </Form>
          <h3>登记实体</h3><Form form={entityForm} layout="vertical"><Form.Item name="name" label="名称" rules={[{ required: true }]}><Input maxLength={200} /></Form.Item>
            <Form.Item name="kind" label="类型" rules={[{ required: true }]}><Select options={[{ value: 'character', label: '人物' }, { value: 'family', label: '家族' }, { value: 'place', label: '地点' }, { value: 'item', label: '物品' }]} /></Form.Item>
            <Button loading={busy} onClick={() => void createEntity()}>登记实体</Button></Form>

  </>
}

function ConflictRecords({ model, activeReview, onResume }: { model: LedgerModel } & Pick<Props, 'activeReview' | 'onResume'>) {
  const { conflicts } = model
  return <>
          {activeReview?.action === 'fact_review_required' && onResume && <FactReview interrupt={activeReview} onResume={onResume} />}
          {conflicts.length ? conflicts.map(chapter => <section key={chapter.chapter_id} style={{ padding: '12px 0', borderBottom: '1px solid #ddd' }}>
          <h3>第 {chapter.chapter_number} 章 {chapter.title}</h3><Tag>{states[chapter.status] || '待核对'}</Tag>
          {chapter.report?.reasons.map((reason, index) => <p key={index}>{reason}</p>)}
          {chapter.report?.findings.map((finding, index) => <div key={index}><strong>{finding.message}</strong><p>已确认依据：{finding.expected_evidence?.quote || '暂无'}</p><p>稿件原文：{finding.actual_evidence?.quote || '暂无'}</p></div>)}
        </section>) : <Empty description="暂无已归档章节记录" />}
  </>
}

function LedgerModals({ model }: { model: LedgerModel }) {
  const { preview, setPreview, confirm, busy, value, history, setHistory } = model
  return <>
    <Modal title="确认事实变更" open={!!preview} onCancel={() => setPreview(null)} onOk={() => void confirm()} confirmLoading={busy} okText="确认追加版本" cancelText="返回修改">
      {preview && <><p>原事实：{preview.previous ? value(preview.previous) + '（版本 ' + preview.previous.version + '）' : '尚未建立'}</p>
        <p>新事实：{value(preview.proposal.fact)}（版本 {preview.proposal.expected_version + 1}）</p><p>依据：{preview.proposal.fact.evidence.quote}</p>
        <p>生效章节：{preview.proposal.fact.valid_from_chapter} 至 {preview.proposal.fact.valid_to_chapter || '后续章节'}</p><p>状态：{states[preview.proposal.fact.status]}</p></>}
    </Modal>
    <Modal title="事实版本历史" open={history !== null} footer={null} onCancel={() => setHistory(null)}>
      {history?.map(fact => <section key={fact.version}><h3>版本 {fact.version}：{value(fact)}</h3><p>{states[fact.status]}，从第 {fact.valid_from_chapter} 章生效</p><p>{fact.evidence.quote}</p></section>)}
    </Modal>

  </>
}

function FactLedgerView({ novelId, activeReview, onResume }: Props) {
  const state = useLedger(novelId)
  const model = { ...state, ...ledgerActions(state) }
  const { open, setOpen, load, setPreview, busy, error, setError } = model
  return <>
    <Tooltip title="事实台账与冲突中心"><Button aria-label="事实台账与冲突中心" icon={<DatabaseOutlined />} onClick={() => { setOpen(true); void load() }} /></Tooltip>
    <Drawer title="事实台账与冲突中心" open={open} onClose={() => { setOpen(false); setPreview(null) }} size={850} styles={{ wrapper: { maxWidth: '100vw' } }}
      extra={<Button aria-label="刷新事实台账" icon={<ReloadOutlined />} onClick={() => void load()} loading={busy} />}>
      {error && <Alert type="error" showIcon title={error} closable onClose={() => setError('')} />}
      <Tabs items={[
        { key: 'facts', label: '事实台账', children: <><LedgerTable model={model} /><LedgerForm model={model} /></> },
        { key: 'conflicts', label: '冲突与章节记录', children: <ConflictRecords model={model} activeReview={activeReview} onResume={onResume} /> },
      ]} />
    </Drawer>
    <LedgerModals model={model} />
  </>
}
