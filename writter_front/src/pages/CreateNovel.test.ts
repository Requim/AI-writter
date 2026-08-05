import { describe, expect, it } from 'vitest'
import type { GenreProfile } from '@/types/novel'
import { buildCreationSubmission } from './creationSubmission'
import { quotaBlocksCreation, quotaNoticeDetails } from './creationQuota'
import { genreDefaults } from './genreSelection'

const suspenseProfile: GenreProfile = {
  value: 'suspense',
  label: '悬疑',
  description: '谜团驱动',
  subgenres: [
    { value: 'cold_case', label: '旧案重启' },
    { value: 'fair_play', label: '本格推理' },
  ],
  reader_experiences: [
    { value: 'clue_puzzle', label: '线索推理' },
    { value: 'truth_shock', label: '真相震荡' },
  ],
  pace_options: [
    { value: 'hook_dense', label: '强钩子快节奏' },
    { value: 'balanced', label: '起伏均衡' },
  ],
  prompt_axes: {},
}

describe('buildCreationSubmission', () => {
  it('passes user-authored fields to both persistence and workflow input', () => {
    const result = buildCreationSubmission({
      novel_type: 'romance',
      subgenre: ' second_chance ',
      reader_experience: ' emotional_tension ',
      narrative_pace: ' slow_burn ',
      title: '  郫西往事  ',
      summary: ' 姚奇伶和吴梓银的青春爱情故事 ',
      core_premise: ' 两位旧友因一封迟到十年的信重逢 ',
      reader_promise: ' 克制的情感拉扯与逐层揭晓的旧事 ',
      content_boundaries: ' 不使用失忆梗 ',
      setting_era: ' 1990 年代末 ',
      setting_region: ' 江南县城 ',
      naming_preference: ' 参考《诗经》，清雅但不生僻 ',
      planning_preset: 'medium',
      total_chapters: 36,
      target_total_words: 151_200,
      writing_style: ' 幽默诙谐 ',
    })

    expect(result.payload).toEqual({
      novel_type: 'romance',
      title: '郫西往事',
      summary: '姚奇伶和吴梓银的青春爱情故事',
      planning: { preset: 'medium', target_chapters: 36, target_total_words: 151_200 },
      total_outline: {
        total_chapters: 36,
        writing_style: '幽默诙谐',
        creative_brief: {
          genre_context: {
            main_type: 'romance',
            subgenre: 'second_chance',
            reader_experience: 'emotional_tension',
            narrative_pace: 'slow_burn',
          },
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
      target_total_words: 151_200,
      planning: { preset: 'medium', target_chapters: 36, target_total_words: 151_200 },
      requested_writing_style: '幽默诙谐',
      creative_brief: {
        genre_context: {
          main_type: 'romance',
          subgenre: 'second_chance',
          reader_experience: 'emotional_tension',
          narrative_pace: 'slow_burn',
        },
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
      planning_preset: 'short',
      total_chapters: 12,
      target_total_words: 50_400,
      writing_style: ' ',
    })

    expect(result.startInput).toEqual({
      novel_type: 'suspense',
      target_total_chapters: 12,
      target_total_words: 50_400,
      planning: { preset: 'short', target_chapters: 12, target_total_words: 50_400 },
      creative_brief: {
        genre_context: { main_type: 'suspense' },
      },
    })
  })

  it('selects default subtype, reader experience and balanced pace for a genre', () => {
    expect(genreDefaults(suspenseProfile)).toEqual({
      novel_type: 'suspense',
      subgenre: 'cold_case',
      reader_experience: 'clue_puzzle',
      narrative_pace: 'balanced',
    })
  })
})

describe('creation quota notice', () => {
  const quota = {
    used: 8, limit: 10, remaining: 2, unlimited: false, ai_enabled: true, period_start: '2026-08-01',
  }

  it('warns without blocking when the next command is affordable but the full book is not', () => {
    expect(quotaNoticeDetails(quota, 12)).toEqual({
      state: 'warning',
      headline: '本月剩余 2 / 10 次',
      detail: '仍可启动 1 次，但余额不足以覆盖预计全书（预计 13 次，含 12 章生成）',
    })
    expect(quotaBlocksCreation(quota)).toBe(false)
  })

  it('blocks only when AI is disabled or no command can be reserved', () => {
    expect(quotaBlocksCreation({ ...quota, remaining: 0 })).toBe(true)
    expect(quotaBlocksCreation({ ...quota, ai_enabled: false })).toBe(true)
    expect(quotaBlocksCreation({ ...quota, remaining: 1 })).toBe(false)
  })

  it('presents unlimited quota without exposing the sentinel limit', () => {
    const unlimited = {
      ...quota, limit: 2_147_483_647, remaining: 2_147_483_633, unlimited: true,
    }

    expect(quotaNoticeDetails(unlimited, 12)).toEqual({
      state: 'ready', headline: '无限额度', detail: '计划生成 12 章',
    })
    expect(quotaBlocksCreation({ ...unlimited, remaining: 0 })).toBe(false)
  })
})
