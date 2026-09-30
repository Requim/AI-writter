import axios from 'axios'
import { apiClient } from './client'
import type {
  BatchAccepted, KnowledgePackage, ResearchCapabilities, ResearchJob, SearchResponse,
} from '@/types/research'

async function data<T>(request: Promise<{ data: T }>): Promise<T> {
  return (await request).data
}

export const researchApi = {
  capabilities: () => data<ResearchCapabilities>(apiClient.get('/v1/research/capabilities')),
  createBatch: (payload: unknown) => data<BatchAccepted>(apiClient.post('/v1/research/batches', payload)),
  job: (jobId: string) => data<ResearchJob>(apiClient.get(`/v1/research/jobs/${jobId}`)),
  search: (params: Record<string, string | number | boolean | undefined>) => data<SearchResponse>(apiClient.get('/v1/research/knowledge/search', { params })),
  current: (genre: string) => data<KnowledgePackage>(apiClient.get(`/v1/research/knowledge/${genre}`)),
  review: (versionId: string, payload: unknown) => data<KnowledgePackage>(apiClient.post(`/v1/research/knowledge/${versionId}/review`, payload)),
}

export function researchErrorMessage(error: unknown): string {
  if (!axios.isAxiosError(error)) return '研究服务请求失败，请稍后重试'
  const detail = error.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (error.response?.status === 401) return '登录状态无效或已过期，请重新登录'
  if (error.response?.status === 403) return '当前账号没有研究资料权限'
  if (error.response?.status === 404) return '研究对象不存在，可能尚未生成或已被清理'
  return `研究服务请求失败（${error.response?.status || '网络异常'}）`
}
