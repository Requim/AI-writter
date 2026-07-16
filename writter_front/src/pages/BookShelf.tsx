import { App, Button, Empty, Progress, Segmented, Skeleton } from 'antd'
import { CheckOutlined, DeleteOutlined, EditOutlined, PlusOutlined, SelectOutlined } from '@ant-design/icons'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { novelApi } from '@/api/novel'
import { useNovelStore } from '@/stores/novelStore'
import type { NovelResponse } from '@/types/novel'
import { currentTenant } from '@/stores/authStore'

const typeLabels: Record<string, string> = {
  suspense: '悬疑', sci_fi: '科幻', romance: '言情', fantasy: '奇幻',
  wuxia: '武侠', xianxia: '仙侠', urban: '都市', history: '历史',
  horror: '惊悚', comedy: '喜剧',
}

export default function BookShelf() {
  const navigate = useNavigate()
  const { message, modal } = App.useApp()
  const autoMode = useNovelStore((state) => state.autoMode)
  const setAutoMode = useNovelStore((state) => state.setAutoMode)
  const [novels, setNovels] = useState<NovelResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [organizing, setOrganizing] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const canDelete = ['owner', 'admin'].includes(currentTenant()?.role || '')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setNovels(await novelApi.list())
    } catch {
      message.error('无法读取书架，请确认后端服务已启动')
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    queueMicrotask(() => void load())
  }, [load])

  const removeSelected = () => {
    modal.confirm({
      title: `删除 ${selected.length} 部作品？`,
      content: '章节、记忆和创作进度将一并删除，操作不可撤销。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        await Promise.all(selected.map((id) => novelApi.remove(id)))
        setSelected([])
        setOrganizing(false)
        await load()
      },
    })
  }

  return (
    <AppShell>
      <div className="shelf-page page-enter">
        <section className="shelf-intro">
          <div>
            <span className="eyebrow">私人小说编辑部</span>
            <h1>我的书架</h1>
            <p>从设定、章节生成到质量审读，稿件都在同一张创作桌上推进。</p>
          </div>
          <div className="shelf-controls">
            <label>工作模式</label>
            <Segmented
              value={autoMode ? 'auto' : 'manual'}
              onChange={(value) => setAutoMode(value === 'auto')}
              options={[{ label: '手动审阅', value: 'manual' }, { label: '自动创作', value: 'auto' }]}
            />
          </div>
        </section>

        <div className="shelf-toolbar">
          <span>{novels.length} 部作品</span>
          <div>
            {organizing && selected.length > 0 && (
              <Button danger icon={<DeleteOutlined />} onClick={removeSelected}>删除已选</Button>
            )}
            {canDelete && (
              <Button
                icon={<SelectOutlined />}
                onClick={() => { setOrganizing((value) => !value); setSelected([]) }}
              >
                {organizing ? '完成整理' : '整理书架'}
              </Button>
            )}
            <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/novels/new')}>
              新建作品
            </Button>
          </div>
        </div>

        {loading ? (
          <div className="book-grid"><Skeleton active /><Skeleton active /><Skeleton active /></div>
        ) : novels.length === 0 ? (
          <Empty className="empty-shelf" description="还没有稿件">
            <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/novels/new')}>
              开始第一部作品
            </Button>
          </Empty>
        ) : (
          <section className="book-grid" aria-label="小说列表">
            {novels.map((novel, index) => {
              const checked = selected.includes(novel.id)
              return (
                <article
                  className={`book-item cover-${index % 5} ${checked ? 'selected' : ''}`}
                  key={novel.id}
                  role={organizing ? 'checkbox' : undefined}
                  aria-checked={organizing ? checked : undefined}
                  tabIndex={organizing ? 0 : undefined}
                  onClick={() => organizing
                    ? setSelected((ids) => checked ? ids.filter((id) => id !== novel.id) : [...ids, novel.id])
                    : navigate(`/novels/${novel.id}`)}
                  onKeyDown={(event) => {
                    if (!organizing || !['Enter', ' '].includes(event.key)) return
                    event.preventDefault()
                    setSelected((ids) => checked ? ids.filter((id) => id !== novel.id) : [...ids, novel.id])
                  }}
                >
                  <div className="book-cover" aria-hidden="true">
                    {organizing && (
                      <span className={`selection-mark ${checked ? 'checked' : ''}`}>
                        {checked && <CheckOutlined />}
                      </span>
                    )}
                    <span>{typeLabels[novel.novel_type] || novel.novel_type}</span>
                    <strong>{novel.title || '未命名作品'}</strong>
                    <small>墨间 · 创作稿</small>
                  </div>
                  <div className="book-meta">
                    <div><span>{novel.status === 'completed' ? '已完稿' : novel.status === 'writing' ? '创作中' : '草稿'}</span></div>
                    <h2>{novel.title || '未命名作品'}</h2>
                    <p>{novel.summary || '这部作品还没有简介。'}</p>
                    <Progress percent={Math.round(novel.progress_percentage || 0)} showInfo={false} strokeColor="#176b5b" />
                    <Button type="text" icon={<EditOutlined />}>打开稿件</Button>
                  </div>
                </article>
              )
            })}
          </section>
        )}
      </div>
    </AppShell>
  )
}
