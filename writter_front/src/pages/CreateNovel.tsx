import { App, Button, Form, Input, InputNumber, Select, Segmented } from 'antd'
import { ArrowLeftOutlined, ArrowRightOutlined, BookOutlined } from '@ant-design/icons'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { novelApi } from '@/api/novel'
import { useNovelStore } from '@/stores/novelStore'
import type { NovelCreateRequest } from '@/types/novel'

interface CreationForm {
  novel_type: string
  title?: string
  summary?: string
  total_chapters: number
  writing_style?: string
}

const genreOptions = [
  ['suspense', '悬疑'], ['sci_fi', '科幻'], ['romance', '言情'], ['fantasy', '奇幻'],
  ['wuxia', '武侠'], ['xianxia', '仙侠'], ['urban', '都市'], ['history', '历史'],
  ['horror', '惊悚'], ['comedy', '喜剧'],
].map(([value, label]) => ({ value, label }))

export default function CreateNovel() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [form] = Form.useForm<CreationForm>()
  const [submitting, setSubmitting] = useState(false)
  const autoMode = useNovelStore((state) => state.autoMode)
  const setAutoMode = useNovelStore((state) => state.setAutoMode)
  const title = Form.useWatch('title', form)
  const genre = Form.useWatch('novel_type', form)

  const submit = async (values: CreationForm) => {
    setSubmitting(true)
    const payload: NovelCreateRequest = {
      novel_type: values.novel_type,
      title: values.title?.trim() || undefined,
      summary: values.summary?.trim() || undefined,
      total_outline: values.total_chapters || values.writing_style ? {
        total_chapters: values.total_chapters,
        writing_style: values.writing_style,
      } : undefined,
    }
    try {
      const result = await novelApi.create(payload)
      navigate(`/novels/${result.novel_id}`, {
        state: { startInput: { novel_id: result.novel_id, novel_type: values.novel_type } },
      })
    } catch {
      message.error('创建失败，请检查后端与数据库配置')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AppShell>
      <div className="creation-page page-enter">
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回书架</Button>
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
                <Form.Item label="计划章节" name="total_chapters">
                  <InputNumber min={1} max={200} size="large" />
                </Form.Item>
                <Form.Item label="写作风格" name="writing_style">
                  <Input size="large" placeholder="例如：冷峻克制、快节奏" />
                </Form.Item>
              </div>
              <Form.Item label="推进方式">
                <Segmented
                  value={autoMode ? 'auto' : 'manual'}
                  onChange={(value) => setAutoMode(value === 'auto')}
                  options={[{ label: '逐步审阅', value: 'manual' }, { label: '自动推进', value: 'auto' }]}
                />
              </Form.Item>
              <Button type="primary" size="large" htmlType="submit" loading={submitting} icon={<ArrowRightOutlined />} iconPosition="end">
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
