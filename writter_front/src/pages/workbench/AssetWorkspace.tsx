import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CopyOutlined,
  DatabaseOutlined,
  EditOutlined,
  FileAddOutlined,
  FileSearchOutlined,
  HistoryOutlined,
  MoreOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Checkbox,
  Drawer,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Radio,
  Select,
  Tag,
  Tooltip,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { novelApi } from '@/api/novel'
import { workbenchApi, workbenchErrorMessage } from '@/api/workbench'
import type { ChapterSummary, NovelResponse } from '@/types/novel'
import type {
  AdoptionAcceptance,
  WorkbenchAsset,
  WorkbenchAssetKind,
  WorkbenchSource,
} from '@/types/workbench'

export interface AssetDraft {
  content: string
  sourceMessageId?: string
  title?: string
  kind?: WorkbenchAssetKind
}

interface AssetFormValues {
  title: string
  kind: WorkbenchAssetKind
  content: string
}

interface AdoptionFormValues {
  acceptance: AdoptionAcceptance
  target: 'append' | 'existing'
  chapter_number?: number
  target_chapter_id?: string
}

const kindOptions: Array<{ value: WorkbenchAssetKind; label: string }> = [
  { value: 'idea', label: '灵感' },
  { value: 'world', label: '世界设定' },
  { value: 'character', label: '角色' },
  { value: 'outline', label: '大纲' },
  { value: 'chapter', label: '章节草稿' },
  { value: 'reference', label: '参考资料' },
]

function kindLabel(kind: WorkbenchAssetKind): string {
  return kindOptions.find((item) => item.value === kind)?.label || kind
}

function reviewLabel(asset: WorkbenchAsset): string {
  const gate = asset.review?.gate
  if (gate && typeof gate === 'object') {
    const decision = (gate as { decision?: string }).decision
    if (decision === 'pass') return '已通过'
    if (decision) return '有审阅问题'
  }
  return asset.review ? '已审阅' : '未审阅'
}

function defaultAcceptance(asset?: WorkbenchAsset): AdoptionAcceptance {
  if (!asset?.review) return 'unreviewed'
  const gate = asset.review.gate
  if (gate && typeof gate === 'object' && (gate as { decision?: string }).decision === 'pass') return 'reviewed'
  return 'with_issues'
}

function AssetEditor({ novelId, draft, editing, onClose, onSaved }: {
  novelId: string
  draft?: AssetDraft
  editing?: WorkbenchAsset
  onClose: () => void
  onSaved: (asset: WorkbenchAsset) => void
}) {
  const { message } = App.useApp()
  const [form] = Form.useForm<AssetFormValues>()
  const [saving, setSaving] = useState(false)
  const open = Boolean(draft || editing)
  useEffect(() => {
    if (!open) return
    form.setFieldsValue(editing ? {
      title: editing.title, kind: editing.kind, content: editing.content,
    } : {
      title: draft?.title || '', kind: draft?.kind || 'idea', content: draft?.content || '',
    })
  }, [draft, editing, form, open])
  const submit = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      const asset = editing
        ? await workbenchApi.updateAsset(novelId, editing.id, { ...values, expected_version: editing.version })
        : await workbenchApi.createAsset(novelId, {
          ...values,
          ...(draft?.sourceMessageId ? { source_message_id: draft.sourceMessageId } : {}),
        })
      onSaved(asset)
      onClose()
      message.success(editing ? '资产已更新' : '资产已保存')
    } catch (error) {
      message.error(workbenchErrorMessage(error))
    } finally {
      setSaving(false)
    }
  }
  return <Modal title={editing ? '编辑资产' : '保存为资产'} open={open} onCancel={onClose}
    onOk={() => void submit()} confirmLoading={saving} okText="保存" destroyOnHidden>
    <Form form={form} layout="vertical" requiredMark={false}>
      <Form.Item name="title" label="名称" rules={[{ required: true, message: '请填写资产名称' }]}>
        <Input maxLength={100} />
      </Form.Item>
      <Form.Item name="kind" label="类型" rules={[{ required: true }]}><Select options={kindOptions} /></Form.Item>
      <Form.Item name="content" label="内容" rules={[{ required: true, message: '资产内容不能为空' }]}>
        <Input.TextArea rows={12} />
      </Form.Item>
    </Form>
  </Modal>
}

