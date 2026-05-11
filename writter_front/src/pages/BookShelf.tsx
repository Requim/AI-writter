import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Row, Col, Button, Tag, Progress, Empty, Spin, Typography, Space, Popconfirm, message, Checkbox, Switch, Tooltip } from 'antd'
import { PlusOutlined, BookOutlined, EditOutlined, DeleteOutlined, RobotOutlined } from '@ant-design/icons'
import { novelApi } from '@/api/novel'
import type { NovelResponse } from '@/api/novel'
import { useNovelStore } from '@/stores/novelStore'

const { Title, Text, Paragraph } = Typography

// 小说类型中文映射
const novelTypeLabels: Record<string, string> = {
  suspense: '悬疑',
  sci_fi: '科幻',
  romance: '言情',
  fantasy: '奇幻',
  wuxia: '武侠',
  xianxia: '仙侠',
  urban: '都市',
  history: '历史',
  horror: '恐怖',
  comedy: '喜剧',
}

const BookShelf = () => {
  const navigate = useNavigate()
  const { setCurrentNovel, autoMode, setAutoMode } = useNovelStore()
  const [novels, setNovels] = useState<NovelResponse[]>([])
  const [loading, setLoading] = useState(true)

  // 批量删除模式
  const [batchMode, setBatchMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    loadNovels()
  }, [])

  const loadNovels = async () => {
    setLoading(true)
    try {
      const data = await novelApi.getNovels()
      setNovels(data)
    } catch (error) {
      console.error('Failed to load novels:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleNovelClick = (novel: NovelResponse) => {
    if (batchMode) {
      toggleSelect(novel.id)
      return
    }
    setCurrentNovel(novel.id)
    navigate(`/novel/${novel.id}`)
  }

  const handleCreateNew = () => {
    navigate('/novel/new')
  }

  const handleDelete = async (novelId: string) => {
    try {
      await novelApi.deleteNovel(novelId)
      message.success('删除成功')
      loadNovels()
    } catch (err: any) {
      message.error('删除失败：' + (err?.message || '未知错误'))
    }
  }

  // ====== 批量删除 ======
  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === novels.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(novels.map(n => n.id)))
    }
  }

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return
    setDeleting(true)
    let success = 0
    let fail = 0
    for (const id of selectedIds) {
      try {
        await novelApi.deleteNovel(id)
        success++
      } catch {
        fail++
      }
    }
    setDeleting(false)
    setSelectedIds(new Set())
    setBatchMode(false)
    if (fail === 0) {
      message.success(`成功删除 ${success} 本小说`)
    } else {
      message.warning(`成功 ${success} 本，失败 ${fail} 本`)
    }
    loadNovels()
  }

  const exitBatchMode = () => {
    setBatchMode(false)
    setSelectedIds(new Set())
  }

  const getStatusTag = (status: string) => {
    switch (status) {
      case 'completed':
        return <Tag color="green">已完结</Tag>
      case 'writing':
        return <Tag color="blue">创作中</Tag>
      case 'draft':
        return <Tag color="default">草稿</Tag>
      default:
        return <Tag>{status}</Tag>
    }
  }

  const allSelected = novels.length > 0 && selectedIds.size === novels.length

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '40px 20px' }}>
      {/* 顶部标题栏 */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 32,
        padding: '24px 32px',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        borderRadius: 12,
        color: '#fff',
      }}>
        <div>
          <Title level={2} style={{ color: '#fff', margin: 0 }}>
            <BookOutlined style={{ marginRight: 12 }} />
            我的书架
          </Title>
          <Text style={{ color: 'rgba(255,255,255,0.8)', fontSize: 15 }}>
            AI 智能小说创作助手
          </Text>
        </div>
        <Space size="middle">
          <Space>
            <RobotOutlined style={{ color: 'rgba(255,255,255,0.7)', fontSize: 16 }} />
            <Switch
              checked={autoMode}
              onChange={setAutoMode}
              checkedChildren="自动"
              unCheckedChildren="手动"
              style={{ background: autoMode ? '#52c41a' : undefined }}
            />
          </Space>
          <Button
            type="primary"
            size="large"
            icon={<PlusOutlined />}
            onClick={handleCreateNew}
            style={{
              background: '#fff',
              color: '#667eea',
              border: 'none',
              fontWeight: 600,
            }}
          >
            开始新创作
          </Button>
        </Space>
      </div>

      {/* 批量操作工具栏 */}
      {novels.length > 0 && (
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 16,
          padding: '8px 16px',
          background: batchMode ? '#fff2f0' : '#fafafa',
          borderRadius: 8,
          border: batchMode ? '1px solid #ffccc7' : '1px solid #f0f0f0',
          transition: 'all 0.3s',
        }}>
          <Space>
            {!batchMode ? (
              <Button
                icon={<DeleteOutlined />}
                onClick={() => setBatchMode(true)}
              >
                批量删除
              </Button>
            ) : (
              <>
                <Checkbox
                  checked={allSelected}
                  indeterminate={selectedIds.size > 0 && !allSelected}
                  onChange={toggleSelectAll}
                >
                  全选
                </Checkbox>
                <Text type="secondary" style={{ fontSize: 13 }}>
                  已选 {selectedIds.size} / {novels.length} 本
                </Text>
              </>
            )}
          </Space>
          {batchMode && (
            <Space>
              {selectedIds.size > 0 && (
                <Popconfirm
                  title={`确定删除选中的 ${selectedIds.size} 本小说？`}
                  description="删除后不可恢复"
                  onConfirm={handleBatchDelete}
                  okText="确定删除"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                >
                  <Button danger type="primary" loading={deleting}>
                    删除已选 ({selectedIds.size})
                  </Button>
                </Popconfirm>
              )}
              <Button onClick={exitBatchMode}>取消</Button>
            </Space>
          )}
        </div>
      )}

      {/* 小说列表 */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: 80 }}>
          <Spin size="large" tip="正在加载书架..." />
        </div>
      ) : novels.length === 0 ? (
        <Empty
          description="书架空空如也，开始你的第一部小说吧！"
          style={{ padding: 80 }}
        >
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreateNew}>
            创建小说
          </Button>
        </Empty>
      ) : (
        <Row gutter={[24, 24]}>
          {novels.map((novel) => {
            const isSelected = selectedIds.has(novel.id)
            return (
            <Col key={novel.id} xs={24} sm={12} md={8} lg={6}>
              <Card
                hoverable={!batchMode}
                onClick={() => handleNovelClick(novel)}
                style={{
                  height: '100%',
                  borderRadius: 12,
                  overflow: 'hidden',
                  border: isSelected ? '2px solid #ff4d4f' : '1px solid #f0f0f0',
                  transition: 'all 0.2s',
                  cursor: batchMode ? 'pointer' : undefined,
                  position: 'relative',
                }}
                bodyStyle={{ padding: '20px 24px 16px' }}
                cover={
                  <div style={{ position: 'relative' }}>
                    <div style={{
                      height: 120,
                      background: novel.status === 'completed'
                        ? 'linear-gradient(135deg, #a8edea 0%, #fed6e3 100%)'
                        : novel.status === 'writing'
                          ? 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
                          : 'linear-gradient(135deg, #e0e0e0 0%, #f5f5f5 100%)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 48,
                      color: '#fff',
                    }}>
                      <BookOutlined />
                    </div>
                    {/* 批量模式勾选框 */}
                    {batchMode && (
                      <div
                        style={{
                          position: 'absolute',
                          top: 8,
                          left: 8,
                          zIndex: 2,
                        }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <Checkbox
                          checked={isSelected}
                          onChange={() => toggleSelect(novel.id)}
                          style={{
                            background: 'rgba(255,255,255,0.9)',
                            padding: '4px 6px',
                            borderRadius: 4,
                          }}
                        />
                      </div>
                    )}
                    {/* 选中蒙层 */}
                    {isSelected && (
                      <div style={{
                        position: 'absolute',
                        top: 0, left: 0, right: 0, bottom: 0,
                        background: 'rgba(255,77,79,0.15)',
                        pointerEvents: 'none',
                      }} />
                    )}
                  </div>
                }
              >
                <div style={{ marginBottom: 8 }}>
                  <Title level={5} ellipsis style={{ margin: 0 }}>
                    {novel.title || '（未命名）'}
                  </Title>
                  <Space style={{ marginTop: 4 }}>
                    {novel.novel_type && (
                      <Tag color="purple">{novelTypeLabels[novel.novel_type] || novel.novel_type}</Tag>
                    )}
                    {getStatusTag(novel.status)}
                  </Space>
                </div>

                {novel.summary && (
                  <Tooltip title={novel.summary} mouseEnterDelay={0.3}>
                    <Paragraph
                      ellipsis={{ rows: 2 }}
                      style={{ color: '#666', fontSize: 13, marginBottom: 12 }}
                    >
                      {novel.summary}
                    </Paragraph>
                  </Tooltip>
                )}

                <Progress
                  percent={Math.round(novel.progress_percentage || 0)}
                  size="small"
                  status={novel.status === 'completed' ? 'success' : 'active'}
                  style={{ marginBottom: 12 }}
                />

                {/* 正常模式：操作按钮 */}
                {!batchMode && (
                  <Space.Compact block style={{ width: '100%' }}>
                    <Button
                      type="primary"
                      icon={<EditOutlined />}
                      onClick={(e) => {
                        e.stopPropagation()
                        handleNovelClick(novel)
                      }}
                      style={{ flex: 1 }}
                    >
                      {novel.status === 'completed' ? '查看' : '继续创作'}
                    </Button>
                    <Popconfirm
                      title="确定删除这本小说？"
                      description="删除后不可恢复"
                      onConfirm={(e) => {
                        e?.stopPropagation()
                        handleDelete(novel.id)
                      }}
                      onCancel={(e) => e?.stopPropagation()}
                      okText="确定删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                    >
                      <Button
                        danger
                        icon={<DeleteOutlined />}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </Popconfirm>
                  </Space.Compact>
                )}
              </Card>
            </Col>
          )})}
        </Row>
      )}
    </div>
  )
}

export default BookShelf
