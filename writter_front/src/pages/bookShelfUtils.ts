import type { NovelResponse } from '@/types/novel'

export type ShelfStatusFilter = 'all' | 'writing' | 'draft' | 'completed'

/** 按书名、简介和作品状态筛选书架。 */
export function filterNovels(
  novels: NovelResponse[],
  query: string,
  status: ShelfStatusFilter,
): NovelResponse[] {
  const keyword = query.trim().toLocaleLowerCase('zh-CN')
  return novels.filter((novel) => {
    if (status !== 'all' && novel.status !== status) return false
    if (!keyword) return true
    return `${novel.title || ''}\n${novel.summary || ''}`
      .toLocaleLowerCase('zh-CN')
      .includes(keyword)
  })
}