function AdoptionDialog({ novelId, asset, chapters, onClose, onAdopted }: {
  novelId: string
  asset?: WorkbenchAsset
  chapters: ChapterSummary[]
  onClose: () => void
  onAdopted: () => void
}) {
  const { message } = App.useApp()
  const [form] = Form.useForm<AdoptionFormValues>()
  const target = Form.useWatch('target', form) || 'append'
  const [saving, setSaving] = useState(false)
  const submit = async () => {
    if (!asset) return
    const values = await form.validateFields()
    const selected = chapters.find((chapter) => chapter.id === values.target_chapter_id)
    setSaving(true)
    try {
      await workbenchApi.adoptAsset(novelId, asset.id, {
        expected_version: asset.version,
        acceptance: values.acceptance,
        ...(values.target === 'existing' && selected ? {
          target_chapter_id: selected.id,
          expected_chapter_version: selected.version,
        } : { chapter_index: Math.max(0, (values.chapter_number ?? chapters.length + 1) - 1) }),
      })
      message.success('章节草稿已采用')
      onAdopted()
      onClose()
    } catch (error) {
      message.error(workbenchErrorMessage(error))
    } finally {
      setSaving(false)
    }
  }
  return <Modal title="采用章节草稿" open={Boolean(asset)} onCancel={onClose} onOk={() => void submit()}
    okText="确认采用" confirmLoading={saving} destroyOnHidden>
    <Alert type="warning" showIcon title="采用后将写入正式章节，并更新作品进度与记忆。" />
    <Form form={form} layout="vertical" initialValues={{
      acceptance: defaultAcceptance(asset), target: 'append', chapter_number: chapters.length + 1,
    }}>
      <Form.Item name="acceptance" label="审阅结论" rules={[{ required: true }]}>
        <Select options={[
          { value: 'reviewed', label: '已审阅通过' },
          { value: 'with_issues', label: '带问题采用' },
          { value: 'unreviewed', label: '未经审阅采用' },
        ]} />
      </Form.Item>
      <Form.Item name="target" label="采用位置"><Radio.Group options={[
        { value: 'append', label: '追加为新章节' }, { value: 'existing', label: '替换现有章节' },
      ]} /></Form.Item>
      {target === 'existing' ? <Form.Item name="target_chapter_id" label="目标章节"
        rules={[{ required: true, message: '请选择目标章节' }]}>
        <Select options={chapters.map((chapter) => ({
          value: chapter.id, label: `第 ${chapter.chapter_index + 1} 章 · ${chapter.title}`,
        }))} />
      </Form.Item> : <Form.Item name="chapter_number" label="章节序号"
        rules={[{ required: true, message: '请填写章节序号' }]}>
        <InputNumber min={1} max={Math.max(chapters.length + 101, 101)} />
      </Form.Item>}
    </Form>
  </Modal>
}

