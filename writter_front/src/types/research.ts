export type ResearchSourceCategory = '玄幻' | '武侠' | '恐怖' | '军事' | '女频' | '游戏' | '科幻'

export type ProjectGenre =
  | 'fantasy' | 'xianxia' | 'wuxia' | 'horror' | 'suspense'
  | 'military' | 'history' | 'romance' | 'game' | 'sci_fi'

export interface ResearchCapabilities {
  retrieval_backend: 'keyword' | string
  vector_enabled: boolean
  raw_text_persistence: boolean
}

export interface BatchAccepted {
  batch_id: string
  job_id: string
  status: 'queued'
}

export interface ResearchJob {
  job_id: string
  batch_id: string
  status: 'queued' | 'running' | 'completed' | 'partial' | 'failed'
  phase: string
  processed: number
  total: number
  error: string | null
}

export interface SearchHit {
  knowledge_version_id: string
  project_genre: ProjectGenre | string
  version: number
  status: string
  score: number
  matched_terms: string[]
  content: Record<string, unknown>
}

export interface KnowledgePackage {
  knowledge_version_id: string
  project_genre: ProjectGenre | string
  version: number
  status: 'draft' | 'review' | 'approved' | 'rejected' | string
  sample_count: number
  source_categories: string[]
  opening_pattern_counts: Record<string, number>
  mechanism_counts: Record<string, number>
  clusters: Array<Record<string, unknown>>
  writing_guidance: string[]
  originality_rules: string[]
  limitations: string[]
  evidence_sample_ids: string[]
  retrieval_text: string
  created_at: string
}

export interface SearchResponse {
  items: SearchHit[]
  backend: string
}
