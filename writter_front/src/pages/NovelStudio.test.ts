import { describe, expect, it } from 'vitest'

import { autoResumeValue, hasChapterChanges, rewindImpactText, shouldAutoResume } from './novelStudioUtils'
import type { InterruptInfo } from '@/types/novel'

const interrupt: InterruptInfo = {
  action: 'review_reflection_issues',
  chapter_number: 3,
  message: '第3章质量审读完成',
}

describe('shouldAutoResume', () => {
  it('does not consume a historical interrupt just because auto mode is persisted', () => {
    expect(shouldAutoResume(true, false, interrupt, undefined)).toBe(false)
  })

  it('continues a current auto run once for each interrupt', () => {
    expect(shouldAutoResume(true, true, interrupt, undefined)).toBe(true)
    expect(shouldAutoResume(true, true, interrupt, 'review_reflection_issues-3')).toBe(false)
  })

  it('stops automatic resume when the server requires human quality review', () => {
    expect(shouldAutoResume(true, true, {
      action: 'quality_gate_exhausted',
      chapter_number: 3,
    }, undefined)).toBe(false)
    expect(shouldAutoResume(true, true, {
      action: 'quality_gate_human_review',
      chapter_number: 3,
    }, undefined)).toBe(false)
  })
})

describe('autoResumeValue', () => {
  it('accepts a generated creative brief in automatic mode', () => {
    expect(autoResumeValue({ action: 'review_or_modify_creative_brief' }, 'suspense')).toBe('accept')
  })
})

describe('chapter editing safeguards', () => {
  const chapter = {
    id: 'chapter-2',
    chapter_index: 1,
    title: '雨站重逢',
    content: '已保存正文',
    word_count: 5,
    status: 'completed',
    version: 2,
    updated_at: '2026-07-31T00:00:00Z',
  }

  it('detects only changes that have not been saved', () => {
    expect(hasChapterChanges(chapter, chapter.title, chapter.content)).toBe(false)
    expect(hasChapterChanges(chapter, '新的标题', chapter.content)).toBe(true)
    expect(hasChapterChanges(chapter, chapter.title, '新的正文')).toBe(true)
  })

  it('states the exact destructive rewind range', () => {
    const chapters = [chapter, { ...chapter, id: 'chapter-3', chapter_index: 2 }]
    expect(rewindImpactText(chapter, chapters)).toContain('第 2 至第 3 章，共 2 章')
  })
})
