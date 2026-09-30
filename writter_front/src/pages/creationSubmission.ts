import type { NovelCreateRequest, PlanningPreset } from '@/types/novel'

export interface CreationForm {
  novel_type: string
  subgenre?: string
  reader_experience?: string
  narrative_pace?: string
  title?: string
  summary?: string
  core_premise?: string
  reader_promise?: string
  content_boundaries?: string
  setting_era?: string
  setting_region?: string
  naming_preference?: string
  planning_preset: PlanningPreset
  total_chapters: number
  target_total_words: number
  writing_style?: string
  autonomous_author?: boolean
  narrative_mode?: 'auto' | 'stable' | 'ensemble_relay'
  target_readers?: string
  author_question?: string
  hard_constraints?: string
  research_queries?: string
  creative_preparation_budget?: number
  creative_chapter_budget?: number
  creative_review_budget?: number
}

function trimmed(value?: string): string | undefined {
  return value?.trim() || undefined
}

function creativeBriefFrom(values: CreationForm) {
  const era = trimmed(values.setting_era)
  const region = trimmed(values.setting_region)
  const settingContext = { ...(era ? { era } : {}), ...(region ? { region } : {}) }
  const genreContext = {
    main_type: values.novel_type,
    ...(trimmed(values.subgenre) ? { subgenre: trimmed(values.subgenre) } : {}),
    ...(trimmed(values.reader_experience) ? { reader_experience: trimmed(values.reader_experience) } : {}),
    ...(trimmed(values.narrative_pace) ? { narrative_pace: trimmed(values.narrative_pace) } : {}),
  }
  return {
    genre_context: genreContext,
    ...(trimmed(values.core_premise) ? { core_premise: trimmed(values.core_premise) } : {}),
    ...(trimmed(values.reader_promise) ? { reader_promise: trimmed(values.reader_promise) } : {}),
    ...(trimmed(values.content_boundaries) ? { content_boundaries: trimmed(values.content_boundaries) } : {}),
    ...(Object.keys(settingContext).length ? { setting_context: settingContext } : {}),
    ...(trimmed(values.naming_preference) ? { naming_preference: trimmed(values.naming_preference) } : {}),
  }
}

export function buildCreationSubmission(values: CreationForm) {
  const title = trimmed(values.title)
  const summary = trimmed(values.summary)
  const writingStyle = trimmed(values.writing_style)
  const creativeBrief = creativeBriefFrom(values)
  const hasCreativeBrief = Object.keys(creativeBrief).length > 0
  const payload: NovelCreateRequest = {
    novel_type: values.novel_type,
    title,
    summary,
    ...(values.autonomous_author ? { author_config: authorConfiguration(values) } : {}),
    planning: {
      preset: values.planning_preset,
      target_chapters: values.total_chapters,
      target_total_words: values.target_total_words,
    },
    total_outline: values.total_chapters || writingStyle ? {
      total_chapters: values.total_chapters,
      writing_style: writingStyle,
      ...(hasCreativeBrief ? { creative_brief: creativeBrief } : {}),
    } : undefined,
  }

  return {
    payload,
    startInput: {
      novel_type: values.novel_type,
      ...(title ? { title } : {}),
      ...(summary ? { summary } : {}),
      target_total_chapters: values.total_chapters,
      target_total_words: values.target_total_words,
      planning: {
        preset: values.planning_preset,
        target_chapters: values.total_chapters,
        target_total_words: values.target_total_words,
      },
      ...(writingStyle ? { requested_writing_style: writingStyle } : {}),
      ...(hasCreativeBrief ? { creative_brief: creativeBrief } : {}),
    },
  }
}

function authorConfiguration(values: CreationForm): NonNullable<NovelCreateRequest['author_config']> {
  return {
    author_mode: 'autonomous_v1', creative_schema_version: 1,
    narrative_mode: values.narrative_mode || 'auto',
    hard_constraints: (values.hard_constraints || '').split('\n').map((s) => s.trim()).filter(Boolean),
    target_readers: values.target_readers?.trim() || '',
    author_question: values.author_question?.trim() || '',
    desired_experience: values.reader_promise?.trim() || '',
    research_queries: (values.research_queries || '').split('\n').map((s) => s.trim()).filter(Boolean),
    sources: [],
    budget: { preparation: values.creative_preparation_budget ?? 60, chapter: values.creative_chapter_budget ?? 32,
      review: values.creative_review_budget ?? null, search: 12, preparation_search: 6 },
  }
}