function SourceDrawer({ sources, available, open, onClose }: { sources: WorkbenchSource[]; available: boolean; open: boolean; onClose: () => void }) {
  return <Drawer title="检索来源" open={open} onClose={onClose} size="large">
    {!available && <Alert type="warning" showIcon title="关键词检索暂不可用，固定设定仍会继续参与创作。" />}
    {sources.length ? <List dataSource={sources} renderItem={(source) => <List.Item>
      <article className="source-hit">
        <header><strong>{source.title}</strong><Tag>v{source.version}</Tag><span>{source.start}-{source.end}</span></header>
        <p>{source.text}</p><small>{source.source_type} · 匹配度 {source.score.toFixed(3)}</small>
      </article>
    </List.Item>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配来源" />}
  </Drawer>
}

function ReviewDrawer({ asset, onClose }: { asset?: WorkbenchAsset; onClose: () => void }) {
  const review = asset?.review
  const decision = review?.gate.decision === 'pass' ? '通过' : review?.gate.decision || '待处理'
  return <Drawer title="章节审阅结果" open={Boolean(asset)} onClose={onClose} size="large">
    {review ? <div className="asset-review-result">
      <header><div><span>审阅结论</span><strong>{decision}</strong></div>
        <div><span>质量分</span><strong>{review.gate.score ?? '—'}</strong></div>
        <div><span>资产版本</span><strong>v{review.asset_version}</strong></div></header>
      <section><h3>审阅问题</h3>{review.issues.length ? review.issues.map((issue, index) => <article key={index}>
        <div><Tag color={issue.severity === 'high' ? 'error' : issue.severity === 'medium' ? 'warning' : 'default'}>{issue.severity || 'issue'}</Tag>
          <strong>{issue.description || '未命名问题'}</strong></div>
        {issue.evidence && <p>{issue.evidence}</p>}{issue.suggestion && <small>{issue.suggestion}</small>}
      </article>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有发现问题" />}</section>
    </div> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无审阅结果" />}
  </Drawer>
}

export function AssetWorkspace({ novelId, assets, legacySources, chapters, selectedIds, draft, onDraftConsumed, onSelectionChange, onChanged }: {
  novelId: string
  assets: WorkbenchAsset[]
  legacySources: WorkbenchSource[]
  chapters: ChapterSummary[]
  selectedIds: string[]
  draft?: AssetDraft
  onDraftConsumed: () => void
  onSelectionChange: (ids: string[]) => void
  onChanged: () => void
}) {
  const { message } = App.useApp()
  const [editorDraft, setEditorDraft] = useState<AssetDraft>()
  const [editing, setEditing] = useState<WorkbenchAsset>()
  const [history, setHistory] = useState<WorkbenchAsset[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [copying, setCopying] = useState<WorkbenchAsset>()
  const [novels, setNovels] = useState<NovelResponse[]>([])
  const [copyTarget, setCopyTarget] = useState<string>()
  const [adopting, setAdopting] = useState<WorkbenchAsset>()
  const [reviewDetails, setReviewDetails] = useState<WorkbenchAsset>()
  const [sources, setSources] = useState<WorkbenchSource[]>([])
  const [sourceOpen, setSourceOpen] = useState(false)
  const [searchAvailable, setSearchAvailable] = useState(true)
  const [searching, setSearching] = useState(false)
  const [reviewingId, setReviewingId] = useState<string>()

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds])
  const toggle = (assetId: string, checked: boolean) => onSelectionChange(
    checked ? [...selectedIds, assetId] : selectedIds.filter((id) => id !== assetId),
  )
  const openHistory = async (asset: WorkbenchAsset) => {
    setHistoryOpen(true)
    try { setHistory(await workbenchApi.assetVersions(novelId, asset.id)) }
    catch (error) { message.error(workbenchErrorMessage(error)) }
  }
  const openCopy = async (asset: WorkbenchAsset) => {
    setCopying(asset)
    try { setNovels((await novelApi.list()).filter((novel) => novel.id !== novelId)) }
    catch { message.error('作品列表读取失败') }
  }
  const copy = async () => {
    if (!copying || !copyTarget) return
    try {
      await workbenchApi.copyAsset(novelId, copying.id, {
        target_novel_id: copyTarget, expected_version: copying.version,
      })
      message.success('资产副本已保存到目标作品')
      setCopying(undefined)
    } catch (error) { message.error(workbenchErrorMessage(error)) }
  }
  const review = async (asset: WorkbenchAsset) => {
    setReviewingId(asset.id)
    try { const value = await workbenchApi.reviewAsset(novelId, asset.id, asset.version); setReviewDetails(value); message.success('章节草稿已审阅'); onChanged() }
    catch (error) { message.error(workbenchErrorMessage(error)) }
    finally { setReviewingId(undefined) }
  }
  const search = async (query: string) => {
    if (!query.trim()) return
    setSearching(true)
    try { const result = await workbenchApi.search(novelId, query.trim()); setSources(result.hits); setSearchAvailable(result.available); setSourceOpen(true) }
    catch (error) { message.error(workbenchErrorMessage(error)) }
    finally { setSearching(false) }
  }
  const reindex = async () => {
    try { await workbenchApi.reindex(novelId); message.success('检索索引已更新') }
    catch (error) { message.error(workbenchErrorMessage(error)) }
  }
  return <>
    <aside className="workbench-assets" aria-label="作品资产">
      <header className="pane-heading"><div><span>ASSETS</span><h2>作品资产</h2></div>
        <div className="asset-header-actions">
          <Tooltip title="重建检索索引"><Button aria-label="重建检索索引" icon={<ReloadOutlined />} onClick={() => void reindex()} /></Tooltip>
          <Tooltip title="新建资产"><Button aria-label="新建资产" icon={<FileAddOutlined />} onClick={() => setEditorDraft({ content: '' })} /></Tooltip>
        </div>
      </header>
      <Input.Search aria-label="检索来源" placeholder="检索设定与已采用章节" enterButton={<FileSearchOutlined />}
        loading={searching} onSearch={(value) => void search(value)} />
      <div className="asset-list" aria-live="polite">
        {assets.length ? assets.map((asset) => <article className="asset-row" key={asset.id}>
          <Checkbox aria-label={`引用资产 ${asset.title}`} checked={selectedSet.has(asset.id)}
            onChange={(event) => toggle(asset.id, event.target.checked)} />
          <div className="asset-copy"><header><strong>{asset.title}</strong><Tag>{kindLabel(asset.kind)}</Tag></header>
            <p>{asset.content}</p><small>v{asset.version} · {reviewLabel(asset)}</small></div>
          <Dropdown trigger={['click']} menu={{ items: [
            { key: 'edit', icon: <EditOutlined />, label: '编辑', onClick: () => setEditing(asset) },
            { key: 'history', icon: <HistoryOutlined />, label: '版本历史', onClick: () => void openHistory(asset) },
            { key: 'copy', icon: <CopyOutlined />, label: '复制到其他作品', onClick: () => void openCopy(asset) },
          ] }}><Button type="text" aria-label={`管理资产 ${asset.title}`} icon={<MoreOutlined />} /></Dropdown>
          {asset.kind === 'chapter' && <div className="asset-chapter-actions">
            {asset.review && <Button size="small" aria-label="查看审阅结果" onClick={() => setReviewDetails(asset)}>审阅结果</Button>}
            <Button size="small" aria-label="审阅章节草稿" loading={reviewingId === asset.id} disabled={Boolean(reviewingId)}
              icon={<SafetyCertificateOutlined />} onClick={() => void review(asset)}>审阅</Button>
            <Button size="small" type="primary" aria-label="采用为章节" icon={<CheckCircleOutlined />} onClick={() => setAdopting(asset)}>采用为章节</Button>
          </div>}
        </article>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无资产" />}
        {legacySources.length > 0 && <section className="legacy-sources" aria-label="原始设定">
          <header><DatabaseOutlined /><strong>原始设定</strong><Tag>只读</Tag></header>
          {legacySources.map((source) => <article key={source.source_id}>
            <div><strong>{source.title}</strong><p>{source.text}</p></div>
            <Button size="small" onClick={() => setEditorDraft({
              title: source.title, content: source.text,
              kind: source.title.includes('角色') ? 'character' : source.title.includes('大纲') ? 'outline' : 'world',
            })}>另存为资产</Button>
          </article>)}
        </section>}
      </div>
    </aside>
    <AssetEditor novelId={novelId} draft={editorDraft || draft} editing={editing}
      onClose={() => { setEditorDraft(undefined); setEditing(undefined); if (draft) onDraftConsumed() }} onSaved={onChanged} />
    <Drawer title="资产版本历史" open={historyOpen} onClose={() => setHistoryOpen(false)} size="large">
      <List dataSource={history} renderItem={(version) => <List.Item><article className="asset-version">
        <header><ClockCircleOutlined /><strong>v{version.version}</strong><span>{version.title}</span></header><p>{version.content}</p>
      </article></List.Item>} />
    </Drawer>
    <Modal title="复制到其他作品" open={Boolean(copying)} onCancel={() => setCopying(undefined)} onOk={() => void copy()}
      okText="复制" okButtonProps={{ disabled: !copyTarget }} destroyOnHidden>
      <Select aria-label="目标作品" value={copyTarget} onChange={setCopyTarget} placeholder="选择目标作品" style={{ width: '100%' }}
        options={novels.map((novel) => ({ value: novel.id, label: novel.title || '未命名作品' }))} />
      {!novels.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有其他作品" />}
    </Modal>
    <AdoptionDialog novelId={novelId} asset={adopting} chapters={chapters} onClose={() => setAdopting(undefined)} onAdopted={onChanged} />
    <ReviewDrawer asset={reviewDetails} onClose={() => setReviewDetails(undefined)} />
    <SourceDrawer sources={sources} available={searchAvailable} open={sourceOpen} onClose={() => setSourceOpen(false)} />
  </>
}
