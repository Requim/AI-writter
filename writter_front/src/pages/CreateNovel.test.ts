import { describe, expect, it } from 'vitest'
import { buildCreationSubmission } from './creationSubmission'

describe('buildCreationSubmission', () => {
  it('passes user-authored fields to both persistence and workflow input', () => {
    const result = buildCreationSubmission({
      novel_type: 'romance',
      title: '  郫西往事  ',
      summary: ' 姚奇伶和吴梓银的青春爱情故事 ',
      core_premise: ' 两位旧友因一封迟到十年的信重逢 ',
      reader_promise: ' 克制的情感拉扯与逐层揭晓的旧事 ',
      content_boundaries: ' 不使用失忆梗 ',
      setting_era: ' 1990 年代末 ',
      setting_region: ' 江南县城 ',
      naming_preference: ' 参考《诗经》，清雅但不生僻 ',
      total_chapters: 36,
      writing_style: ' 幽默诙谐 ',
    })

    expect(result.payload).toEqual({
      novel_type: 'romance',
      title: '郫西往事',
      summary: '姚奇伶和吴梓银的青春爱情故事',
      total_outline: {
        total_chapters: 36,
        writing_style: '幽默诙谐',
        creative_brief: {
          core_premise: '两位旧友因一封迟到十年的信重逢',
          reader_promise: '克制的情感拉扯与逐层揭晓的旧事',
          content_boundaries: '不使用失忆梗',
          setting_context: { era: '1990 年代末', region: '江南县城' },
          naming_preference: '参考《诗经》，清雅但不生僻',
        },
      },
    })
    expect(result.startInput).toEqual({
      novel_type: 'romance',
      title: '郫西往事',
      summary: '姚奇伶和吴梓银的青春爱情故事',
      target_total_chapters: 36,
      requested_writing_style: '幽默诙谐',
      creative_brief: {
        core_premise: '两位旧友因一封迟到十年的信重逢',
        reader_promise: '克制的情感拉扯与逐层揭晓的旧事',
        content_boundaries: '不使用失忆梗',
        setting_context: { era: '1990 年代末', region: '江南县城' },
        naming_preference: '参考《诗经》，清雅但不生僻',
      },
    })
  })

  it('leaves blank optional fields for AI generation', () => {
    const result = buildCreationSubmission({
      novel_type: 'suspense',
      title: '   ',
      summary: '',
      core_premise: ' ',
      reader_promise: '',
      content_boundaries: '   ',
      setting_era: ' ',
      setting_region: '',
      naming_preference: '   ',
      total_chapters: 12,
      writing_style: ' ',
    })

    expect(result.startInput).toEqual({
      novel_type: 'suspense',
      target_total_chapters: 12,
    })
  })
})
