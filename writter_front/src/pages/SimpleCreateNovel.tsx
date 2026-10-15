import { ArrowLeftOutlined, ArrowRightOutlined, SettingOutlined } from '@ant-design/icons'
import { Alert, App, Button, Form, Input, Select, Skeleton } from 'antd'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { novelApi } from '@/api/novel'
import { AppShell } from '@/components/AppShell'
import type { GenreProfile, PlanningPresetOption } from '@/types/novel'
import './workbench/workbench.css'

interface SimpleCreationValues {
  title: string
  novel_type: string
  summary: string
}

export default function SimpleCreateNovel() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [form] = Form.useForm<SimpleCreationValues>()
  const [genres, setGenres] = useState<GenreProfile[]>([])
  const [shortPlan, setShortPlan] = useState<PlanningPresetOption>()
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    void Promise.all([novelApi.genreTaxonomy(), novelApi.planningOptions()]).then(([profiles, options]) => {
      if (controller.signal.aborted) return
      const plan = options.presets.find((item) => item.preset === 'short') || options.presets[0]
      setGenres(profiles)
      setShortPlan(plan)
      if (profiles[0]) form.setFieldValue('novel_type', profiles[0].value)
    }).catch(() => { if (!controller.signal.aborted) setLoadError(true) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [form])

  const submit = async (values: SimpleCreationValues) => {
    if (!shortPlan) return
    setSubmitting(true)
    try {
      const result = await novelApi.create({
        novel_type: values.novel_type,
        title: values.title.trim(),
        summary: values.summary.trim(),
        planning: {
          preset: shortPlan.preset,
          target_chapters: shortPlan.target_chapters,
          target_total_words: shortPlan.target_total_words,
        },
        total_outline: {
          total_chapters: shortPlan.target_chapters,
          creative_brief: {
            core_premise: values.summary.trim(),
            genre_context: { main_type: values.novel_type },
          },
        },
      })
      navigate(`/novels/${result.novel_id}`, { replace: true })
    } catch {
      message.error('作品创建失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return <AppShell>
    <main className="simple-create-page">
      <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回书架</Button>
      <div className="simple-create-layout">
        <section className="simple-create-form" aria-labelledby="simple-create-title">
          <div className="simple-create-heading">
            <span>NEW STORY</span>
            <h1 id="simple-create-title">从一个故事起点开始</h1>
            <p>先建立作品，进入对话工作台后再逐步完善设定、角色和章节。</p>
          </div>
          {loadError && <Alert type="error" showIcon message="创建选项读取失败，请确认服务可用后重试" />}
          {loading ? <Skeleton active paragraph={{ rows: 5 }} /> : <Form form={form} layout="vertical" requiredMark={false}
            onFinish={(values) => void submit(values)}>
            <Form.Item name="title" label="作品名" rules={[{ required: true, message: '请填写作品名' }]}>
              <Input size="large" maxLength={80} autoFocus placeholder="暂定名也可以" />
            </Form.Item>
            <Form.Item name="novel_type" label="小说类型" rules={[{ required: true, message: '请选择小说类型' }]}>
              <Select size="large" options={genres.map((item) => ({ value: item.value, label: item.label }))} />
            </Form.Item>
            <Form.Item name="summary" label="故事起点" rules={[{ required: true, message: '写下一句话故事起点' }]}>
              <Input.TextArea rows={6} maxLength={800} showCount placeholder="谁，在什么处境里，遇到了什么无法回避的变化？" />
            </Form.Item>
            <div className="simple-create-actions">
              <Link to="/novels/new/advanced"><SettingOutlined /> 高级创建</Link>
              <Button type="primary" size="large" htmlType="submit" loading={submitting}
                aria-label="创建并开始讨论" disabled={!shortPlan} icon={<ArrowRightOutlined />} iconPlacement="end">创建并开始讨论</Button>
            </div>
          </Form>}
        </section>
        <aside className="simple-create-note" aria-label="创建方案">
          <strong>当前方案</strong>
          <ol><li>短篇结构</li><li>对话推进</li><li>人工采用章节</li></ol>
          {shortPlan && <small>默认以 {shortPlan.target_chapters} 章短篇方案建立，可在后续规划中调整。</small>}
        </aside>
      </div>
    </main>
  </AppShell>
}
