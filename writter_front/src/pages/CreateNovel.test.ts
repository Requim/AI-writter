import { describe, expect, it } from 'vitest'
import { buildCreationSubmission } from './creationSubmission'

describe('buildCreationSubmission', () => {
  it('passes user-authored fields to both persistence and workflow input', () => {
    const result = buildCreationSubmission({
      novel_type: 'romance',
      title: '  郫西往事  ',
      summary: ' 姚奇伶和吴梓银的青春爱情故事 ',
      total_chapters: 36,
      writing_style: ' 幽默诙谐 ',
    })

    expect(result.payload).toEqual({
      novel_type: 'romance',
      title: '郫西往事',
      summary: '姚奇伶和吴梓银的青春爱情故事',
      total_outline: { total_chapters: 36, writing_style: '幽默诙谐' },
    })
    expect(result.startInput).toEqual({
      novel_type: 'romance',
      title: '郫西往事',
      summary: '姚奇伶和吴梓银的青春爱情故事',
      target_total_chapters: 36,
      requested_writing_style: '幽默诙谐',
    })
  })

  it('leaves blank optional fields for AI generation', () => {
    const result = buildCreationSubmission({
      novel_type: 'suspense',
      title: '   ',
      summary: '',
      total_chapters: 12,
      writing_style: ' ',
    })

    expect(result.startInput).toEqual({
      novel_type: 'suspense',
      target_total_chapters: 12,
    })
  })
})
