import { describe, expect, it } from 'vitest'

import { filterNovels } from './bookShelfUtils'
import type { NovelResponse } from '@/types/novel'

const novels: NovelResponse[] = [
  {
    id: 'novel-1',
    novel_type: 'suspense',
    title: '雨夜来客',
    summary: '一桩发生在车站的旧案',
    status: 'writing',
  },
  {
    id: 'novel-2',
    novel_type: 'romance',
    title: '春日来信',
    summary: '多年后的重逢',
    status: 'completed',
  },
]

describe('filterNovels', () => {
  it('matches title or summary without surrounding spaces', () => {
    expect(filterNovels(novels, ' 车站 ', 'all').map((novel) => novel.id)).toEqual(['novel-1'])
    expect(filterNovels(novels, '春日', 'all').map((novel) => novel.id)).toEqual(['novel-2'])
  })

  it('combines status and text filters', () => {
    expect(filterNovels(novels, '来', 'completed').map((novel) => novel.id)).toEqual(['novel-2'])
    expect(filterNovels(novels, '', 'draft')).toEqual([])
  })
})
