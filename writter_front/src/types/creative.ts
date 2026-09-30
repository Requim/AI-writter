export interface CreativeBudget {
  preparation: number
  chapter: number
  review: number | null
  search: number
  preparation_search: number
}

export interface AuthorConfiguration {
  author_mode: 'autonomous_v1'
  creative_schema_version: 1
  narrative_mode: 'auto' | 'stable' | 'ensemble_relay'
  hard_constraints: string[]
  target_readers: string
  author_question: string
  desired_experience: string
  sources: unknown[]
  research_queries: string[]
  budget: CreativeBudget
  author_profile_id?: string
  author_profile_version?: number
}

export interface CreativeOptions {
  enabled: boolean
  tenant_enabled: boolean
  global_enabled: boolean
  request_limit: number
}

export interface TextEvidence {
  chapter_id: string
  chapter_version: number
  chapter_number: number
  content_hash: string
  start: number
  end: number
  quote: string
}

export interface CreativeRecord {
  id: string
  kind: string
  key: string
  version: number
  payload: Record<string, unknown>
  source: string
  status: string
  evidence: TextEvidence[]
  input_versions: Record<string, number | string>
  created_at: string
}

export interface CreativeOverview {
  session: {
    id: string
    version: number
    stage: string
    status: string
    config: AuthorConfiguration
    limits: CreativeBudget & { total: number; chapters: number }
    counters: Record<string, number>
  }
  artifact_counts: Record<string, number>
  real_reader_validation: string
}

export interface AuthorRecord {
  id: string
  key: string
  kind: 'sample' | 'profile'
  version: number
  payload: Record<string, unknown>
  created_at: string
}
