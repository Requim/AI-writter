import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Progress, List, Button, message, Space, Tag, Modal, Input, Typography, Divider } from 'antd'
import { ArrowLeftOutlined, EditOutlined, PlayCircleOutlined, BookOutlined } from '@ant-design/icons'
import { novelApi } from '@/api/novel'
import type { NovelResponse, ProgressResponse, ChapterResponse } from '@/api/novel'
import '@/App.css'

const { Title, Text, Paragraph } = Typography

const novelTypeLabels: Record<string, string> = {
  suspense: '悬疑', sci_fi: '科幻', romance: '言情', fantasy: '奇幻',
  wuxia: '武侠', xianxia: '仙侠', urban: '都市', history: '历史',
  horror: '恐怖', comedy: '喜剧',
}

const NovelProgress = () => {
  const { novelId } = useParams<{ novelId: string }>()
  const navigate = useNavigate()

  const [novel, setNovel] = useState<NovelResponse | null>(null)
  const [progress, setProgress] = useState<ProgressResponse>({
    current_chapter: 0,
    total_chapters: 0,
    percentage: 0,
    status: 'draft'
  })
  const [chapters, setChapters] = useState<ChapterResponse[]>([])
  const [loading, setLoading] = useState(true)

  // 章节查看/编辑
  const [viewModal, setViewModal] = useState(false)
  const [editingChapter, setEditingChapter] = useState<ChapterResponse | null>(null)
  const [chapterContent, setChapterContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [loadingChapter, setLoadingChapter] = useState(false)

  const loadData = async () => {
    if (!novelId) return
    setLoading(true)
    try {
      const [novelData, progressData, chaptersData] = await Promise.all([
        novelApi.getNovel(novelId),
        novelApi.getProgress(novelId),
        novelApi.getChapters(novelId)
      ])
      setNovel(novelData)
      setProgress(progressData)
      setChapters(chaptersData)
    } catch (error: any) {
      if (error?.response?.status === 404 || error?.status === 404) {
        message.warning('该小说不存在或已被删除')
        navigate('/', { replace: true })
      } else {
        message.error('加载数据失败')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [novelId])

  const viewChapter = async (chapter: ChapterResponse) => {
    setLoadingChapter(true)
    setViewModal(true)
    try {
      const chapterData = await novelApi.getChapter(novelId!, chapter.id)
      setEditingChapter(chapter)
      setChapterContent(chapterData.content || '')
    } catch (error) {
      message.error('加载章节失败')
      setViewModal(false)
    } finally {
      setLoadingChapter(false)
    }
  }

  const handleSaveChapter = async () => {
    if (!editingChapter) return
    setSaving(true)
    try {
      await novelApi.updateChapter(novelId!, editingChapter.id, {
        content: chapterContent
      })
      message.success('章节已更新')
      setViewModal(false)
      loadData()
    } catch (error) {
      message.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleContinue = () => {
    navigate(`/novel/${novelId}`)
  }

  const isCompleted = progress.status === 'completed' || novel?.status === 'completed'

  return (
    <div style={{ maxWidth: 900, margin: '40px auto', padding: '0 20px' }}>
      {/* 顶部导航 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>
          返回书架
        </Button>
        {!isCompleted && (
          <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleContinue}>
            继续创作
          </Button>
        )}
      </div>

      {/* 小说信息卡片 */}
      {novel && (
        <Card style={{ marginBottom: 24, borderRadius: 12 }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
            <div style={{
              width: 80, height: 80, borderRadius: 8,
              background: 'linear-gradient(135deg, #667eea, #764ba2)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 36, color: '#fff', flexShrink: 0,
            }}>
              <BookOutlined />
            </div>
            <div style={{ flex: 1 }}>
              <Title level={3} style={{ margin: '0 0 8px' }}>
                {novel.title || '（未命名）'}
              </Title>
              <Space>
                {novel.novel_type && (
                  <Tag color="purple">{novelTypeLabels[novel.novel_type] || novel.novel_type}</Tag>
                )}
                <Tag color={isCompleted ? 'green' : 'blue'}>
                  {isCompleted ? '已完结' : '创作中'}
                </Tag>
              </Space>
              {novel.summary && (
                <Paragraph ellipsis={{ rows: 2 }} style={{ color: '#666', marginTop: 8 }}>
                  {novel.summary}
                </Paragraph>
              )}
            </div>
          </div>

          <Divider style={{ margin: '16px 0' }} />

          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <Progress
              percent={Math.round(progress.percentage || 0)}
              style={{ flex: 1 }}
              strokeColor={isCompleted ? '#52c41a' : '#1677ff'}
            />
            <Text type="secondary" style={{ whiteSpace: 'nowrap', fontSize: 14 }}>
              {progress.current_chapter} / {progress.total_chapters} 章
            </Text>
          </div>
        </Card>
      )}

      {/* 章节目录 */}
      <Card
        title={
          <Space>
            <span>章节目录</span>
            <Tag>{chapters.length} 章</Tag>
          </Space>
        }
        loading={loading}
        style={{ borderRadius: 12 }}
      >
        {chapters.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
            暂无章节，点击「继续创作」开始生成第一章
          </div>
        ) : (
          <List
            dataSource={chapters}
            renderItem={(chapter) => (
              <List.Item
                key={chapter.id}
                style={{
                  padding: '12px 16px',
                  borderRadius: 8,
                  marginBottom: 4,
                  cursor: 'pointer',
                  transition: 'background 0.2s',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = '#f5f5f5')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                onClick={() => viewChapter(chapter)}
                actions={[
                  <Button
                    type="link"
                    icon={<EditOutlined />}
                    onClick={(e) => { e.stopPropagation(); viewChapter(chapter) }}
                  >
                    查看
                  </Button>
                ]}
              >
                <List.Item.Meta
                  avatar={
                    <div style={{
                      width: 36, height: 36, borderRadius: '50%',
                      background: '#f0f5ff', display: 'flex',
                      alignItems: 'center', justifyContent: 'center',
                      fontWeight: 600, color: '#1677ff',
                    }}>
                      {chapter.chapter_index + 1}
                    </div>
                  }
                  title={
                    <Space>
                      <Text strong>第{chapter.chapter_index + 1}章</Text>
                      <Text>{chapter.title}</Text>
                      <Tag
                        color={chapter.status === 'completed' ? 'green' : 'blue'}
                        style={{ fontSize: 12 }}
                      >
                        {chapter.status === 'completed' ? '已完成' : '创作中'}
                      </Tag>
                    </Space>
                  }
                  description={
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {chapter.word_count?.toLocaleString() || 0} 字
                    </Text>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Card>

      {/* 章节内容弹窗 */}
      <Modal
        title={
          editingChapter
            ? `第${editingChapter.chapter_index + 1}章：${editingChapter.title}`
            : '章节内容'
        }
        open={viewModal}
        onCancel={() => setViewModal(false)}
        onOk={handleSaveChapter}
        confirmLoading={saving}
        width={800}
        okText="保存修改"
        cancelText="关闭"
        bodyStyle={{ maxHeight: '60vh', overflow: 'auto' }}
      >
        {loadingChapter ? (
          <div style={{ textAlign: 'center', padding: 40 }}>加载中...</div>
        ) : (
          <>
            {/* 章节元信息 */}
            {editingChapter && (
              <div style={{ marginBottom: 16, padding: '8px 12px', background: '#fafafa', borderRadius: 8 }}>
                <Space size="large">
                  <Text type="secondary">字数：{editingChapter.word_count?.toLocaleString() || 0}</Text>
                  <Tag color={editingChapter.status === 'completed' ? 'green' : 'blue'}>
                    {editingChapter.status === 'completed' ? '已完成' : '创作中'}
                  </Tag>
                </Space>
              </div>
            )}
            <Input.TextArea
              value={chapterContent}
              onChange={(e) => setChapterContent(e.target.value)}
              rows={22}
              style={{ fontSize: 15, lineHeight: 1.8, fontFamily: 'Georgia, "Noto Serif SC", serif' }}
            />
          </>
        )}
      </Modal>
    </div>
  )
}

export default NovelProgress
