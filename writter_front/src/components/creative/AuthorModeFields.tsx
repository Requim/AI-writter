import { Alert, Form, Input, InputNumber, Select, Switch } from 'antd'
import { useEffect, useState } from 'react'
import type { FormInstance } from 'antd'
import { creativeApi } from '@/api/creative'
import type { CreativeOptions } from '@/types/creative'
import type { CreationForm } from '@/pages/creationSubmission'

export function AuthorModeFields({ form }: { form: FormInstance<CreationForm> }) {
  const [options, setOptions] = useState<CreativeOptions>()
  const [failed, setFailed] = useState(false)
  const enabled = Form.useWatch('autonomous_author', form)
  const chapters = Form.useWatch('total_chapters', form) || 1
  const prep = Form.useWatch('creative_preparation_budget', form) ?? 60
  const perChapter = Form.useWatch('creative_chapter_budget', form) ?? 32
  const review = Form.useWatch('creative_review_budget', form) ?? 20 + 8 * chapters
  useEffect(() => { let mounted = true
    creativeApi.options().then((value) => { if (mounted) setOptions(value) })
      .catch(() => { if (mounted) setFailed(true) })
    return () => { mounted = false }
  }, [])
  return <section className="author-mode-fields">
    <Form.Item name="autonomous_author" label="自主作家模式" valuePropName="checked">
      <Switch disabled={!options?.enabled || failed} />
    </Form.Item>
    {!options?.enabled && <span className="creative-muted">{failed ? '自主模式配置读取失败' : '自主模式未开放'}</span>}
    {enabled && <>
      <Form.Item name="narrative_mode" label="叙事承诺" initialValue="auto">
        <Select options={[{ value: 'auto', label: '立项时选定' }, { value: 'stable', label: '稳定主角' }, { value: 'ensemble_relay', label: '群像接力' }]} />
      </Form.Item>
      <Form.Item name="target_readers" label="目标读者"><Input maxLength={2000} /></Form.Item>
      <Form.Item name="author_question" label="作者想探讨的问题"><Input.TextArea rows={2} maxLength={2000} /></Form.Item>
      <Form.Item name="hard_constraints" label="不可变设定"><Input.TextArea rows={3} maxLength={10000} /></Form.Item>
      <Form.Item name="research_queries" label="公开资料检索主题"><Input.TextArea rows={2} maxLength={720} /></Form.Item>
      <div className="planning-number-fields">
        <Form.Item name="creative_preparation_budget" label="准备请求上限" initialValue={60}><InputNumber min={1} max={60} /></Form.Item>
        <Form.Item name="creative_chapter_budget" label="每章请求上限" initialValue={32}><InputNumber min={1} max={32} /></Form.Item>
        <Form.Item name="creative_review_budget" label="复盘共享上限"><InputNumber min={0} max={20 + 8 * chapters} placeholder={String(20 + 8 * chapters)} /></Form.Item>
      </div>
      <Alert showIcon type={prep + perChapter * chapters + review > (options?.request_limit ?? 10000) ? 'error' : 'info'}
        title={`全书模型请求上限 ${prep + perChapter * chapters + review} 次 · 检索上限 12 次`}
        description={`租户上限 ${options?.request_limit ?? 0} 次；按请求计量，不是精确金额预算。`} />
    </>}
  </section>
}
