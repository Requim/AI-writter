import { ArrowLeftOutlined, ArrowRightOutlined, BookOutlined, SettingOutlined } from '@ant-design/icons'
import { App, Button, Collapse, Form, Input, InputNumber, Segmented, Select, Skeleton } from 'antd'
import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { FormInstance } from 'antd'
import { AppShell } from '@/components/AppShell'
import { useUnsavedChangesGuard, type DiscardConfirmation } from '@/hooks/useUnsavedChangesGuard'
import { novelApi } from '@/api/novel'
import { useQuota } from '@/stores/quotaStore'
import { useNovelStore } from '@/stores/novelStore'
import type { QuotaUsage } from '@/types/auth'
import { buildCreationSubmission, type CreationForm } from './creationSubmission'
import { quotaBlocksCreation, quotaNoticeDetails } from './creationQuota'

const genreOptions = [
  ['suspense', '悬疑'], ['sci_fi', '科幻'], ['romance', '言情'], ['fantasy', '奇幻'],
  ['wuxia', '武侠'], ['xianxia', '仙侠'], ['urban', '都市'], ['history', '历史'],
  ['horror', '惊悚'], ['comedy', '喜剧'],
].map(([value, label]) => ({ value, label }))

function useDiscardDraft(form: FormInstance<CreationForm>, submitting: boolean) {
  const { modal } = App.useApp()
  const values = Form.useWatch([], form)
  const dirty = Boolean(values && form.isFieldsTouched()) && !submitting
  const request = useCallback<DiscardConfirmation>((onConfirm, onCancel) => {
    modal.confirm({
      title: '放弃当前选题？', content: '已填写的书名、简介和创作设置将不会保留。',
      okText: '放弃并离开', cancelText: '继续填写', okButtonProps: { danger: true },
      onOk: onConfirm, onCancel,
    })
  }, [modal])
  return useUnsavedChangesGuard(dirty, request)
}

function CoreFields({ autoMode, onModeChange }: { autoMode: boolean; onModeChange: (value: boolean) => void }) {
  return <>
    <Form.Item label="小说类型" name="novel_type" rules={[{ required: true, message: '请选择小说类型' }]}>
      <Select size="large" options={genreOptions} />
    </Form.Item>
    <Form.Item label="核心设想" name="core_premise">
      <Input.TextArea rows={3} maxLength={800} placeholder="这个故事最独特的处境、矛盾或反常识设定" showCount />
    </Form.Item>
    <Form.Item label="读者体验" name="reader_promise">
      <Input size="large" maxLength={160} placeholder="例如：持续解谜，并在真相揭晓时获得情感回响" />
    </Form.Item>
    <Form.Item label="推进方式">
      <Segmented value={autoMode ? 'auto' : 'manual'} onChange={(value) => onModeChange(value === 'auto')}
        options={[{ label: '逐步审阅', value: 'manual' }, { label: '自动推进', value: 'auto' }]} />
    </Form.Item>
  </>
}

function AdvancedFields() {
  return <div className="advanced-fields">
    <Form.Item label="暂定书名" name="title"><Input size="large" maxLength={80} placeholder="留空则由 AI 提供候选" /></Form.Item>
    <Form.Item label="故事简介" name="summary"><Input.TextArea rows={4} maxLength={1200} placeholder="留空则分别生成读者文案和内部简报" showCount /></Form.Item>
    <div className="setting-row">
      <Form.Item label="故事时代" name="setting_era"><Input size="large" maxLength={80} placeholder="如：北宋末年、当代、近未来" /></Form.Item>
      <Form.Item label="主要地域" name="setting_region"><Input size="large" maxLength={100} placeholder="如：江南水乡、架空北方边城" /></Form.Item>
    </div>
    <Form.Item label="命名偏好" name="naming_preference">
      <Input.TextArea rows={2} maxLength={300} placeholder="如：偏爱《诗经》典故，姓名清雅但不生僻" showCount />
    </Form.Item>
    <Form.Item label="内容边界" name="content_boundaries"><Input.TextArea rows={2} maxLength={400} placeholder="不希望出现的情节、尺度或表达方式" showCount /></Form.Item>
    <div className="form-row">
      <Form.Item label="计划章节" name="total_chapters" rules={[
        { required: true, message: '请输入计划章节数' },
        { type: 'number', min: 1, max: 200, message: '计划章节数应为 1 至 200' },
      ]}><InputNumber min={1} max={200} size="large" /></Form.Item>
      <Form.Item label="写作风格" name="writing_style"><Input size="large" maxLength={80} placeholder="例如：冷峻克制、快节奏" /></Form.Item>
    </div>
  </div>
}

