import { App, Button, Empty, Input, Progress, Segmented, Skeleton } from 'antd'
import { CheckOutlined, DeleteOutlined, EditOutlined, PlusOutlined, SearchOutlined, SelectOutlined } from '@ant-design/icons'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { novelApi } from '@/api/novel'
import { useNovelStore } from '@/stores/novelStore'
import type { NovelResponse } from '@/types/novel'
import { currentTenant } from '@/stores/authStore'
import { filterNovels, type ShelfStatusFilter } from './bookShelfUtils'

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
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<ShelfStatusFilter>('all')
  const canDelete = ['owner', 'admin'].includes(currentTenant()?.role || '')
  const filteredNovels = useMemo(
    () => filterNovels(novels, query, statusFilter),
    [novels, query, statusFilter],
  )

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
        const results = await Promise.allSettled(selected.map((id) => novelApi.remove(id)))
        const failedIds = selected.filter((_, index) => results[index].status === 'rejected')
        await load()
        if (failedIds.length > 0) {
          setSelected(failedIds)
          message.error(`${failedIds.length} 部作品删除失败，已保留选择，请重试`)
          return
        }
        setSelected([])
        setOrganizing(false)
        message.success('已从书架删除所选作品')
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
            <label>新任务默认模式</label>
            <Segmented
              value={autoMode ? 'auto' : 'manual'}
              onChange={(value) => setAutoMode(value === 'auto')}
              options={[{ label: '手动审阅', value: 'manual' }, { label: '自动创作', value: 'auto' }]}
            />
          </div>
        </section>

        <div className="shelf-toolbar">
          <div className="shelf-filters">
            <Input
              allowClear
              aria-label="搜索书架"
              prefix={<SearchOutlined />}
              placeholder="搜索书名或简介"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value)
                setSelected([])
              }}
            />
            <Segmented
              value={statusFilter}
              onChange={(value) => {
                setStatusFilter(value as ShelfStatusFilter)
                setSelected([])
              }}
              options={[
                { label: '全部', value: 'all' },
                { label: '创作中', value: 'writing' },
                { label: '草稿', value: 'draft' },
                { label: '已完稿', value: 'completed' },
              ]}
            />
            <span className="shelf-result-count">{filteredNovels.length} / {novels.length} 部</span>
          </div>
          <div className="shelf-toolbar-actions">
            {organizing && filteredNovels.length > 0 && (
              <Button
                icon={<CheckOutlined />}
                onClick={() => {
                  const visibleIds = filteredNovels.map((novel) => novel.id)
                  const allSelected = visibleIds.every((id) => selected.includes(id))
                  setSelected(allSelected ? [] : visibleIds)
                }}
              >
                {filteredNovels.every((novel) => selected.includes(novel.id)) ? '取消全选' : '全选结果'}
              </Button>
            )}
            {organizing && selected.length > 0 && (
              <Button danger icon={<DeleteOutlined />} onClick={removeSelected}>删除已选（{selected.length}）</Button>
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
        ) : filteredNovels.length === 0 ? (
          <Empty className="empty-shelf" description="没有符合条件的作品">
            <Button onClick={() => { setQuery(''); setStatusFilter('all') }}>清除筛选</Button>
          </Empty>
        ) : (
          <section className="book-grid" aria-label="小说列表">
            {filteredNovels.map((novel, index) => {
              const checked = selected.includes(novel.id)
              const progress = Math.round(novel.progress_percentage || 0)
              return (
                <article
                  className={`book-item cover-${index % 5} ${checked ? 'selected' : ''}`}
                  key={novel.id}
                  role={organizing ? 'checkbox' : 'button'}
                  aria-checked={organizing ? checked : undefined}
                  aria-label={organizing ? `选择《${novel.title || '未命名作品'}》` : `打开《${novel.title || '未命名作品'}》`}
                  tabIndex={0}
                  onClick={() => organizing
                    ? setSelected((ids) => checked ? ids.filter((id) => id !== novel.id) : [...ids, novel.id])
                    : navigate(`/novels/${novel.id}`)}
                  onKeyDown={(event) => {
                    if (!['Enter', ' '].includes(event.key)) return
                    event.preventDefault()
                    if (organizing) {
                      setSelected((ids) => checked ? ids.filter((id) => id !== novel.id) : [...ids, novel.id])
                    } else {
                      navigate(`/novels/${novel.id}`)
                    }
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
                    <div className="book-status-row">
                      <span>{novel.status === 'completed' ? '已完稿' : novel.status === 'writing' ? '创作中' : '草稿'}</span>
                      <small>{progress}%</small>
                    </div>
                    <h2>{novel.title || '未命名作品'}</h2>
                    <p>{novel.summary || '这部作品还没有简介。'}</p>
                    <Progress percent={progress} showInfo={false} strokeColor="#176b5b" />
                    <span className="book-open-action">
                      <EditOutlined /> {novel.status === 'completed' ? '查看稿件' : progress > 0 ? '继续创作' : '打开稿件'}
                    </span>
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
