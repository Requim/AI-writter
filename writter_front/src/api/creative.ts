import { apiClient } from './client'
import { createIdempotencyKey } from './idempotency'
import type { AuthorRecord, CreativeOptions, CreativeOverview, CreativeRecord } from '@/types/creative'

async function data<T>(request: Promise<{ data: T }>): Promise<T> { return (await request).data }
function command() { return { headers: { 'Idempotency-Key': createIdempotencyKey() } } }
function root(novelId: string) { return `/v1/novels/${novelId}/creative` }

export const creativeApi = {
  options: () => data<CreativeOptions>(apiClient.get('/v1/novels/creative-options')),
  overview: (id: string) => data<CreativeOverview>(apiClient.get(root(id))),
  artifacts: (id: string) => data<CreativeRecord[]>(apiClient.get(`${root(id)}/artifacts`)),
  sources: (id: string, payload: unknown) => data<CreativeRecord>(apiClient.post(`${root(id)}/sources`, payload, command())),
  upload: (id: string, file: File) => data<CreativeRecord>(apiClient.post(
    `${root(id)}/sources/file`, file,
    { ...command(), params: { filename: file.name }, headers: { ...command().headers, 'Content-Type': 'text/plain;charset=UTF-8' } },
  )),
  feedback: (id: string, payload: unknown) => data<unknown>(apiClient.post(`${root(id)}/feedback`, payload, command())),
  budget: (id: string, payload: unknown) => data<CreativeOverview['session']>(apiClient.put(`${root(id)}/budget`, payload, command())),
  bindProfile: (id: string, payload: unknown) => data<unknown>(apiClient.put(`${root(id)}/author-profile`, payload, command())),
  humanReview: (id: string, experimentId: string, payload: unknown) => data<CreativeRecord>(apiClient.post(
    `${root(id)}/experiments/${experimentId}/human-review`, payload, command(),
  )),
  authorRecords: (kind: 'samples' | 'profiles') => data<AuthorRecord[]>(apiClient.get(`/v1/author/${kind}`)),
  authorSample: (payload: unknown) => data<AuthorRecord>(apiClient.post('/v1/author/samples', payload, command())),
  authorProfile: (payload: unknown) => data<AuthorRecord>(apiClient.post('/v1/author/profiles', payload, command())),
}
