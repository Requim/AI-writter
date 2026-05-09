import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Card, Steps, Radio, Input, Button, Form, message, Alert, Space, Spin, Progress, Tag, InputNumber, Collapse, Divider, Typography, Select } from 'antd'
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
  const [editableIssues, setEditableIssues] = useState<any[]>([])       // 可编辑的反思问题
  const [customInstruction, setCustomInstruction] = useState('')        // 用户自定义修正指令
  const [streamNode, setStreamNode] = useState('')                       // 当前流式节点名
  const [streamDone, setStreamDone] = useState<string[]>([])             // 已完成的流式节点
  const [streaming, setStreaming] = useState(false)                      // 是否在流式处理中

  // ====== 章节细纲场景字段兼容（新旧格式统一） ======
  function normalizeSceneFields(s: any): any {
    // events: 旧版 array → 统一为 dict {entry, struggle, result}
    if (Array.isArray(s.events)) {
      s.events = { entry: s.events[0] || '', struggle: s.events[1] || '', result: s.events[2] || '' }
    }
    // sensory_details: 旧版 array → 统一为 dict {visual, auditory, olfactory_tactile}
    if (Array.isArray(s.sensory_details)) {
      const arr = s.sensory_details as string[]
      s.sensory_details = { visual: arr[0] || '', auditory: arr[1] || '', olfactory_tactile: arr[2] || '' }
    }
    // dialogue_targets: 旧版 array → 统一为 dict {explicit, implicit}
    if (Array.isArray(s.dialogue_targets)) {
      s.dialogue_targets = { explicit: s.dialogue_targets[0] || '', implicit: s.dialogue_targets[1] || '' }
    }
    // events 是字符串（旧版极简格式）→ 转 dict
    if (typeof s.events === 'string') {
      s.events = { entry: s.events, struggle: '', result: '' }
    }
    return s
  }

  // ====== 大纲字段兼容：中文/英文键名统一为中文 ======
  function normalizeCharacters(chars: any[]): any[] {
    return (chars || []).map((c: any) => ({
      '姓名': c['姓名'] || c.name || '',
      '性格': c['性格'] || c.personality || '',
      '目标': c['目标'] || c.goal || '',
      '冲突对象': c['冲突对象'] || c.conflict || '',
      '关系标签': c['关系标签'] || c.relationTag || c.relation_tag || '',
    }))
  }

  // ====== main_plot 字段兼容：中文键（起承转合）→ 英文键（beginning/development/climax/ending） ======
  function normalizeMainPlot(plot: any): any {
    if (!plot || typeof plot !== 'object') {
      return { beginning: '', development: '', climax: '', ending: '' }
    }
    return {
      beginning: plot.beginning || plot['起'] || '',
      development: plot.development || plot['承'] || '',
      climax: plot.climax || plot['转'] || '',
      ending: plot.ending || plot['合'] || '',
    }
  }

  // 节点名 → 中文进度标签
  const nodeLabels: Record<string, string> = {
    title_node: '生成书名',
    summary_node: '生成简介',
    outline_node: '生成总纲领',
    progress_check_node: '进度检查',
    memory_retrieval_node: '检索前文记忆',
    chapter_outline_node: '生成章节细纲',
    chapter_writer_node: '撰写章节内容',
    reflection_node: '质量检查',
    revision_node: '修正内容',
    persist_node: '保存章节',
  }

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
      // 统一角色字段为中文键名（兼容新旧格式）
      if (outline.main_characters) {
        outline.main_characters = normalizeCharacters(outline.main_characters)
      }
      // 统一 main_plot 字段：中文键（起承转合）→ 英文键（beginning/development/climax/ending）
      if (outline.main_plot) {
        outline.main_plot = normalizeMainPlot(outline.main_plot)
      }
      setEditableOutline(outline)
    }
    // 简介确认：自动填入AI生成的内容
    if (interrupt?.action === 'confirm_or_provide_summary' && interrupt.ai_generated_summary && !summary) {
      setSummary(interrupt.ai_generated_summary)
    }
    // 章节细纲：初始化可编辑数据（兼容新旧格式）
    if (interrupt?.action === 'review_or_provide_chapter_outline' && interrupt.ai_generated_outline) {
      const raw = JSON.parse(JSON.stringify(interrupt.ai_generated_outline))
      // 标准化 scenes 字段（兼容新旧格式）
      if (raw.scenes) {
        raw.scenes = raw.scenes.map((s: any) => normalizeSceneFields(s))
      }
      setEditableChapter(raw)
    }
    // 反思问题：初始化可编辑数据
    if (interrupt?.action === 'review_reflection_issues' && interrupt.issues) {
      setEditableIssues(JSON.parse(JSON.stringify(interrupt.issues)))
      setCustomInstruction('')
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
            const interruptAction = interruptValue?.action || ''

            // ready_for_next_chapter → 自动 resume，直接继续创作
            if (interruptAction === 'ready_for_next_chapter') {
              // chapter_number 是当前已完成章节，下一章要 +1
              const nextChapter = (interruptValue.chapter_number || 0) + 1
              setChapterNum(nextChapter)
              setCurrentStep(4)
              setStreaming(true)
              setStreamNode('')
              setStreamDone([])
              // 延迟一下让 UI 更新，再发起流
              setTimeout(() => invokeWorkflow('next', threadId, novelData.id), 100)
              return
            }

            setInterrupt(interruptValue)
            setCurrentStep(getStepFromAction(interruptAction))
            if (interruptValue.chapter_number) {
              setChapterNum(interruptValue.chapter_number)
            }
            message.info('已恢复上次创作进度')
          } else {
            // 无中断 → 发起新流，用已有数据跳过设定阶段
            setStreaming(true)
            setStreamNode('')
            setStreamDone([])
            // 从 total_outline 推算当前章节数
            const existingChapters = novelData.total_outline?.total_chapters || 0
            setChapterNum(existingChapters > 0 ? 1 : 0)
            // 构造包含已有数据的 input，让设定节点全部跳过
            const inputData = {
              input: {
                novel_id: novelData.id,
                novel_type: novelData.novel_type,
                title: novelData.title || '',
                summary: novelData.summary || '',
                total_outline: novelData.total_outline || {},
                current_chapter_content: '',  // 清空旧内容，防止 persist_node 误判为章节阶段
              }
            }
            invokeWorkflow(inputData, threadId, novelData.id)
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

  // ====== rewrite 参数兼容（保留但不使用） ======
  // 重写功能已移除，所有操作通过"继续创作"进入工作流

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

  // 调用工作流（流式版本）
  const invokeWorkflow = async (resumeValue?: any, tid?: string | null, nid?: string | null) => {
    const effectiveThreadId = tid || threadId
    const effectiveNovelId = nid || novelId
    if (!effectiveThreadId) return

    // resumeValue === undefined → 首次启动工作流（新 input）
    // resumeValue 为 { input: {...} } 对象 → 直接使用（恢复模式加载已有状态，跳过设定阶段）
    // 其他情况（string 或 object）→ 从 interrupt 恢复，作为 command.resume 发送
    let data: any
    if (resumeValue === undefined) {
      data = { input: { novel_id: effectiveNovelId, novel_type: novelType } }
    } else if (resumeValue && typeof resumeValue === 'object' && 'input' in resumeValue) {
      data = resumeValue
    } else {
      data = { command: { resume: resumeValue } }
    }

    setStreaming(true)
    setStreamNode('')
    setStreamDone([])
    console.log('[invokeWorkflow] stream start:', { threadId: effectiveThreadId, data: JSON.stringify(data) })

    try {
      const response = await workflowApi.streamWorkflow(effectiveThreadId, data)
      if (!response.ok) {
        const errText = await response.text()
        throw new Error(errText || `HTTP ${response.status}`)
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const payload = line.slice(6)
          if (payload === '[DONE]') continue

          try {
            const chunk = JSON.parse(payload)
            if (chunk.error) { throw new Error(chunk.error) }

            // 检查中断
            if (chunk.__interrupt__ && chunk.__interrupt__.length > 0) {
              reader.cancel()
              const interruptValue = chunk.__interrupt__[0].value
              const interruptAction = interruptValue?.action || ''
              const newStep = getStepFromAction(interruptAction)
              const newChapterNum = interruptValue?.chapter_number || 0
              console.log('[invokeWorkflow] interrupt received:', { action: interruptAction, step: newStep, chapter: newChapterNum })
              setChapterNum(newChapterNum)
              setInterrupt(interruptValue)
              setCurrentStep(newStep)
              setStreaming(false)

              // 章节完成 -> 自动跳转到书籍详情页
              if (interruptAction === 'ready_for_next_chapter') {
                message.success(`第 ${newChapterNum} 章已完成！`)
                // 延迟跳转，让 UI 先更新
                setTimeout(() => {
                  navigate(`/progress/${effectiveNovelId}`)
                }, 500)
              }
              return
            }

            // 更新进度：取 chunk 中第一个非 __ 开头的 key
            const nodeKey = Object.keys(chunk).find(k => !k.startsWith('__'))
            if (nodeKey && nodeLabels[nodeKey]) {
              setStreamNode(nodeKey)
              setStreamDone(prev => prev.includes(nodeKey) ? prev : [...prev, nodeKey])
            }
          } catch (parseErr) {
            // 非 JSON chunk，忽略
          }
        }
      }

      // 流结束无中断：可能是 LLM 耗时太长连接断开，查一下 state 确认
      setStreaming(false)
      try {
        const stateData: any = await workflowApi.getWorkflowState(effectiveThreadId)
        if (stateData.has_interrupt && stateData.interrupts?.length > 0) {
          const interruptValue = stateData.interrupts[0].value
          setInterrupt(interruptValue)
          setCurrentStep(getStepFromAction(interruptValue.action))
          if (interruptValue.chapter_number) {
            setChapterNum(interruptValue.chapter_number)
          }
          return
        }
      } catch (_) {
        // 查 state 失败，按无中断处理
      }
      setInterrupt(null)
      navigate(`/progress/${effectiveNovelId}`)
    } catch (error: any) {
      setStreaming(false)
      console.error('[invokeWorkflow] error:', error)
      message.error(`处理失败: ${error.message || '未知错误'}`)
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
      message.destroy('creating')

      // 立即切换到书名确认 UI（等待中断）
      setCurrentStep(1)
      setInterrupt({
        action: 'confirm_or_provide_title',
        message: '正在生成中...',
      })
      setStreaming(true)
      setStreamNode('')
      setStreamDone([])

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

  // 处理 interrupt 恢复（自动推进下一步）
  const handleInterruptResume = () => {
    if (!interrupt) return
    switch (interrupt.action) {
      case 'require_novel_type':
        invokeWorkflow(novelType)
        break
      case 'confirm_or_provide_title': {
        const firstSuggestion = interrupt.ai_suggestions?.[0]
        const defaultTitle = typeof firstSuggestion === 'string' ? firstSuggestion : firstSuggestion?.title || '未命名小说'
        invokeWorkflow(title || defaultTitle)
        break
      }
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
      case 'user_fix':
        invokeWorkflow(customInstruction || '请根据问题列表自动修正')
        break
      case 'confirm_revision':
        invokeWorkflow('accept')
        break
    }
  }

  // 当前中断 → 下一步中断 action 映射
  const nextInterruptAction: Record<string, string> = {
    'confirm_or_provide_title': 'confirm_or_provide_summary',
    'confirm_or_provide_summary': 'review_or_modify_outline',
    'review_or_modify_outline': 'review_or_provide_chapter_outline',
    'review_or_provide_chapter_outline': 'review_or_provide_chapter_outline',
  }

  // 用户确认当前步骤后，立即切换到下一步 UI，同时发起流
  const handleConfirmAndContinue = () => {
    if (!interrupt) return
    const currentAction = interrupt.action

    // 计算下一步的 step 和占位 action
    const nextAction = nextInterruptAction[currentAction]
    const nextStep = nextAction ? getStepFromAction(nextAction) : currentStep

    // 立刻切换到下一步 UI：插入一个"等待中"的占位中断
    const placeholderInterrupt: InterruptInfo = {
      action: nextAction || currentAction,
      message: '正在生成中...',
    }
    setCurrentStep(nextStep)
    setInterrupt(placeholderInterrupt)
    setStreaming(true)
    setStreamNode('')
    setStreamDone([])

    // 发起流
    handleInterruptResume()
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

        {/* 流式进度节点标签（遮罩内已有 Spin，此处只显示已完成的节点名） */}
        {streaming && streamDone.length > 0 && (
          <div style={{ marginBottom: 24 }}>
            <Space wrap size={[8, 4]}>
              {streamDone.map(node => (
                <Tag key={node} color="success">✓ {nodeLabels[node] || node}</Tag>
              ))}
            </Space>
          </div>
        )}

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
          <div style={{ position: 'relative' }}>
            {/* 等待遮罩：流处理中且为占位中断时显示 */}
            {streaming && interrupt.message === '正在生成中...' && (
              <div style={{
                position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
                background: 'rgba(255,255,255,0.85)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                zIndex: 10, borderRadius: 8,
              }}>
                <div style={{ textAlign: 'center' }}>
                  <Spin size="large" style={{ display: 'block', marginBottom: 16 }} />
                  <span style={{ color: '#666', fontSize: 15 }}>正在生成中...</span>
                </div>
              </div>
            )}
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
                    <p style={{ fontWeight: 500, marginBottom: 8 }}>AI推荐书名（点击选中）：</p>
                    <Space wrap>
                      {interrupt.ai_suggestions.map((s: any, i: number) => {
                        const item = typeof s === 'string' ? { title: s, hint: '' } : s
                        return (
                          <Button
                            key={i}
                            onClick={() => setTitle(item.title)}
                            type={title === item.title ? 'primary' : 'default'}
                            style={{ height: 'auto', padding: '8px 16px', whiteSpace: 'normal', maxWidth: 320 }}
                          >
                            <div style={{ textAlign: 'left' }}>
                              <div style={{ fontWeight: 600, fontSize: 15 }}>{item.title}</div>
                              {item.hint && (
                                <div style={{ fontSize: 12, opacity: 0.65, marginTop: 2 }}>
                                  {item.hint}
                                </div>
                              )}
                            </div>
                          </Button>
                        )
                      })}
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

                {/* 大纲校验报告 */}
                {interrupt.validation?.issues?.length > 0 && (
                  <Alert
                    type="warning"
                    showIcon
                    message="大纲校验发现以下问题（已自动修复部分）"
                    description={
                      <ul style={{ margin: 0, paddingLeft: 20 }}>
                        {interrupt.validation.issues.map((issue: string, i: number) => (
                          <li key={i}>{issue}</li>
                        ))}
                      </ul>
                    }
                    style={{ marginBottom: 16 }}
                  />
                )}

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
                      <div style={{ marginBottom: 8, fontSize: 13, color: '#888' }}>
                        <Tag color="blue">角色 {i + 1}</Tag>
                        <span style={{ marginLeft: 8 }}>{char['姓名'] || '未命名'}</span>
                      </div>
                      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                        <div style={{ flex: '1 1 120px' }}>
                          <Form.Item label="姓名" style={{ marginBottom: 0 }}>
                            <Input
                              value={char['姓名'] || ''}
                              onChange={(e) => {
                                const chars = [...editableOutline.main_characters]
                                chars[i] = { ...chars[i], '姓名': e.target.value }
                                setEditableOutline({ ...editableOutline, main_characters: chars })
                              }}
                              placeholder="角色名"
                              size="small"
                            />
                          </Form.Item>
                        </div>
                        <div style={{ flex: '1 1 140px' }}>
                          <Form.Item label="性格" style={{ marginBottom: 0 }}>
                            <Input
                              value={char['性格'] || ''}
                              onChange={(e) => {
                                const chars = [...editableOutline.main_characters]
                                chars[i] = { ...chars[i], '性格': e.target.value }
                                setEditableOutline({ ...editableOutline, main_characters: chars })
                              }}
                              placeholder="2-4个核心特质"
                              size="small"
                            />
                          </Form.Item>
                        </div>
                        <div style={{ flex: '1 1 160px' }}>
                          <Form.Item label="目标" style={{ marginBottom: 0 }}>
                            <Input
                              value={char['目标'] || ''}
                              onChange={(e) => {
                                const chars = [...editableOutline.main_characters]
                                chars[i] = { ...chars[i], '目标': e.target.value }
                                setEditableOutline({ ...editableOutline, main_characters: chars })
                              }}
                              placeholder="随剧情演进的动态目标"
                              size="small"
                            />
                          </Form.Item>
                        </div>
                        <div style={{ flex: '1 1 160px' }}>
                          <Form.Item label="冲突对象" style={{ marginBottom: 0 }}>
                            <Input
                              value={char['冲突对象'] || ''}
                              onChange={(e) => {
                                const chars = [...editableOutline.main_characters]
                                chars[i] = { ...chars[i], '冲突对象': e.target.value }
                                setEditableOutline({ ...editableOutline, main_characters: chars })
                              }}
                              placeholder="与谁本质对抗？"
                              size="small"
                            />
                          </Form.Item>
                        </div>
                        <div style={{ flex: '1 1 180px' }}>
                          <Form.Item label="关系标签" style={{ marginBottom: 0 }}>
                            <Input
                              value={char['关系标签'] || ''}
                              onChange={(e) => {
                                const chars = [...editableOutline.main_characters]
                                chars[i] = { ...chars[i], '关系标签': e.target.value }
                                setEditableOutline({ ...editableOutline, main_characters: chars })
                              }}
                              placeholder="引路人/隐藏反派/被背叛的盟友"
                              size="small"
                            />
                          </Form.Item>
                        </div>
                      </div>
                    </div>
                  ))}
                  <Button
                    size="small"
                    type="dashed"
                    onClick={() => {
                      const chars = [...(editableOutline.main_characters || [])]
                      chars.push({ '姓名': '', '性格': '', '目标': '', '冲突对象': '', '关系标签': '' })
                      setEditableOutline({ ...editableOutline, main_characters: chars })
                    }}
                    icon={<EditOutlined />}
                    style={{ marginBottom: 16 }}
                  >
                    添加角色
                  </Button>
                  <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 8 }}>
                    {editableOutline.main_characters?.length || 0} / 至少 9 个角色 · 提示：每个角色至少应与 2 人有关联，反派需有合理动机
                  </Typography.Text>

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

                  {/* 卷结构 */}
                  {(editableOutline.volumes || []).length > 0 && (
                    <>
                      <Divider orientation="left" plain>
                        卷结构规划（{editableOutline.volumes.length}卷）
                        <Tag style={{ marginLeft: 8 }} color="purple">节拍点</Tag>
                      </Divider>
                      <Collapse
                        ghost
                        size="small"
                        items={editableOutline.volumes.map((vol: any, vi: number) => ({
                          key: `vol-${vi}`,
                          label: (
                            <Space>
                              <Tag color="purple">V{vi + 1}</Tag>
                              <Typography.Text strong>{vol.volume_name || `第${vi + 1}卷`}</Typography.Text>
                              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                第{vol.start_chapter || '?'}-{vol.end_chapter || '?'}章
                              </Typography.Text>
                            </Space>
                          ),
                          children: (
                            <div style={{ paddingLeft: 8 }}>
                              <Form.Item label="卷名" style={{ marginBottom: 8 }}>
                                <Input
                                  value={vol.volume_name || ''}
                                  onChange={(e) => {
                                    const vols = [...editableOutline.volumes]
                                    vols[vi] = { ...vols[vi], volume_name: e.target.value }
                                    setEditableOutline({ ...editableOutline, volumes: vols })
                                  }}
                                  size="small"
                                />
                              </Form.Item>
                              <div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
                                <Form.Item label="起始章节" style={{ marginBottom: 0 }}>
                                  <InputNumber
                                    value={vol.start_chapter}
                                    onChange={(val) => {
                                      const vols = [...editableOutline.volumes]
                                      vols[vi] = { ...vols[vi], start_chapter: val || 1 }
                                      setEditableOutline({ ...editableOutline, volumes: vols })
                                    }}
                                    min={1} size="small" style={{ width: 80 }}
                                  />
                                </Form.Item>
                                <Form.Item label="结束章节" style={{ marginBottom: 0 }}>
                                  <InputNumber
                                    value={vol.end_chapter}
                                    onChange={(val) => {
                                      const vols = [...editableOutline.volumes]
                                      vols[vi] = { ...vols[vi], end_chapter: val || 1 }
                                      setEditableOutline({ ...editableOutline, volumes: vols })
                                    }}
                                    min={1} size="small" style={{ width: 80 }}
                                  />
                                </Form.Item>
                              </div>
                              <Form.Item label="核心冲突" style={{ marginBottom: 8 }}>
                                <Input.TextArea
                                  value={vol.core_conflict || ''}
                                  onChange={(e) => {
                                    const vols = [...editableOutline.volumes]
                                    vols[vi] = { ...vols[vi], core_conflict: e.target.value }
                                    setEditableOutline({ ...editableOutline, volumes: vols })
                                  }}
                                  rows={2} size="small"
                                />
                              </Form.Item>
                              <Form.Item label="主角弧线" style={{ marginBottom: 8 }}>
                                <Input.TextArea
                                  value={vol.main_character_arc || ''}
                                  onChange={(e) => {
                                    const vols = [...editableOutline.volumes]
                                    vols[vi] = { ...vols[vi], main_character_arc: e.target.value }
                                    setEditableOutline({ ...editableOutline, volumes: vols })
                                  }}
                                  rows={2} size="small"
                                />
                              </Form.Item>
                              <Form.Item label="高潮事件" style={{ marginBottom: 0 }}>
                                <Input.TextArea
                                  value={vol.climax_event || ''}
                                  onChange={(e) => {
                                    const vols = [...editableOutline.volumes]
                                    vols[vi] = { ...vols[vi], climax_event: e.target.value }
                                    setEditableOutline({ ...editableOutline, volumes: vols })
                                  }}
                                  rows={2} size="small"
                                />
                              </Form.Item>
                            </div>
                          ),
                        }))}
                      />
                    </>
                  )}

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
                      min={1} max={300}
                      style={{ width: 120 }}
                    />
                  </Form.Item>

                  {/* 章节规划 */}
                  {(editableOutline.chapters || []).length > 0 && (
                    <Collapse
                      ghost
                      items={[{
                        key: 'chapters',
                        label: `章节规划（${editableOutline.chapters.length}/${editableOutline.total_chapters}章）`,
                        children: (
                          <div style={{ maxHeight: 400, overflow: 'auto' }}>
                            {editableOutline.chapters.map((ch: any, i: number) => (
                              <div key={i} style={{
                                marginBottom: 8, padding: '8px 10px',
                                background: ch.volume_name ? '#fafafa' : '#fff',
                                borderRadius: 4, border: '1px solid #f0f0f0'
                              }}>
                                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4, flexWrap: 'wrap' }}>
                                  <Typography.Text strong style={{ minWidth: 60 }}>
                                    {ch.chapter_number ? `#${ch.chapter_number}` : `#${i + 1}`}
                                  </Typography.Text>
                                  <Input
                                    value={ch.theme || ''}
                                    onChange={(e) => {
                                      const chs = [...editableOutline.chapters]
                                      chs[i] = { ...chs[i], theme: e.target.value }
                                      setEditableOutline({ ...editableOutline, chapters: chs })
                                    }}
                                    size="small"
                                    style={{ width: 220 }}
                                    placeholder="章节主题"
                                  />
                                  {ch.volume_name && (
                                    <Tag color="purple" style={{ fontSize: 11, margin: 0 }}>
                                      {ch.volume_name.replace(/第[^卷]*卷/g, '') || ch.volume_name}
                                    </Tag>
                                  )}
                                </div>
                                {(ch.key_events || []).length > 0 && (
                                  <div style={{ marginTop: 4, paddingLeft: 68 }}>
                                    {(ch.key_events as string[]).slice(0, 2).map((evt: string, ei: number) => (
                                      <Typography.Text
                                        key={ei}
                                        type="secondary"
                                        style={{ display: 'block', fontSize: 12, lineHeight: 1.6 }}
                                        ellipsis={{ tooltip: evt }}
                                      >
                                        · {evt}
                                      </Typography.Text>
                                    ))}
                                    {(ch.key_events as string[]).length > 2 && (
                                      <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                                        + {(ch.key_events as string[]).length - 2} 个事件
                                      </Typography.Text>
                                    )}
                                  </div>
                                )}
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
                  <Divider orientation="left" plain>
                    场景安排
                    <Tag style={{ marginLeft: 8 }} color="blue">
                      {(editableChapter.scenes || []).length} 个场景
                    </Tag>
                    {(editableChapter.scenes || []).length >= 3 && (
                      <Tag color="green">建议≥3场景（场景队列模式）</Tag>
                    )}
                  </Divider>
                  <Alert
                    type="info"
                    showIcon
                    message="字数分布要求"
                    description="写作引擎会按场景数均匀分配字数，严禁场景一详细、后序场景草草结束。如果本章3个场景，每个约1700字。请在下方「目标字数」中为每个场景指定预期字数。"
                    style={{ marginBottom: 12, fontSize: 13 }}
                  />
                  {(editableChapter.scenes || []).map((s: any, i: number) => (
                    <div key={i} style={{ marginBottom: 12, padding: 12, background: '#fafafa', borderRadius: 8, border: '1px solid #f0f0f0' }}>
                      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                        <div style={{ flex: 1 }}>
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
                        </div>
                        <Form.Item label="目标字数" style={{ marginBottom: 8, width: 130 }}>
                          <InputNumber
                            value={s.target_words}
                            onChange={(val) => {
                              const sc = [...editableChapter.scenes]
                              sc[i] = { ...sc[i], target_words: val || undefined }
                              setEditableChapter({ ...editableChapter, scenes: sc })
                            }}
                            min={500} max={4000} step={100}
                            style={{ width: '100%' }}
                            size="small"
                            placeholder="自动"
                          />
                        </Form.Item>
                      </div>
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
                      {/* 情节三阶段：入场-拉锯-结果 */}
                      <Form.Item label="情节三阶段" style={{ marginBottom: 4 }}>
                        <div style={{ display: 'flex', gap: 8, flexDirection: 'column' }}>
                          <Input
                            value={s.events?.entry || ''}
                            onChange={(e) => {
                              const sc = [...editableChapter.scenes]
                              sc[i] = { ...sc[i], events: { ...sc[i].events, entry: e.target.value } }
                              setEditableChapter({ ...editableChapter, scenes: sc })
                            }}
                            placeholder="【入场】环境描写与角色登场"
                            size="small"
                          />
                          <Input
                            value={s.events?.struggle || ''}
                            onChange={(e) => {
                              const sc = [...editableChapter.scenes]
                              sc[i] = { ...sc[i], events: { ...sc[i].events, struggle: e.target.value } }
                              setEditableChapter({ ...editableChapter, scenes: sc })
                            }}
                            placeholder="【拉锯】心理博弈与冲突升级"
                            size="small"
                          />
                          <Input
                            value={s.events?.result || ''}
                            onChange={(e) => {
                              const sc = [...editableChapter.scenes]
                              sc[i] = { ...sc[i], events: { ...sc[i].events, result: e.target.value } }
                              setEditableChapter({ ...editableChapter, scenes: sc })
                            }}
                            placeholder="【结果】关系位移与场景落点"
                            size="small"
                          />
                        </div>
                      </Form.Item>
                      {/* 感官三位一体：视觉/听觉/嗅觉触觉 */}
                      <Form.Item label="感官细节（三通道）" style={{ marginBottom: 8 }}>
                        <div style={{ display: 'flex', gap: 8, flexDirection: 'column' }}>
                          <Input
                            value={s.sensory_details?.visual || ''}
                            onChange={(e) => {
                              const sc = [...editableChapter.scenes]
                              sc[i] = { ...sc[i], sensory_details: { ...sc[i].sensory_details, visual: e.target.value } }
                              setEditableChapter({ ...editableChapter, scenes: sc })
                            }}
                            placeholder="【视觉】光影/色彩/人物神态"
                            size="small"
                          />
                          <Input
                            value={s.sensory_details?.auditory || ''}
                            onChange={(e) => {
                              const sc = [...editableChapter.scenes]
                              sc[i] = { ...sc[i], sensory_details: { ...sc[i].sensory_details, auditory: e.target.value } }
                              setEditableChapter({ ...editableChapter, scenes: sc })
                            }}
                            placeholder="【听觉】环境音/语气/沉默"
                            size="small"
                          />
                          <Input
                            value={s.sensory_details?.olfactory_tactile || ''}
                            onChange={(e) => {
                              const sc = [...editableChapter.scenes]
                              sc[i] = { ...sc[i], sensory_details: { ...sc[i].sensory_details, olfactory_tactile: e.target.value } }
                              setEditableChapter({ ...editableChapter, scenes: sc })
                            }}
                            placeholder="【嗅觉/触觉】气味/温度/质感"
                            size="small"
                          />
                        </div>
                      </Form.Item>
                      {/* 对话明暗线：明线/暗线潜台词 */}
                      <Form.Item label="对话设计（明暗线）" style={{ marginBottom: 8 }}>
                        <div style={{ display: 'flex', gap: 8, flexDirection: 'column' }}>
                          <Input
                            value={s.dialogue_targets?.explicit || ''}
                            onChange={(e) => {
                              const sc = [...editableChapter.scenes]
                              sc[i] = { ...sc[i], dialogue_targets: { ...sc[i].dialogue_targets, explicit: e.target.value } }
                              setEditableChapter({ ...editableChapter, scenes: sc })
                            }}
                            placeholder="【明线】表面要达成的对话目标"
                            size="small"
                          />
                          <Input
                            value={s.dialogue_targets?.implicit || ''}
                            onChange={(e) => {
                              const sc = [...editableChapter.scenes]
                              sc[i] = { ...sc[i], dialogue_targets: { ...sc[i].dialogue_targets, implicit: e.target.value } }
                              setEditableChapter({ ...editableChapter, scenes: sc })
                            }}
                            placeholder="【暗线/潜台词】角色真正想表达的"
                            size="small"
                          />
                        </div>
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

                  {/* 写作约束参考 */}
                  <Collapse
                    ghost
                    size="small"
                    style={{ marginBottom: 16 }}
                    items={[{
                      key: 'writing-constraints',
                      label: <Typography.Text type="secondary" style={{ fontSize: 13 }}>📋 写作约束参考（AI 将严格遵循以下五点）</Typography.Text>,
                      children: (
                        <div style={{ fontSize: 13, lineHeight: 2, padding: '4px 8px', background: '#fafafa', borderRadius: 6 }}>
                          <p><strong>一、信息密度与结构均衡</strong><br />
                            每个场景字数均匀分布，严禁场景一详细、后续草草结束。
                            每段文字必须提供新信息/情感波动/情节推进，禁止无意义堆砌景物。</p>
                          <p><strong>二、逻辑钩子强制执行</strong><br />
                            前 10% 内容必须体现 Callback 回收；后 10% 必须聚焦 Setup 埋设；
                            中间 80% 自然融入情节。</p>
                          <p><strong>三、对话的非直接性</strong><br />
                            严禁连续 3 句以上纯对白；每 2 句对话间穿插视觉焦点转移或手部动作描写；
                            保留 30% 潜台词空间，避免直白表达。</p>
                          <p><strong>四、镜头感与描写配比</strong><br />
                            动作:对话:心理:环境 ≈ 3:3:2:2。关键冲突处用慢镜头（拆解为连续动态过程）。
                            每场景 ≥3 处生理反应描写。环境须映射人物心理。</p>
                          <p><strong>五、分镜头扩写流程</strong><br />
                            步骤：细节预演（感官→50-100字描写）→ 情节填充（入场→拉锯→结果）→
                            对话生成（明线+暗线+动作穿插）→ 转场过渡。</p>
                        </div>
                      ),
                    }]}
                  />

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
                  <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 8 }}>
                    提示：必须指定影响的具体章节号，禁止写"为后文埋下伏笔"这种模糊表述
                  </Typography.Text>
                  <Form.Item
                    label="回收的前文伏笔（Callback）"
                    help="⚠️ 必须在「本章前 10%」内容中体现回收，开篇即点出前文设局"
                  >
                    <Input.TextArea
                      value={editableChapter.logic_hooks?.callback || ''}
                      onChange={(e) => setEditableChapter({
                        ...editableChapter,
                        logic_hooks: { ...editableChapter.logic_hooks, callback: e.target.value }
                      })}
                      placeholder="回收前文第X章的伏笔：具体伏笔内容"
                      rows={2}
                    />
                  </Form.Item>
                  <Form.Item
                    label="埋下的新矛盾（Setup）"
                    help="⚠️ 必须在「本章后 10%」内容中聚焦埋设，确保读者有翻页冲动"
                  >
                    <Input.TextArea
                      value={editableChapter.logic_hooks?.setup || ''}
                      onChange={(e) => setEditableChapter({
                        ...editableChapter,
                        logic_hooks: { ...editableChapter.logic_hooks, setup: e.target.value }
                      })}
                      placeholder="为后文第Y章埋下新矛盾：具体矛盾描述"
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
                {/* 评分 & 有效密度概览 */}
                {(() => {
                  const wc = interrupt.word_count_analysis || {}
                  const density = wc.effective_density
                  const densityColor = density !== undefined ? (density >= 70 ? 'green' : density >= 50 ? 'orange' : 'red') : undefined
                  return (
                    <Alert
                      message={
                        <span>
                          第 {interrupt.chapter_number || '?'} 章质量检查未通过&nbsp;
                          <Tag color={interrupt.quality_score >= 0.8 ? 'green' : 'red'}>
                            评分 {interrupt.quality_score ?? '?'}
                          </Tag>
                          {density !== undefined && (
                            <Tag color={densityColor}>
                              有效密度 {density}%
                            </Tag>
                          )}
                          <Tag color={wc.is_valid_word_count ? 'green' : 'red'}>
                            字数 {wc.total_count ?? '?'}
                          </Tag>
                        </span>
                      }
                      type="warning"
                      style={{ marginBottom: 16 }}
                    />
                  )
                })()}

                {/* 逻辑链状态 + 伏笔检查 */}
                {interrupt.logic_chain_status && (
                  <Alert
                    message="前文衔接检查"
                    description={interrupt.logic_chain_status}
                    type={interrupt.logic_chain_status.includes('断层') || interrupt.logic_chain_status.includes('断裂') ? 'error' : 'info'}
                    style={{ marginBottom: 8 }}
                    showIcon
                  />
                )}
                {interrupt.foreshadowing_check && (
                  <Alert
                    message="伏笔检查"
                    description={interrupt.foreshadowing_check}
                    type={interrupt.foreshadowing_check.includes('未提及') || interrupt.foreshadowing_check.includes('缺失') ? 'warning' : 'success'}
                    style={{ marginBottom: 16 }}
                    showIcon
                  />
                )}

                {/* 可编辑问题列表 */}
                {editableIssues.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    {editableIssues.map((issue: any, idx: number) => (
                      <div key={idx} style={{ marginBottom: 12, padding: 12, background: '#fff7e6', borderRadius: 8, border: '1px solid #ffd591' }}>
                        <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                          <Input
                            value={issue.type || ''}
                            onChange={(e) => {
                              const items = [...editableIssues]
                              items[idx] = { ...items[idx], type: e.target.value }
                              setEditableIssues(items)
                            }}
                            placeholder="问题类型"
                            size="small"
                            style={{ width: 100 }}
                          />
                          <Select
                            value={issue.severity || 'medium'}
                            onChange={(val) => {
                              const items = [...editableIssues]
                              items[idx] = { ...items[idx], severity: val }
                              setEditableIssues(items)
                            }}
                            size="small"
                            style={{ width: 100 }}
                            options={[
                              { value: 'low', label: '低' },
                              { value: 'medium', label: '中' },
                              { value: 'high', label: '高' },
                            ]}
                          />
                          <Tag color={issue.severity === 'high' ? 'red' : issue.severity === 'medium' ? 'orange' : 'blue'}>
                            {issue.severity === 'high' ? '严重' : issue.severity === 'medium' ? '一般' : '轻微'}
                          </Tag>
                          <Input
                            value={issue.location || ''}
                            onChange={(e) => {
                              const items = [...editableIssues]
                              items[idx] = { ...items[idx], location: e.target.value }
                              setEditableIssues(items)
                            }}
                            placeholder="位置"
                            size="small"
                            style={{ width: 160 }}
                          />
                        </div>
                        <Form.Item style={{ marginBottom: 8 }}>
                          <Input.TextArea
                            value={issue.description || ''}
                            onChange={(e) => {
                              const items = [...editableIssues]
                              items[idx] = { ...items[idx], description: e.target.value }
                              setEditableIssues(items)
                            }}
                            placeholder="问题描述"
                            rows={2}
                            size="small"
                          />
                        </Form.Item>
                        <Form.Item style={{ marginBottom: 0 }}>
                          <Input
                            value={issue.suggestion || ''}
                            onChange={(e) => {
                              const items = [...editableIssues]
                              items[idx] = { ...items[idx], suggestion: e.target.value }
                              setEditableIssues(items)
                            }}
                            placeholder="修正建议"
                            size="small"
                          />
                        </Form.Item>
                      </div>
                    ))}
                  </div>
                )}

                {/* 自定义修正指令输入区 */}
                <div style={{ marginBottom: 12, padding: 12, background: '#f0f5ff', borderRadius: 8, border: '1px solid #adc6ff' }}>
                  <p style={{ fontWeight: 500, marginBottom: 8 }}>自定义修正指令（选填）：</p>
                  <Input.TextArea
                    value={customInstruction}
                    onChange={(e) => setCustomInstruction(e.target.value)}
                    placeholder="例如：把对话改得更紧张、删掉冗余的环境描写、增加主角的心理活动..."
                    rows={3}
                  />
                </div>

                <p style={{ marginBottom: 8, fontWeight: 500 }}>选择处理方式：</p>
                <Space wrap>
                  <Button onClick={() => invokeWorkflow('accept')}>接受（忽略问题）</Button>
                  <Button type="primary" onClick={() => invokeWorkflow('revise')}>
                    AI自动修正
                  </Button>
                  <Button onClick={() => {
                    if (!customInstruction.trim()) {
                      message.warning('请先填写自定义修正指令')
                      return
                    }
                    invokeWorkflow(customInstruction.trim())
                  }}>
                    按指令修正
                  </Button>
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
              {currentStep > 0 && currentStep < 4 && interrupt.message !== '正在生成中...' && (
                <Button onClick={goBack} style={{ marginRight: 16 }}>
                  返回上一步
                </Button>
              )}
              {interrupt.action !== 'ready_for_next_chapter' && interrupt.message !== '正在生成中...' && (
                <Button type="primary" onClick={handleConfirmAndContinue} loading={loading || streaming} disabled={streaming}>
                  确认并继续
                </Button>
              )}
            </div>
          </div>
        )}

        {/* Step 4: 创作进行中 / 重写模式 */}
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
