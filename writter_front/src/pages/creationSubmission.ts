import type { NovelCreateRequest } from '@/types/novel'

export interface CreationForm {
  novel_type: string
  title?: string
  summary?: string
  core_premise?: string
  reader_promise?: string
  content_boundaries?: string
  total_chapters: number
  writing_style?: string
}

export function buildCreationSubmission(values: CreationForm) {
  const title = values.title?.trim() || undefined
  const summary = values.summary?.trim() || undefined
  const writingStyle = values.writing_style?.trim() || undefined
  const corePremise = values.core_premise?.trim() || undefined
  const readerPromise = values.reader_promise?.trim() || undefined
  const contentBoundaries = values.content_boundaries?.trim() || undefined
  const creativeBrief = {
    ...(corePremise ? { core_premise: corePremise } : {}),
    ...(readerPromise ? { reader_promise: readerPromise } : {}),
    ...(contentBoundaries ? { content_boundaries: contentBoundaries } : {}),
  }
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
