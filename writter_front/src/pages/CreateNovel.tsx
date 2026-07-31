import { App, Button, Form, Input, InputNumber, Select, Segmented } from 'antd'
import { ArrowLeftOutlined, ArrowRightOutlined, BookOutlined } from '@ant-design/icons'
import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { useUnsavedChangesGuard, type DiscardConfirmation } from '@/hooks/useUnsavedChangesGuard'
import { novelApi } from '@/api/novel'
import { useNovelStore } from '@/stores/novelStore'
import { buildCreationSubmission, type CreationForm } from './creationSubmission'

const genreOptions = [
  ['suspense', '悬疑'], ['sci_fi', '科幻'], ['romance', '言情'], ['fantasy', '奇幻'],
  ['wuxia', '武侠'], ['xianxia', '仙侠'], ['urban', '都市'], ['history', '历史'],
  ['horror', '惊悚'], ['comedy', '喜剧'],
].map(([value, label]) => ({ value, label }))

export default function CreateNovel() {
  const navigate = useNavigate()
  const { message, modal } = App.useApp()
  const [form] = Form.useForm<CreationForm>()
  const [submitting, setSubmitting] = useState(false)
  const autoMode = useNovelStore((state) => state.autoMode)
  const setAutoMode = useNovelStore((state) => state.setAutoMode)
  const title = Form.useWatch('title', form)
  const genre = Form.useWatch('novel_type', form)
  const formValues = Form.useWatch([], form)
  const hasUnsavedChanges = Boolean(formValues && form.isFieldsTouched()) && !submitting

  const requestDiscardConfirmation = useCallback<DiscardConfirmation>((onConfirm, onCancel) => {
    modal.confirm({
      title: '放弃当前选题？',
      content: '已填写的书名、简介和创作设置将不会保留。',
      okText: '放弃并离开',
      cancelText: '继续填写',
      okButtonProps: { danger: true },
      onOk: onConfirm,
      onCancel,
    })
  }, [modal])
  const confirmDiscardChanges = useUnsavedChangesGuard(hasUnsavedChanges, requestDiscardConfirmation)

  const submit = async (values: CreationForm) => {
    setSubmitting(true)
    const { payload, startInput } = buildCreationSubmission(values)
    try {
      const result = await novelApi.create(payload)
      navigate(`/novels/${result.novel_id}`, {
        state: { startInput: { novel_id: result.novel_id, ...startInput } },
      })
    } catch {
      message.error('作品创建失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AppShell onBeforeNavigate={confirmDiscardChanges}>
      <div className="creation-page page-enter">
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => confirmDiscardChanges(() => navigate('/'))}>返回书架</Button>
        <div className="creation-layout">
          <section className="creation-form">
            <span className="eyebrow">新建选题</span>
            <h1>为故事定下第一笔</h1>
            <p className="section-lead">先提供方向，空白内容将由 AI 提案，并在手动模式下逐项交给你确认。</p>
            <Form
              form={form}
              layout="vertical"
              initialValues={{ novel_type: 'suspense', total_chapters: 12 }}
              onFinish={(values) => void submit(values)}
              requiredMark={false}
            >
              <Form.Item label="小说类型" name="novel_type" rules={[{ required: true, message: '请选择小说类型' }]}>
                <Select size="large" options={genreOptions} />
              </Form.Item>
              <Form.Item label="暂定书名" name="title">
                <Input size="large" maxLength={80} placeholder="留空则由 AI 提供候选" />
              </Form.Item>
              <Form.Item label="故事简介" name="summary">
                <Input.TextArea rows={5} maxLength={1200} placeholder="一句冲突、一个人物，或完全留空" showCount />
              </Form.Item>
              <div className="form-row">
                <Form.Item
                  label="计划章节"
                  name="total_chapters"
                  rules={[
                    { required: true, message: '请输入计划章节数' },
                    { type: 'number', min: 1, max: 200, message: '计划章节数应为 1 至 200' },
                  ]}
                >
                  <InputNumber min={1} max={200} size="large" />
                </Form.Item>
                <Form.Item label="写作风格" name="writing_style">
                  <Input size="large" maxLength={80} placeholder="例如：冷峻克制、快节奏" />
                </Form.Item>
              </div>
              <Form.Item label="推进方式">
                <Segmented
                  value={autoMode ? 'auto' : 'manual'}
                  onChange={(value) => setAutoMode(value === 'auto')}
                  options={[{ label: '逐步审阅', value: 'manual' }, { label: '自动推进', value: 'auto' }]}
                />
              </Form.Item>
              <Button type="primary" size="large" htmlType="submit" loading={submitting} icon={<ArrowRightOutlined />} iconPlacement="end">
                创建并进入工作台
              </Button>
            </Form>
          </section>

          <aside className="creation-preview" aria-label="书稿预览">
            <div className="preview-folio">NO. {new Date().getFullYear()}</div>
            <BookOutlined />
            <span>{genreOptions.find((item) => item.value === genre)?.label || '小说'}</span>
            <h2>{title || '未命名作品'}</h2>
            <div className="preview-rule" />
            <p>一部正在形成的长篇小说</p>
            <small>墨间编辑部 · 私人创作稿</small>
          </aside>
        </div>
      </div>
    </AppShell>
  )
}
