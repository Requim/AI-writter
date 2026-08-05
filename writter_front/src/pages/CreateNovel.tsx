import { ArrowLeftOutlined, ArrowRightOutlined, BookOutlined, SettingOutlined } from '@ant-design/icons'
import { Alert, App, Button, Collapse, Form, Input, InputNumber, Segmented, Select, Skeleton } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import type { FormInstance } from 'antd'
import { AppShell } from '@/components/AppShell'
import { useUnsavedChangesGuard, type DiscardConfirmation } from '@/hooks/useUnsavedChangesGuard'
import { novelApi } from '@/api/novel'
import { useGenreTaxonomy } from '@/hooks/useGenreTaxonomy'
import { usePlanningOptions } from '@/hooks/usePlanningOptions'
import { DEFAULT_TOTAL_CHAPTERS, useQuota } from '@/stores/quotaStore'
import { useNovelStore } from '@/stores/novelStore'
import type { QuotaUsage } from '@/types/auth'
import type { GenreProfile, PlanningOptions } from '@/types/novel'
import { buildCreationSubmission, type CreationForm } from './creationSubmission'
import { quotaBlocksCreation, quotaNoticeDetails } from './creationQuota'
import { genreDefaults, selectedGenreProfile } from './genreSelection'

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

interface CoreFieldsProps {
  autoMode: boolean
  genreError: boolean
  genreLoading: boolean
  genreProfiles: GenreProfile[]
  selectedProfile?: GenreProfile
  onModeChange: (value: boolean) => void
  onGenreChange: (value: string) => void
}

function CoreFields({
  autoMode,
  genreError,
  genreLoading,
  genreProfiles,
  selectedProfile,
  onModeChange,
  onGenreChange,
}: CoreFieldsProps) {
  const profileOptions = genreProfiles.map((profile) => ({ value: profile.value, label: profile.label }))
  return <>
    {genreError && <Alert type="error" showIcon message="题材分类无法读取，请确认后端服务已启动" />}
    <Form.Item label="小说类型" name="novel_type" rules={[{ required: true, message: '请选择小说类型' }]}>
      <Select size="large" loading={genreLoading} disabled={genreLoading || genreError} options={profileOptions}
        onChange={onGenreChange} />
    </Form.Item>
    <div className="genre-grid">
      <Form.Item label="子类型" name="subgenre" rules={[{ required: true, message: '请选择子类型' }]}>
        <Select size="large" disabled={!selectedProfile || genreError}
          options={(selectedProfile?.subgenres || []).map((item) => ({ value: item.value, label: item.label }))} />
      </Form.Item>
      <Form.Item label="读者快感" name="reader_experience" rules={[{ required: true, message: '请选择读者快感' }]}>
        <Select size="large" disabled={!selectedProfile || genreError}
          options={(selectedProfile?.reader_experiences || []).map((item) => ({ value: item.value, label: item.label }))} />
      </Form.Item>
      <Form.Item label="叙事节奏" name="narrative_pace" rules={[{ required: true, message: '请选择叙事节奏' }]}>
        <Select size="large" disabled={!selectedProfile || genreError}
          options={(selectedProfile?.pace_options || []).map((item) => ({ value: item.value, label: item.label }))} />
      </Form.Item>
    </div>
    <Form.Item label="核心设想" name="core_premise">
      <Input.TextArea rows={3} maxLength={800} placeholder="这个故事最独特的处境、矛盾或反常识设定" showCount />
    </Form.Item>
    <Form.Item label="读者体验" name="reader_promise">
      <Input size="large" maxLength={160} placeholder="例如：持续解谜，并在真相揭晓时获得情感回响" />
    </Form.Item>
    <Form.Item label="推进方式">
      <Segmented value={autoMode ? 'auto' : 'manual'} onChange={(value) => onModeChange(value === 'auto')}
        options={[{ label: '逐步确认', value: 'manual' }, { label: '自动推进', value: 'auto' }]} />
    </Form.Item>
  </>
}

