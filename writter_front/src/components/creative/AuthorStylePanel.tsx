import { App, Button, Checkbox, Form, Input, Select, Space, Tag } from 'antd'
import { PlusOutlined, SaveOutlined } from '@ant-design/icons'
import { useEffect, useState } from 'react'
import { creativeApi } from '@/api/creative'
import type { AuthorRecord, CreativeOverview } from '@/types/creative'

interface SampleFields { original: string; revision?: string; judgment: string; reason: string; original_confirmed: boolean }

export function AuthorStylePanel({ novelId, overview, onSaved }: { novelId: string; overview: CreativeOverview; onSaved: () => void }) {
  const [samples, setSamples] = useState<AuthorRecord[]>([])
  const [profiles, setProfiles] = useState<AuthorRecord[]>([])
  const [busy, setBusy] = useState(false)
  const [form] = Form.useForm<SampleFields>()
  const { message } = App.useApp()
  const reload = async () => {
    const [sampleData, profileData] = await Promise.all([creativeApi.authorRecords('samples'), creativeApi.authorRecords('profiles')])
    setSamples(sampleData); setProfiles(profileData)
  }
  useEffect(() => {
    let active = true
    Promise.all([creativeApi.authorRecords('samples'), creativeApi.authorRecords('profiles')])
      .then(([sampleData, profileData]) => { if (active) { setSamples(sampleData); setProfiles(profileData) } })
      .catch(() => { if (active) message.error('作者档案读取失败') })
    return () => { active = false }
  }, [novelId, message])
  const saveSample = async (values: SampleFields) => {
    setBusy(true)
    try {
      await creativeApi.authorSample({ sample: { ...values, scope: 'book', novel_id: novelId, category: 'style' } })
      form.resetFields(); await reload(); onSaved()
    } catch { message.error('原创样例保存失败') } finally { setBusy(false) }
  }
  return <div>
    <Space wrap><Tag>当前档案：{overview.session.config.author_profile_version ? `V${overview.session.config.author_profile_version}` : '未绑定，沿用现有风格'}</Tag><Tag>原创样例 {samples.length}</Tag></Space>
    <Form name="author-sample" form={form} layout="vertical" onFinish={(values) => void saveSample(values)} initialValues={{ judgment: 'reference' }}>
      <div className="creative-form-grid">
        <Form.Item name="original" label="原创原稿" rules={[{ required: true }]}><Input.TextArea rows={5} maxLength={50000} /></Form.Item>
        <Form.Item name="revision" label="修改稿"><Input.TextArea rows={5} maxLength={50000} /></Form.Item>
      </div>
      <Form.Item name="judgment" label="评价"><Select options={[{ value: 'reference', label: '认可的参考样章' }, { value: 'accepted', label: '认可修改' }, { value: 'rejected', label: '否决修改' }]} /></Form.Item>
      <Form.Item name="reason" label="认可或否决的理由" rules={[{ required: true }]}><Input.TextArea rows={2} maxLength={4000} /></Form.Item>
      <Form.Item name="original_confirmed" valuePropName="checked" rules={[{ validator: (_, value) => value ? Promise.resolve() : Promise.reject(new Error('请确认原创来源')) }]}>
        <Checkbox>确认由我提供或认可的原创样例，范围为本书</Checkbox>
      </Form.Item>
      <Button htmlType="submit" icon={<PlusOutlined />} loading={busy}>记录原创对照</Button>
    </Form>
    <ProfileForm novelId={novelId} samples={samples} profiles={profiles} overview={overview} onSaved={() => { void reload(); onSaved() }} />
  </div>
}

interface PreferenceFields { name: string; sample_id: string; aspect: string; value: string; reason: string }

function ProfileForm({ novelId, samples, profiles, overview, onSaved }: {
  novelId: string; samples: AuthorRecord[]; profiles: AuthorRecord[]; overview: CreativeOverview; onSaved: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<string>()
  const { message } = App.useApp()
  const save = async (values: PreferenceFields) => {
    setBusy(true)
    try {
      await creativeApi.authorProfile({ profile: { name: values.name, preferences: [{
        preference_id: crypto.randomUUID(), aspect: values.aspect, value: values.value, reason: values.reason,
        sample_ids: [values.sample_id], strength: 'soft', scope: 'book', novel_id: novelId,
        tasks: ['topic', 'character', 'prose', 'revision'],
      }] } })
      onSaved()
    } catch { message.error('作者档案保存失败') } finally { setBusy(false) }
  }
  const bind = async () => {
    const profile = profiles.find((item) => item.id === selected)
    if (!profile) return
    setBusy(true)
    try {
      await creativeApi.bindProfile(novelId, { expected_session_version: overview.session.version, profile_id: profile.key,
        profile_version: profile.version, apply_to_current_book: true, reason: '作者在章边界明确选用档案' })
      onSaved()
    } catch { message.error('切换失败，请确认已暂停在章边界并刷新版本') } finally { setBusy(false) }
  }
  return <section className="creative-section">
    <h3>明确的作者偏好</h3>
    <Form<PreferenceFields> name="author-preference" layout="vertical" onFinish={(values) => void save(values)}>
      <div className="creative-form-grid">
        <Form.Item name="name" label="档案名称" rules={[{ required: true }]}><Input maxLength={120} /></Form.Item>
        <Form.Item name="sample_id" label="原创依据" rules={[{ required: true }]}><Select options={samples.map((s) => ({ value: s.key, label: String(s.payload.reason).slice(0, 45) }))} /></Form.Item>
        <Form.Item name="aspect" label="审美维度" rules={[{ required: true }]}><Input maxLength={120} /></Form.Item>
        <Form.Item name="value" label="明确取舍" rules={[{ required: true }]}><Input maxLength={1000} /></Form.Item>
      </div>
      <Form.Item name="reason" label="选择理由" rules={[{ required: true }]}><Input.TextArea rows={2} maxLength={2000} /></Form.Item>
      <Button htmlType="submit" loading={busy} icon={<SaveOutlined />}>创建档案版本</Button>
    </Form>
    <Space.Compact className="creative-binding">
      <Select placeholder="选择作者档案版本" value={selected} onChange={setSelected}
        options={profiles.map((p) => ({ value: p.id, label: `${String(p.payload.name)} · V${p.version}` }))} />
      <Button icon={<SaveOutlined />} disabled={!selected} loading={busy} onClick={() => void bind()}>应用当前书</Button>
    </Space.Compact>
  </section>
}
