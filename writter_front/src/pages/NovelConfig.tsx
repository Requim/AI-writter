import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Card, Steps, Radio, Input, Button, Form, message, Alert, Space, Spin, Progress, Tag, InputNumber, Collapse, Divider, Typography } from 'antd'
import { EditOutlined } from '@ant-design/icons'
import { novelApi, workflowApi } from '@/api/novel'
import type { NovelCreateRequest, NovelResponse } from '@/api/novel'
import type { InterruptInfo } from '@/api/novel'

const NovelConfig = () => {
  const navigate = useNavigate()
  const { novelId: urlNovelId } = useParams<{ novelId: string }>()
  const isResumeMode = urlNovelId && urlNovelId !== 'new'
  const [currentStep, setCurrentStep] = useState(0)
  const [resumeLoading, setResumeLoading] = useState(isResumeMode)
  const [novelId, setNovelId] = useState<string | null>(null)
  const [threadId, setThreadId] = useState<string | null>(null)
  const [novelType, setNovelType] = useState('')
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [outline, setOutline] = useState<any>(null)
  const [interrupt, setInterrupt] = useState<InterruptInfo | null>(null)
  const [loading, setLoading] = useState(false)
  const [chapterNum, setChapterNum] = useState(0)   // 当前章节编号
  const [editableOutline, setEditableOutline] = useState<any>(null)  // 可编辑的大纲数据
  const [editableChapter, setEditableChapter] = useState<any>(null)   // 可编辑的章节细纲

  // 大纲中断到达时，初始化可编辑数据（保持章节数与总章节数一致）
  useEffect(() => {
    if (interrupt?.action === 'review_or_modify_outline' && interrupt.ai_generated_outline) {
      const outline = JSON.parse(JSON.stringify(interrupt.ai_generated_outline))
      const total = outline.total_chapters || 0
      const chs = outline.chapters || []
      if (chs.length < total) {
        const extra = Array.from({ length: total - chs.length }, () => ({ theme: '', key_events: [] }))
        outline.chapters = [...chs, ...extra]
      } else if (chs.length > total) {
        outline.chapters = chs.slice(0, total)
      }
      setEditableOutline(outline)
    }
    // 简介确认：自动填入AI生成的内容
    if (interrupt?.action === 'confirm_or_provide_summary' && interrupt.ai_generated_summary && !summary) {
      setSummary(interrupt.ai_generated_summary)
    }
    // 章节细纲：初始化可编辑数据
    if (interrupt?.action === 'review_or_provide_chapter_outline' && interrupt.ai_generated_outline) {
      setEditableChapter(JSON.parse(JSON.stringify(interrupt.ai_generated_outline)))
    }
  }, [interrupt])

  // ====== 恢复模式：从书架进入，加载已有小说状态 ======
  useEffect(() => {
    if (!isResumeMode) return

    let cancelled = false
    const resumeNovel = async () => {
      try {
        const novelData: NovelResponse = await novelApi.getNovel(urlNovelId!)
        if (cancelled) return
        setNovelId(novelData.id)
        setNovelType(novelData.novel_type)
        if (novelData.title) setTitle(novelData.title)
        if (novelData.summary) setSummary(novelData.summary)

        const threadId = novelData.thread_id || novelData.id
        setThreadId(threadId)

        // 获取工作流状态，加超时兜底
        try {
          const stateData: any = await Promise.race([
            workflowApi.getWorkflowState(threadId),
            new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 8000)),
          ])
          if (cancelled) return
          if (stateData.has_interrupt && stateData.interrupts?.length > 0) {
            const interruptValue = stateData.interrupts[0].value
            setInterrupt(interruptValue)
            setCurrentStep(getStepFromAction(interruptValue.action))
            if (interruptValue.chapter_number) {
              setChapterNum(interruptValue.chapter_number)
            }
            message.info('已恢复上次创作进度')
          } else {
            navigate(`/progress/${novelData.id}`, { replace: true })
          }
        } catch (stateErr: any) {
          if (cancelled) return
          console.warn('工作流状态查询超时或失败，从步骤 0 开始', stateErr?.message)
          setCurrentStep(0)
        }
      } catch (err: any) {
        if (cancelled) return
        const status = err?.response?.status || err?.status
        if (status === 404) {
          message.warning('该小说不存在或已被删除')
        } else {
          message.error('加载小说失败：' + (err?.message || '未知错误'))
        }
        navigate('/', { replace: true })
      } finally {
        if (!cancelled) setResumeLoading(false)
      }
    }

    resumeNovel()
    return () => { cancelled = true }
  }, [urlNovelId])

  // 小说类型选项
  const novelTypes = [
    { label: '悬疑', value: 'suspense' },
    { label: '科幻', value: 'sci_fi' },
    { label: '言情', value: 'romance' },
    { label: '奇幻', value: 'fantasy' },
    { label: '武侠', value: 'wuxia' },
    { label: '仙侠', value: 'xianxia' },
    { label: '都市', value: 'urban' },
    { label: '历史', value: 'history' },
    { label: '恐怖', value: 'horror' },
    { label: '喜剧', value: 'comedy' },
  ]

  // 根据 interrupt action 确定步骤
  const getStepFromAction = (action: string) => {
    switch (action) {
      case 'require_novel_type': return 0
      case 'confirm_or_provide_title': return 1
      case 'confirm_or_provide_summary': return 2
      case 'review_or_modify_outline': return 3
      case 'review_or_provide_chapter_outline': return 4
      case 'ready_for_next_chapter': return 4
      case 'review_reflection_issues': return 5
      case 'confirm_revision': return 6
      default: return 1
    }
  }

  // 调用工作流（内部函数）
  const invokeWorkflow = async (resumeValue?: any, tid?: string | null, nid?: string | null) => {
    const effectiveThreadId = tid || threadId
    const effectiveNovelId = nid || novelId
    if (!effectiveThreadId) return

    const loadingKey = resumeValue ? 'workflow_resume' : 'workflow_init'
    message.loading({ content: '正在处理，请稍候...', key: loadingKey, duration: 0 })
    try {
      const data: any = resumeValue
        ? { command: { resume: resumeValue } }
        : { input: { novel_id: effectiveNovelId, novel_type: novelType } }

      console.log('[invokeWorkflow] request:', { threadId: effectiveThreadId, data: JSON.stringify(data) })
      const res = await workflowApi.invokeWorkflow(effectiveThreadId, data)
      console.log('[invokeWorkflow] response:', res)
      message.destroy(loadingKey)

      // 检查是否有 interrupt
      if (res.__interrupt__ && res.__interrupt__.length > 0) {
        const interruptValue = res.__interrupt__[0].value
        const interruptAction = interruptValue?.action || ''
        console.log('[invokeWorkflow] interrupt received:', { action: interruptAction, step: getStepFromAction(interruptAction) })
        const newStep = getStepFromAction(interruptAction)

        // 防御：如果 action 未被识别，尝试从 __interrupt__ 的其他字段推断
        if (newStep === 1 && interruptAction && !['require_novel_type', 'confirm_or_provide_title'].includes(interruptAction)) {
          console.warn('[invokeWorkflow] unknown interrupt action:', interruptAction, ' falling back to raw step')
        }

        // 追踪章节编号：检测章节完成（非首章）
        const newChapterNum = interruptValue?.chapter_number || 0
        if (newChapterNum > 0 && chapterNum > 0 && newChapterNum > chapterNum && newStep === 4) {
          // 前一章已完成，显示成功提示
          message.success(`第 ${chapterNum} 章已完成！正在准备第 ${newChapterNum} 章...`)
        }
        setChapterNum(newChapterNum)

        setInterrupt(interruptValue)
        setCurrentStep(newStep)
        console.log('[invokeWorkflow] state updated: step=', newStep, ' action=', interruptAction)
        message.info('请确认信息')
      } else {
        setInterrupt(null)
        message.success('章节生成中...')
        navigate(`/progress/${effectiveNovelId}`)
      }
    } catch (error: any) {
      message.destroy(loadingKey)
      console.error('[invokeWorkflow] error:', error.response?.data || error)
      const errorMsg = error.response?.data?.detail || error.message || '工作流调用失败'
      message.error(`处理失败: ${errorMsg}`)
    }
  }

   // 开始创作
  const startCreation = async () => {
    if (!novelType) {
      message.warning('请选择小说类型')
      return
    }

    setLoading(true)
    message.loading({ content: '正在创建小说...', key: 'creating', duration: 0 })
    try {
      // 使用条件展开避免 undefined 值被 JSON.stringify 剔除
      const data: NovelCreateRequest = {
        novel_type: novelType,
        ...(title ? { title } : {}),
        ...(summary ? { summary } : {}),
      }
      console.log('[startCreation] request:', JSON.stringify(data))
      const res = await novelApi.createNovel(data)
      console.log('[startCreation] response:', res)

      setNovelId(res.novel_id)
      setThreadId(res.thread_id)
      setCurrentStep(1)
      message.destroy('creating')

      // 启动工作流（invokeWorkflow 自己管理 loading）
      await invokeWorkflow(undefined, res.thread_id, res.novel_id)
    } catch (error: any) {
      console.error('[startCreation] error:', error.response?.data || error)
      message.destroy('creating')
      // 显示详细错误信息
      const errData = error.response?.data
      let errMsg = '创建小说失败'
      if (errData) {
        if (typeof errData === 'string') {
          errMsg = errData
        } else if (errData.detail) {
          if (Array.isArray(errData.detail)) {
            errMsg = errData.detail.map((d: any) => `${d.loc?.join('.')}: ${d.msg}`).join('; ')
          } else {
            errMsg = errData.detail
          }
        }
      }
      message.error(errMsg)
    } finally {
      setLoading(false)
      message.destroy('creating')
    }
  }

  // 处理 interrupt 恢复
  const handleInterruptResume = () => {
    if (!interrupt) return
    switch (interrupt.action) {
      case 'require_novel_type':
        invokeWorkflow(novelType)
        break
      case 'confirm_or_provide_title':
        invokeWorkflow(title || (interrupt.ai_suggestions?.[0] || '未命名小说'))
        break
      case 'confirm_or_provide_summary':
        invokeWorkflow(summary || 'accept')
        break
      case 'review_or_modify_outline':
        invokeWorkflow(editableOutline || 'accept')
        break
      case 'review_or_provide_chapter_outline':
        invokeWorkflow(editableChapter || 'accept')
        break
      case 'ready_for_next_chapter':
        invokeWorkflow('next')
        break
      case 'review_reflection_issues':
        invokeWorkflow('accept')
        break
      case 'confirm_revision':
        invokeWorkflow('accept')
        break
    }
  }

  // 返回上一步（章节阶段禁用）
  const goBack = () => {
    if (currentStep > 0 && currentStep < 4) {
      setCurrentStep(currentStep - 1)
    }
  }

  const isChapterPhase = currentStep >= 4

  // 准备阶段步骤
  const setupSteps = [
    { title: currentStep === 0 ? '选择类型' : '' },
    { title: currentStep === 1 ? '书名确认' : '' },
    { title: currentStep === 2 ? '简介确认' : '' },
    { title: currentStep === 3 ? '大纲确认' : '' },
  ]

  // 章节阶段步骤
  const chapterLocalStep = currentStep - 4  // 0, 1, 2
  const chapterSteps = [
    { title: chapterNum > 0 ? `第${chapterNum}章细纲` : '章节细纲' },
    { title: chapterNum > 0 ? `第${chapterNum}章质检` : '质量检查' },
    { title: chapterNum > 0 ? `第${chapterNum}章修正` : '修正确认' },
  ]

  return (
    <div style={{ maxWidth: 960, margin: '40px auto', padding: '0 20px' }}>
      {resumeLoading ? (
        <div style={{ textAlign: 'center', padding: 100 }}>
          <Spin size="large" tip="正在加载小说数据..." />
        </div>
      ) : (
      <Card title={
        isChapterPhase
          ? (chapterNum > 0 ? `第${chapterNum}章创作` : '章节创作')
          : (isResumeMode && title ? `《${title}》创作配置` : 'AI 小说创作配置')
      }
        extra={<Button onClick={() => navigate('/')}>返回书架</Button>}
      >
        <Steps
          current={isChapterPhase ? chapterLocalStep : currentStep}
          style={{ marginBottom: 40 }}
          items={isChapterPhase ? chapterSteps : setupSteps}
        />

        {/* Step 0: 选择小说类型（无中断时显示） */}
        {!interrupt && currentStep === 0 && (
          <div>
            <h3>{isResumeMode ? '确认小说类型' : '选择小说类型（必选）'}</h3>
            {isResumeMode ? (
              <div style={{ marginBottom: 16, padding: 12, background: '#f5f5f5', borderRadius: 8 }}>
                <p style={{ margin: 0, fontWeight: 500 }}>
                  类型：{novelTypes.find(t => t.value === novelType)?.label || novelType}
                </p>
              </div>
            ) : (
              <Radio.Group value={novelType} onChange={(e) => setNovelType(e.target.value)}>
                <Space wrap>
                  {novelTypes.map((t) => (
                    <Radio key={t.value} value={t.value}>{t.label}</Radio>
                  ))}
                </Space>
              </Radio.Group>
            )}
            <div style={{ marginTop: 24 }}>
              <Button
                type="primary"
                onClick={() => {
                  if (isResumeMode && novelId && threadId) {
                    invokeWorkflow(undefined, threadId, novelId)
                  } else {
                    startCreation()
                  }
                }}
                loading={loading}
              >
                {isResumeMode ? '继续创作' : '开始创作'}
              </Button>
            </div>
          </div>
        )}

        {/* Step 1-3: Interrupt 处理 */}
        {interrupt && (
          <div>
            <Alert
              message={interrupt.message}
              type="info"
              showIcon
              style={{ marginBottom: 20 }}
            />

            {/* 类型确认 */}
            {interrupt.action === 'require_novel_type' && (
              <div>
                <p>请确认小说类型：</p>
                <Radio.Group value={novelType} onChange={(e) => setNovelType(e.target.value)}>
                  <Space wrap>
                    {novelTypes.map((t) => (
                      <Radio key={t.value} value={t.value}>{t.label}</Radio>
                    ))}
                  </Space>
                </Radio.Group>
              </div>
            )}

            {/* 书名确认 */}
            {interrupt.action === 'confirm_or_provide_title' && (
              <div>
                <p>{interrupt.message}</p>
                {interrupt.ai_suggestions && interrupt.ai_suggestions.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <p style={{ fontWeight: 500, marginBottom: 8 }}>AI推荐书名：</p>
                    <Space wrap>
                      {interrupt.ai_suggestions.map((s: string, i: number) => (
                        <Button
                          key={i}
                          onClick={() => setTitle(s)}
                          type={title === s ? 'primary' : 'default'}
                        >
                          {s}
                        </Button>
                      ))}
                    </Space>
                  </div>
                )}
                <Form layout="vertical">
                  <Form.Item label="书名">
                    <Input.TextArea
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      placeholder="自定义书名或接受AI建议"
                      rows={2}
                    />
                  </Form.Item>
                </Form>
              </div>
            )}

            {/* 简介确认 */}
            {interrupt.action === 'confirm_or_provide_summary' && (
              <div>
                <p>{interrupt.message}</p>
                {interrupt.ai_generated_summary && (
                  <div style={{ marginBottom: 16, padding: 12, background: '#f5f5f5', borderRadius: 8 }}>
                    <p style={{ fontWeight: 500, marginBottom: 4 }}>AI生成简介：</p>
                    <p>{interrupt.ai_generated_summary}</p>
                  </div>
                )}
                <Form layout="vertical">
                  <Form.Item label="简介">
                    <Input.TextArea
                      value={summary}
                      onChange={(e) => setSummary(e.target.value)}
                      placeholder="自定义简介或接受AI建议"
                      rows={4}
                    />
                  </Form.Item>
                </Form>
              </div>
            )}

            {/* 大纲确认 */}
            {interrupt.action === 'review_or_modify_outline' && editableOutline && (
              <div>
                <p style={{ color: '#888', marginBottom: 16 }}>{interrupt.note}</p>

                {/* 故事背景 */}
                <Form layout="vertical">
                  <Form.Item label="故事背景">
                    <Input.TextArea
                      value={editableOutline.story_background || ''}
                      onChange={(e) => setEditableOutline({ ...editableOutline, story_background: e.target.value })}
                      rows={3}
                    />
                  </Form.Item>

                  {/* 主角列表 */}
                  <Divider orientation="left" plain>主角列表</Divider>
                  {(editableOutline.main_characters || []).map((char: any, i: number) => (
                    <div key={i} style={{ marginBottom: 12, padding: 12, background: '#fafafa', borderRadius: 8, border: '1px solid #f0f0f0' }}>
                      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                        <div style={{ flex: '1 1 120px' }}>
                          <Form.Item label="名字" style={{ marginBottom: 0 }}>
                            <Input
                              value={char.name || ''}
                              onChange={(e) => {
                                const chars = [...editableOutline.main_characters]
                                chars[i] = { ...chars[i], name: e.target.value }
                                setEditableOutline({ ...editableOutline, main_characters: chars })
                              }}
                              placeholder="角色名"
                            />
                          </Form.Item>
                        </div>
                        <div style={{ flex: '1 1 120px' }}>
                          <Form.Item label="性格" style={{ marginBottom: 0 }}>
                            <Input
                              value={char.personality || ''}
                              onChange={(e) => {
                                const chars = [...editableOutline.main_characters]
                                chars[i] = { ...chars[i], personality: e.target.value }
                                setEditableOutline({ ...editableOutline, main_characters: chars })
                              }}
                              placeholder="性格特征"
                            />
                          </Form.Item>
                        </div>
                        <div style={{ flex: '1 1 120px' }}>
                          <Form.Item label="目标" style={{ marginBottom: 0 }}>
                            <Input
                              value={char.goal || ''}
                              onChange={(e) => {
                                const chars = [...editableOutline.main_characters]
                                chars[i] = { ...chars[i], goal: e.target.value }
                                setEditableOutline({ ...editableOutline, main_characters: chars })
                              }}
                              placeholder="角色目标"
                            />
                          </Form.Item>
                        </div>
                        <div style={{ flex: '2 1 200px' }}>
                          <Form.Item label="冲突" style={{ marginBottom: 0 }}>
                            <Input
                              value={char.conflict || ''}
                              onChange={(e) => {
                                const chars = [...editableOutline.main_characters]
                                chars[i] = { ...chars[i], conflict: e.target.value }
                                setEditableOutline({ ...editableOutline, main_characters: chars })
                              }}
                              placeholder="核心冲突"
                            />
                          </Form.Item>
                        </div>
                      </div>
                    </div>
                  ))}

                  {/* 主线剧情 */}
                  <Divider orientation="left" plain>主线剧情</Divider>
                  {editableOutline.main_plot && (
                    <>
                      <Form.Item label="开端">
                        <Input.TextArea
                          value={editableOutline.main_plot.beginning || ''}
                          onChange={(e) => setEditableOutline({
                            ...editableOutline,
                            main_plot: { ...editableOutline.main_plot, beginning: e.target.value }
                          })}
                          rows={2}
                        />
                      </Form.Item>
                      <Form.Item label="发展">
                        <Input.TextArea
                          value={editableOutline.main_plot.development || ''}
                          onChange={(e) => setEditableOutline({
                            ...editableOutline,
                            main_plot: { ...editableOutline.main_plot, development: e.target.value }
                          })}
                          rows={2}
                        />
                      </Form.Item>
                      <Form.Item label="高潮">
                        <Input.TextArea
                          value={editableOutline.main_plot.climax || ''}
                          onChange={(e) => setEditableOutline({
                            ...editableOutline,
                            main_plot: { ...editableOutline.main_plot, climax: e.target.value }
                          })}
                          rows={2}
                        />
                      </Form.Item>
                      <Form.Item label="结局">
                        <Input.TextArea
                          value={editableOutline.main_plot.ending || ''}
                          onChange={(e) => setEditableOutline({
                            ...editableOutline,
                            main_plot: { ...editableOutline.main_plot, ending: e.target.value }
                          })}
                          rows={2}
                        />
                      </Form.Item>
                    </>
                  )}

                  {/* 写作风格 */}
                  <Divider orientation="left" plain>写作风格</Divider>
                  <Form.Item>
                    <Input.TextArea
                      value={editableOutline.writing_style || ''}
                      onChange={(e) => setEditableOutline({ ...editableOutline, writing_style: e.target.value })}
                      rows={2}
                    />
                  </Form.Item>

                  {/* 总章节数 */}
                  <Form.Item label="总章节数">
                    <InputNumber
                      value={editableOutline.total_chapters || 0}
                      onChange={(val) => {
                        const newTotal = val || 0
                        const oldChapters = editableOutline.chapters || []
                        let newChapters: any[]
                        if (newTotal > oldChapters.length) {
                          // 增加章节：新章节目录默认为空
                          const extra = Array.from({ length: newTotal - oldChapters.length }, (_, i) => ({
                            theme: '',
                            key_events: [] as string[],
                          }))
                          newChapters = [...oldChapters, ...extra]
                        } else if (newTotal < oldChapters.length) {
                          // 减少章节：截断
                          newChapters = oldChapters.slice(0, newTotal)
                        } else {
                          newChapters = oldChapters
                        }
                        setEditableOutline({ ...editableOutline, total_chapters: newTotal, chapters: newChapters })
                      }}
                      min={1} max={200}
                      style={{ width: 120 }}
                    />
                  </Form.Item>

                  {/* 章节规划 */}
                  {(editableOutline.chapters || []).length > 0 && (
                    <Collapse
                      ghost
                      items={[{
                        key: 'chapters',
                        label: `章节规划（${editableOutline.chapters.length}章）`,
                        children: (
                          <div style={{ maxHeight: 300, overflow: 'auto' }}>
                            {editableOutline.chapters.map((ch: any, i: number) => (
                              <div key={i} style={{ marginBottom: 8, padding: '6px 10px', background: '#fafafa', borderRadius: 4 }}>
                                <Space>
                                  <Typography.Text strong>第{i + 1}章</Typography.Text>
                                  <Input
                                    value={ch.theme || ''}
                                    onChange={(e) => {
                                      const chs = [...editableOutline.chapters]
                                      chs[i] = { ...chs[i], theme: e.target.value }
                                      setEditableOutline({ ...editableOutline, chapters: chs })
                                    }}
                                    size="small"
                                    style={{ width: 200 }}
                                    placeholder="章节主题"
                                  />
                                </Space>
                              </div>
                            ))}
                          </div>
                        )
                      }]}
                    />
                  )}
                </Form>
              </div>
            )}

            {/* 章节细纲确认 */}
            {interrupt.action === 'review_or_provide_chapter_outline' && editableChapter && (
              <div>
                <p style={{ color: '#888', marginBottom: 16 }}>{interrupt.note}</p>

                <Form layout="vertical">
                  <Form.Item label="章节标题">
                    <Input
                      value={editableChapter.title || ''}
                      onChange={(e) => setEditableChapter({ ...editableChapter, title: e.target.value })}
                      placeholder="富有感染力的章节标题"
                    />
                  </Form.Item>

                  <Form.Item label="字数分配建议">
                    <Input
                      value={editableChapter.word_count_distribution || ''}
                      onChange={(e) => setEditableChapter({ ...editableChapter, word_count_distribution: e.target.value })}
                      placeholder="建议配比：场景1(1500字), 场景2(2000字)..."
                    />
                  </Form.Item>

                  <Form.Item label="预估字数">
                    <InputNumber
                      value={editableChapter.estimated_word_count || 3500}
                      onChange={(val) => setEditableChapter({ ...editableChapter, estimated_word_count: val || 3500 })}
                      min={3000} max={6000}
                      style={{ width: 150 }}
                    />
                  </Form.Item>

                  {/* 场景安排 */}
                  <Divider orientation="left" plain>场景安排</Divider>
                  {(editableChapter.scenes || []).map((s: any, i: number) => (
                    <div key={i} style={{ marginBottom: 12, padding: 12, background: '#fafafa', borderRadius: 8, border: '1px solid #f0f0f0' }}>
                      <Form.Item label={`场景${i + 1} · 地点`} style={{ marginBottom: 8 }}>
                        <Input
                          value={s.location || ''}
                          onChange={(e) => {
                            const sc = [...editableChapter.scenes]
                            sc[i] = { ...sc[i], location: e.target.value }
                            setEditableChapter({ ...editableChapter, scenes: sc })
                          }}
                          placeholder="场景地点"
                        />
                      </Form.Item>
                      <Form.Item label="人物及情感状态" style={{ marginBottom: 8 }}>
                        <Input
                          value={(s.characters || []).join('、')}
                          onChange={(e) => {
                            const sc = [...editableChapter.scenes]
                            sc[i] = { ...sc[i], characters: e.target.value.split(/[、,，]/).filter(Boolean) }
                            setEditableChapter({ ...editableChapter, scenes: sc })
                          }}
                          placeholder="用顿号分隔：张三(愤怒)、李四(忐忑)"
                        />
                      </Form.Item>
                      <Form.Item label="情节链" style={{ marginBottom: 8 }}>
                        <Input.TextArea
                          value={(s.events || []).join('\n')}
                          onChange={(e) => {
                            const sc = [...editableChapter.scenes]
                            sc[i] = { ...sc[i], events: e.target.value.split('\n').filter(Boolean) }
                            setEditableChapter({ ...editableChapter, scenes: sc })
                          }}
                          placeholder="每行一个事件：情节A -> 转折B -> 结果C"
                          rows={2}
                        />
                      </Form.Item>
                      <Form.Item label="感官细节素材" style={{ marginBottom: 8 }}>
                        <Input.TextArea
                          value={(s.sensory_details || []).join('\n')}
                          onChange={(e) => {
                            const sc = [...editableChapter.scenes]
                            sc[i] = { ...sc[i], sensory_details: e.target.value.split('\n').filter(Boolean) }
                            setEditableChapter({ ...editableChapter, scenes: sc })
                          }}
                          placeholder="每行一个细节：特定气味、小动作、光影变化..."
                          rows={2}
                        />
                      </Form.Item>
                      <Form.Item label="对话目标/金句" style={{ marginBottom: 8 }}>
                        <Input.TextArea
                          value={(s.dialogue_targets || []).join('\n')}
                          onChange={(e) => {
                            const sc = [...editableChapter.scenes]
                            sc[i] = { ...sc[i], dialogue_targets: e.target.value.split('\n').filter(Boolean) }
                            setEditableChapter({ ...editableChapter, scenes: sc })
                          }}
                          placeholder="每行一个：对话目的 / 关键金句 / 潜台词"
                          rows={2}
                        />
                      </Form.Item>
                      <Form.Item label="场景必要性" style={{ marginBottom: 0 }}>
                        <Input
                          value={s.purpose || ''}
                          onChange={(e) => {
                            const sc = [...editableChapter.scenes]
                            sc[i] = { ...sc[i], purpose: e.target.value }
                            setEditableChapter({ ...editableChapter, scenes: sc })
                          }}
                          placeholder="该场景在全书逻辑中的必要性"
                        />
                      </Form.Item>
                    </div>
                  ))}

                  {/* 主角心理演变 */}
                  <Divider orientation="left" plain>主角心理轨迹</Divider>
                  <Form.Item>
                    <Input.TextArea
                      value={editableChapter.internal_monologue || ''}
                      onChange={(e) => setEditableChapter({ ...editableChapter, internal_monologue: e.target.value })}
                      placeholder="主角在本章的核心心理演变轨迹"
                      rows={3}
                    />
                  </Form.Item>

                  {/* 逻辑钩子 */}
                  <Divider orientation="left" plain>伏笔与悬念</Divider>
                  <Form.Item label="回收的前文伏笔（Callback）">
                    <Input.TextArea
                      value={editableChapter.logic_hooks?.callback || ''}
                      onChange={(e) => setEditableChapter({
                        ...editableChapter,
                        logic_hooks: { ...editableChapter.logic_hooks, callback: e.target.value }
                      })}
                      placeholder="本章回收了哪些前文埋下的线索"
                      rows={2}
                    />
                  </Form.Item>
                  <Form.Item label="埋下的新矛盾（Setup）">
                    <Input.TextArea
                      value={editableChapter.logic_hooks?.setup || ''}
                      onChange={(e) => setEditableChapter({
                        ...editableChapter,
                        logic_hooks: { ...editableChapter.logic_hooks, setup: e.target.value }
                      })}
                      placeholder="为后续章节制造的新悬念或矛盾"
                      rows={2}
                    />
                  </Form.Item>
                </Form>
              </div>
            )}

            {/* 章节完成 — 等待用户触发下一章 */}
            {interrupt.action === 'ready_for_next_chapter' && (
              <div style={{ textAlign: 'center', padding: '24px 0' }}>
                <div style={{
                  width: 80, height: 80, margin: '0 auto 16px',
                  background: 'linear-gradient(135deg, #52c41a, #73d13d)',
                  borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 36, color: '#fff',
                }}>
                  ✓
                </div>
                <h2 style={{ margin: '0 0 8px', color: '#52c41a' }}>
                  第 {interrupt.current_chapter} 章已完成！
                </h2>
                <p style={{ color: '#666', marginBottom: 8 }}>
                  进度：{interrupt.current_chapter} / {interrupt.total_chapters} 章
                  （{interrupt.progress_percentage}%）
                </p>
                <Progress
                  percent={Math.round(interrupt.progress_percentage || 0)}
                  status="active"
                  style={{ maxWidth: 400, margin: '0 auto' }}
                />
              </div>
            )}

            {/* 反思问题 */}
            {interrupt.action === 'review_reflection_issues' && (
              <div>
                <Alert message={`第 ${interrupt.chapter_number || '?'} 章质量检查未通过（评分：${interrupt.quality_score ?? '?'}）`} type="warning" style={{ marginBottom: 16 }} />
                {interrupt.issues && interrupt.issues.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    {interrupt.issues.map((issue: any, idx: number) => (
                      <div key={idx} style={{ marginBottom: 8, padding: '8px 12px', background: '#fff7e6', borderRadius: 6, border: '1px solid #ffd591' }}>
                        <Space>
                          <Tag color={issue.severity === 'high' ? 'red' : issue.severity === 'medium' ? 'orange' : 'blue'}>
                            {issue.type || '问题'}
                          </Tag>
                          <span style={{ fontWeight: 500 }}>{issue.description || String(issue)}</span>
                        </Space>
                        {issue.suggestion && (
                          <p style={{ margin: '4px 0 0', fontSize: 13, color: '#666' }}>
                            建议：{issue.suggestion}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                <p>请选择处理方式：</p>
                <Space>
                  <Button onClick={() => invokeWorkflow('accept')}>接受（忽略问题）</Button>
                  <Button type="primary" onClick={() => invokeWorkflow('ai_fix')}>AI自动修正</Button>
                  <Button onClick={() => invokeWorkflow('user_fix')}>按指令修正</Button>
                  <Button danger onClick={() => invokeWorkflow('regenerate')}>重新生成</Button>
                </Space>
              </div>
            )}

            {/* 修正确认 */}
            {interrupt.action === 'confirm_revision' && (
              <div>
                <p><strong>第 {interrupt.chapter_number || '?'} 章：</strong>{interrupt.message}</p>
                {interrupt.revised_content_preview && (
                  <div style={{ marginBottom: 16, padding: 12, background: '#f0f5ff', borderRadius: 8 }}>
                    <p style={{ fontWeight: 500, marginBottom: 8 }}>修正后的内容预览：</p>
                    <pre style={{ background: '#fff', padding: 12, borderRadius: 4, maxHeight: 300, overflow: 'auto', whiteSpace: 'pre-wrap', fontSize: 13 }}>
                      {interrupt.revised_content_preview}
                    </pre>
                  </div>
                )}
                <p style={{ color: '#888', fontSize: 13 }}>{interrupt.note}</p>
              </div>
            )}

            <div style={{ marginTop: 24, textAlign: 'center' }}>
              {currentStep > 0 && currentStep < 4 && (
                <Button onClick={goBack} style={{ marginRight: 16 }}>
                  返回上一步
                </Button>
              )}
              {interrupt.action === 'ready_for_next_chapter' ? (
                <Space size="middle">
                  <Button
                    type="primary"
                    size="large"
                    onClick={() => invokeWorkflow('next')}
                    icon={<EditOutlined />}
                  >
                    生成下一章
                  </Button>
                  <Button
                    size="large"
                    onClick={() => navigate(`/progress/${novelId}`)}
                  >
                    查看章节目录
                  </Button>
                </Space>
              ) : (
                <Button type="primary" onClick={handleInterruptResume} loading={loading}>
                  确认并继续
                </Button>
              )}
            </div>
          </div>
        )}

        {/* Step 4: 创作进行中 */}
        {!interrupt && currentStep >= 4 && (
          <div>
            <Alert message="小说创作进行中..." type="success" />
            <Button
              type="primary"
              onClick={() => navigate(`/progress/${novelId}`)}
              style={{ marginTop: 16 }}
            >
              查看进度
            </Button>
          </div>
        )}
      </Card>
      )}
    </div>
  )
}

export default NovelConfig