const FALLBACK_TARGET_WORDS = 50_400
const INITIAL_CREATION_VALUES: Partial<CreationForm> = {
  planning_preset: 'short', total_chapters: DEFAULT_TOTAL_CHAPTERS, target_total_words: FALLBACK_TARGET_WORDS,
}

function targetWordsRule(form: FormInstance<CreationForm>, options?: PlanningOptions) {
  return async (_: unknown, value?: number) => {
    if (value == null) throw new Error('请输入目标总字数')
    const chapters = form.getFieldValue('total_chapters') || DEFAULT_TOTAL_CHAPTERS
    const minimum = chapters * (options?.constraints.min_chapter_words ?? 3000)
    const maximum = chapters * (options?.constraints.max_chapter_words ?? 7000)
    if (value < minimum || value > maximum) {
      throw new Error(`目标总字数应为 ${minimum.toLocaleString()} 至 ${maximum.toLocaleString()}`)
    }
  }
}

interface PlanningFieldsProps {
  form: FormInstance<CreationForm>
  options?: PlanningOptions
  loading: boolean
  error: boolean
}

function PlanningFields({ form, options, loading, error }: PlanningFieldsProps) {
  const chapters = Form.useWatch('total_chapters', form) ?? DEFAULT_TOTAL_CHAPTERS
  const words = Form.useWatch('target_total_words', form) ?? FALLBACK_TARGET_WORDS
  const presets = options?.presets || []
  const selectPreset = (value: string | number) => {
    const preset = presets.find((item) => item.preset === value)
    form.setFieldsValue(preset ? {
      planning_preset: preset.preset,
      total_chapters: preset.target_chapters,
      target_total_words: preset.target_total_words,
    } : { planning_preset: 'custom' })
  }
  const average = Math.round(words / Math.max(chapters, 1))
  const volumes = Math.min(8, Math.max(1, Math.ceil(chapters / 25)))
  return <section className="planning-fields" aria-labelledby="planning-fields-title">
    <div className="planning-fields-heading">
      <div><span className="eyebrow">Book Scale</span><h2 id="planning-fields-title">整书规模</h2></div>
      <div className="planning-scale-summary"><strong>{volumes}</strong><span>卷</span><strong>{average.toLocaleString()}</strong><span>字 / 章</span></div>
    </div>
    {error && <Alert type="error" showIcon message="规模选项无法读取，请确认后端服务已启动" />}
    <Form.Item name="planning_preset" label="规模预设" rules={[{ required: true }]}>
      <Segmented block disabled={loading || error} onChange={selectPreset} options={[
        ...presets.map((item) => ({ label: item.label, value: item.preset })),
        { label: '自定义', value: 'custom' },
      ]} />
    </Form.Item>
    <div className="planning-number-fields">
      <Form.Item label="计划章节" name="total_chapters" rules={[
        { required: true, message: '请输入计划章节数' },
        { type: 'number', min: options?.constraints.min_chapters ?? 1,
          max: options?.constraints.max_chapters ?? 200, message: '计划章节数应为 1 至 200' },
      ]}><InputNumber min={options?.constraints.min_chapters ?? 1} max={options?.constraints.max_chapters ?? 200} size="large" /></Form.Item>
      <Form.Item label="目标总字数" name="target_total_words" dependencies={['total_chapters']}
        rules={[{ validator: targetWordsRule(form, options) }]}>
        <InputNumber min={3000} max={1_400_000} step={1000} size="large" formatter={(value) => Number(value || 0).toLocaleString()} />
      </Form.Item>
    </div>
  </section>
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
    <Form.Item label="写作风格" name="writing_style"><Input size="large" maxLength={80} placeholder="例如：冷峻克制、快节奏" /></Form.Item>
  </div>
}

interface QuotaNoticeProps { quota?: QuotaUsage; loading: boolean; chapters?: number }