interface QuotaNoticeProps { quota?: QuotaUsage; loading: boolean; chapters?: number }

function QuotaNotice({ quota, loading, chapters }: QuotaNoticeProps) {
  if (loading) return <div className="creation-quota"><Skeleton.Input active size="small" /></div>
  const details = quotaNoticeDetails(quota, chapters)
  return <div className="creation-quota" data-state={details.state}>
    <span>{quota ? <>本月剩余 <strong>{quota.remaining}</strong> / {quota.limit} 次</> : '额度暂时无法读取'}</span>
    <small>{details.detail}</small>
  </div>
}

function CreationPreview({ title, genre }: { title?: string; genre?: string }) {
  return <aside className="creation-preview" aria-label="书稿预览">
    <div className="preview-folio">NO. {new Date().getFullYear()}</div><BookOutlined />
    <span>{genreOptions.find((item) => item.value === genre)?.label || '小说'}</span>
    <h2>{title || '未命名作品'}</h2><div className="preview-rule" />
    <p>一部正在形成的长篇小说</p><small>墨间编辑部 · 私人创作稿</small>
  </aside>
}

export default function CreateNovel() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [form] = Form.useForm<CreationForm>()
  const [submitting, setSubmitting] = useState(false)
  const autoMode = useNovelStore((state) => state.autoMode)
  const setAutoMode = useNovelStore((state) => state.setAutoMode)
  const title = Form.useWatch('title', form)
  const genre = Form.useWatch('novel_type', form)
  const chapters = Form.useWatch('total_chapters', form)
  const { quota, loading: quotaLoading } = useQuota()
  const confirmDiscard = useDiscardDraft(form, submitting)
  const quotaBlocked = quotaBlocksCreation(quota)
  const submit = async (values: CreationForm) => {
    setSubmitting(true)
    const { payload, startInput } = buildCreationSubmission(values)
    try {
      const result = await novelApi.create(payload)
      navigate(`/novels/${result.novel_id}`, { state: { startInput: { novel_id: result.novel_id, ...startInput } } })
    } catch { message.error('作品创建失败，请稍后重试') } finally { setSubmitting(false) }
  }
  return <AppShell onBeforeNavigate={confirmDiscard}>
    <div className="creation-page page-enter">
      <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => confirmDiscard(() => navigate('/'))}>返回书架</Button>
      <div className="creation-layout"><section className="creation-form">
        <span className="eyebrow">新建选题</span><h1>为故事定下第一笔</h1>
        <p className="section-lead">先给出故事方向；空白内容由 AI 提案，手动模式会逐项交给你确认。</p>
        <Form form={form} layout="vertical" initialValues={{ novel_type: 'suspense', total_chapters: 12 }} onFinish={(values) => void submit(values)} requiredMark={false}>
          <CoreFields autoMode={autoMode} onModeChange={setAutoMode} />
          <Collapse ghost className="advanced-settings" items={[{ key: 'advanced', label: <span><SettingOutlined /> 更多创作约束</span>, children: <AdvancedFields /> }]} />
          <QuotaNotice quota={quota} loading={quotaLoading} chapters={chapters} />
          <Button type="primary" size="large" htmlType="submit" disabled={quotaBlocked} loading={submitting} icon={<ArrowRightOutlined />} iconPlacement="end">创建并进入工作台</Button>
        </Form>
      </section><CreationPreview title={title} genre={genre} /></div>
    </div>
  </AppShell>
}
