import type { ChapterDetail, ChapterSummary, InterruptInfo } from '@/types/novel'

/** 返回自动模式处理当前人工确认时应提交的值。 */
export function autoResumeValue(interrupt: InterruptInfo, novelType: string): unknown {
  switch (interrupt.action) {
    case 'require_novel_type': return novelType
    case 'review_or_modify_creative_brief': return 'accept'
    case 'confirm_or_provide_title': return interrupt.ai_suggestions?.[0] || '未命名小说'
    case 'ready_for_next_chapter': return 'next'
    case 'review_reflection_issues': return 'revise'
    default: return 'accept'
  }
}

/** 返回用于阻止同一中断被重复提交的稳定键。 */
export function interruptKey(interrupt: InterruptInfo): string {
  return `${interrupt.action}-${interrupt.chapter_number ?? ''}`
}

/** 判断当前中断是否属于用户本次明确启动的自动创作。 */
export function shouldAutoResume(
  autoMode: boolean,
  autoRunActive: boolean,
  interrupt: InterruptInfo | undefined,
  lastInterruptKey: string | undefined,
): boolean {
  if (!autoMode || !autoRunActive || !interrupt) return false
  if (['quality_gate_exhausted', 'quality_gate_human_review'].includes(interrupt.action)) return false
  return interruptKey(interrupt) !== lastInterruptKey
}

/** 判断编辑器内容是否偏离当前已保存章节。 */
export function hasChapterChanges(
  chapter: ChapterDetail | undefined,
  title: string,
  content: string,
): boolean {
  return Boolean(chapter && (title !== chapter.title || content !== chapter.content))
}

/** 生成人可核对的章节回退影响说明。 */
export function rewindImpactText(chapter: ChapterDetail, chapters: ChapterSummary[]): string {
  const affected = chapters.filter((item) => item.chapter_index >= chapter.chapter_index)
  const firstNumber = chapter.chapter_index + 1
  const lastNumber = affected.at(-1)?.chapter_index ?? chapter.chapter_index
  const range = lastNumber + 1 === firstNumber
    ? `第 ${firstNumber} 章`
    : `第 ${firstNumber} 至第 ${lastNumber + 1} 章`
  return `将永久删除${range}，共 ${affected.length || 1} 章。创作进度和连续性记忆也会同步回退。`
}