function QuotaNotice({ quota, loading, chapters }: QuotaNoticeProps) {
  if (loading) return <div className="creation-quota" role="status" aria-live="polite" aria-label="正在读取创作额度"><Skeleton.Input active size="small" /></div>
  const details = quotaNoticeDetails(quota, chapters)
  return <div className="creation-quota" data-state={details.state}>
    <span>{quota?.unlimited && <strong>∞</strong>}{details.headline}</span>
    <small>{details.detail}</small>
  </div>
}

function CreationPreview({ title, genreLabel, chapters, words }: { title?: string; genreLabel?: string; chapters: number; words: number }) {
  return <aside className="creation-preview" aria-label="书稿预览">
    <div className="preview-folio">NO. {new Date().getFullYear()}</div><BookOutlined />
    <span>{genreLabel || '小说'}</span>
    <h2>{title || '未命名作品'}</h2><div className="preview-rule" />
    <p>{chapters} 章 · {(words / 10_000).toFixed(1)} 万字</p><small>墨间编辑部 · 私人创作稿</small>
  </aside>
}

function useCreationGenreFields(form: FormInstance<CreationForm>) {
  const { profiles, loading, error } = useGenreTaxonomy()
  const genre = Form.useWatch('novel_type', form)
  const selectedProfile = useMemo(
    () => selectedGenreProfile(profiles, genre),
    [profiles, genre],
  )
  const genreLabel = selectedProfile && selectedProfile.value === genre ? selectedProfile.label : undefined
  useEffect(() => {
    if (!profiles.length) return
    const profile = selectedGenreProfile(profiles, form.getFieldValue('novel_type'))
    if (profile) form.setFieldsValue(genreDefaults(profile))
  }, [form, profiles])
  const onGenreChange = useCallback((value: string) => {
    form.setFieldsValue(genreDefaults(selectedGenreProfile(profiles, value)))
  }, [form, profiles])
  return { profiles, loading, error, selectedProfile, genreLabel, onGenreChange }
}

export default function CreateNovel() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [form] = Form.useForm<CreationForm>()
  const [submitting, setSubmitting] = useState(false)
  const genreState = useCreationGenreFields(form)
  const autoMode = useNovelStore((state) => state.autoMode)
  const setAutoMode = useNovelStore((state) => state.setAutoMode)
  const title = Form.useWatch('title', form)
  const chapters = Form.useWatch('total_chapters', form)
  const targetWords = Form.useWatch('target_total_words', form)
  const planning = usePlanningOptions()
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
        <p className="section-lead">先给出故事方向；空白内容由 AI 提案，逐步确认模式会在关键节点等待你的决定。</p>
        <Form form={form} layout="vertical" initialValues={INITIAL_CREATION_VALUES} onValuesChange={(changed) => {
          if ('total_chapters' in changed || 'target_total_words' in changed) form.setFieldValue('planning_preset', 'custom')
        }} onFinish={(values) => void submit(values)} requiredMark={false}>
          <CoreFields autoMode={autoMode} genreError={genreState.error} genreLoading={genreState.loading}
            genreProfiles={genreState.profiles} selectedProfile={genreState.selectedProfile}
            onGenreChange={genreState.onGenreChange} onModeChange={setAutoMode} />
          <PlanningFields form={form} options={planning.options} loading={planning.loading} error={planning.error} />
          <Collapse ghost className="advanced-settings" items={[{ key: 'advanced', label: <span><SettingOutlined /> 更多创作约束</span>, children: <AdvancedFields /> }]} />
          <div className="creation-submit-bar">
            <QuotaNotice quota={quota} loading={quotaLoading} chapters={chapters ?? DEFAULT_TOTAL_CHAPTERS} />
            <Button type="primary" size="large" htmlType="submit"
              disabled={quotaBlocked || genreState.loading || genreState.error || planning.loading || planning.error}
              loading={submitting} icon={<ArrowRightOutlined />} iconPlacement="end">创建并进入工作台</Button>
          </div>
        </Form>
      </section><CreationPreview title={title} genreLabel={genreState.genreLabel}
        chapters={chapters ?? DEFAULT_TOTAL_CHAPTERS} words={targetWords ?? FALLBACK_TARGET_WORDS} /></div>
    </div>
  </AppShell>
}
