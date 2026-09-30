import { App, Button, Form, Input, Select } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useState } from 'react'
import { creativeApi } from '@/api/creative'
import type { ChapterDetail } from '@/types/novel'
import { excerptEvidence } from './excerptEvidence'

interface FeedbackFields { reader_id: string; issue_key: string; category: string; source: string; quote: string; comment: string }

export function CreativeFeedbackForm({ novelId, chapter, onSaved }: { novelId: string; chapter?: ChapterDetail | null; onSaved: () => void }) {
  const [form] = Form.useForm<FeedbackFields>()
  const [saving, setSaving] = useState(false)
  const { message } = App.useApp()
  const submit = async (values: FeedbackFields) => {
    if (!chapter) return
    setSaving(true)
    try {
      const { quote, ...payload } = values
      await creativeApi.feedback(novelId, { ...payload, evidence: [await excerptEvidence(chapter, quote)] })
      form.resetFields(); onSaved()
    } catch (error) { message.error(error instanceof Error ? error.message : '反馈保存失败') }
    finally { setSaving(false) }
  }
  return <Form form={form} layout="vertical" onFinish={(values) => void submit(values)} initialValues={{ source: 'human_reader', category: 'pace' }}>
    <div className="creative-form-grid">
      <Form.Item name="source" label="反馈来源"><Select options={[{ value: 'human_reader', label: '真人读者' }, { value: 'author_instruction', label: '作者指令' }, { value: 'simulated_reader', label: '模拟读者' }]} /></Form.Item>
      <Form.Item name="reader_id" label="独立读者标识" rules={[{ required: true }]}><Input maxLength={120} /></Form.Item>
      <Form.Item name="issue_key" label="同类问题标识" rules={[{ required: true }]}><Input maxLength={120} /></Form.Item>
      <Form.Item name="category" label="问题分类"><Select options={Object.entries({ pace: '节奏', style: '文风', character: '人物', understanding: '理解', fact: '事实', plot: '剧情' }).map(([value, label]) => ({ value, label }))} /></Form.Item>
    </div>
    <Form.Item name="quote" label={chapter ? `第 ${chapter.chapter_index + 1} 章 V${chapter.version} 原文引用` : '先在目录选定章节'} rules={[{ required: true }]}>
      <Input.TextArea rows={3} maxLength={2000} disabled={!chapter} />
    </Form.Item>
    <Form.Item name="comment" label="评价及理由" rules={[{ required: true }]}><Input.TextArea rows={3} maxLength={4000} /></Form.Item>
    <Button htmlType="submit" icon={<PlusOutlined />} loading={saving} disabled={!chapter}>记录反馈</Button>
  </Form>
}
