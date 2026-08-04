import type { NovelCreateRequest } from '@/types/novel'

export interface CreationForm {
  novel_type: string
  title?: string
  summary?: string
  core_premise?: string
  reader_promise?: string
  content_boundaries?: string
  setting_era?: string
  setting_region?: string
  naming_preference?: string
  total_chapters: number
  writing_style?: string
}

function trimmed(value?: string): string | undefined {
  return value?.trim() || undefined
}

function creativeBriefFrom(values: CreationForm) {
  const era = trimmed(values.setting_era)
  const region = trimmed(values.setting_region)
  const settingContext = { ...(era ? { era } : {}), ...(region ? { region } : {}) }
  return {
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
      ...(writingStyle ? { requested_writing_style: writingStyle } : {}),
      ...(hasCreativeBrief ? { creative_brief: creativeBrief } : {}),
    },
  }
}
