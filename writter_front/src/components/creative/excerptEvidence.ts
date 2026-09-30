import type { ChapterDetail } from '@/types/novel'
import type { TextEvidence } from '@/types/creative'

export async function excerptEvidence(chapter: ChapterDetail, quote: string): Promise<TextEvidence> {
  const content = chapter.content || ''
  const offset = content.indexOf(quote)
  if (!quote || offset < 0 || offset !== content.lastIndexOf(quote)) throw new Error('引用必须能在所选章节中唯一定位')
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(content))
  const start = Array.from(content.slice(0, offset)).length
  return {
    chapter_id: chapter.id, chapter_version: chapter.version, chapter_number: chapter.chapter_index + 1,
    content_hash: Array.from(new Uint8Array(hash), (value) => value.toString(16).padStart(2, '0')).join(''),
    start, end: start + Array.from(quote).length, quote,
  }
}
