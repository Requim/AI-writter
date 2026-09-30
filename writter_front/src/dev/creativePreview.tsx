import { createRoot } from 'react-dom/client'
import { App, ConfigProvider } from 'antd'
import { createMemoryRouter, Navigate, RouterProvider } from 'react-router'
import zhCN from 'antd/locale/zh_CN'
import { creativeApi } from '@/api/creative'
import BookShelf from '@/pages/BookShelf'
import CreateNovel from '@/pages/CreateNovel'
import NovelStudio from '@/pages/NovelStudio'
import Login from '@/pages/Login'
import Register from '@/pages/Register'
import TenantSettings from '@/pages/TenantSettings'
import { workbenchTheme } from '@/theme'
import { installWorkbenchFixtures } from './workbenchFixtures'
import { PreviewLayout } from './PreviewLayout'
import type { CreativeOverview, CreativeRecord } from '@/types/creative'
import '@fontsource/noto-sans-sc/400.css'
import '@fontsource/noto-sans-sc/500.css'
import '@fontsource/noto-sans-sc/600.css'
import '@fontsource/noto-serif-sc/600.css'
import '../index.css'

const configuration: CreativeOverview['session']['config'] = {
  author_mode: 'autonomous_v1', creative_schema_version: 1, narrative_mode: 'stable',
  target_readers: '都市悬疑读者', author_question: '当证据与信任冲突', desired_experience: '推理与关系变化',
  hard_constraints: ['无超自然能力'], sources: [], research_queries: [],
  budget: { preparation: 60, chapter: 32, review: 180, search: 12, preparation_search: 6 },
}
const overview: CreativeOverview = {
  session: { id: 'preview-session', version: 1, stage: 'postprocess:5', status: 'pending',
    config: configuration, limits: { ...configuration.budget, total: 880, chapters: 20 },
    counters: { preparation: 28, 'chapter:1': 18, 'chapter:2': 21, 'chapter:3': 19, 'chapter:4': 20, 'chapter:5': 22, review: 4 } },
  artifact_counts: {}, real_reader_validation: 'not_performed',
}
function record(kind: string, key: string, payload: Record<string, unknown>, status: string): CreativeRecord {
  return { id: crypto.randomUUID(), kind, key, version: 1, payload, status, source: 'model',
    input_versions: {}, evidence: [], created_at: '2026-09-09T00:00:00Z' }
}
const records = [
  record('selection', 'accepted', { title: '第七码头', narrative_mode: 'stable', reason: '模拟候选：调查推动关系变化', market_evidence_status: 'unknown' }, 'accepted'),
  record('character', 'investigator', { name: '许知衡', goal: '查明失踪案', belief: '只相信可复核的记录', narrative_status: 'active',
    arc_duties: [{ arc_id: 'main', function: 'drive', status: 'active' }], aliases: [], life_status: 'alive' }, 'active'),
  record('role_slot', 'future-witness', { description: '第8-10章登场的关键见证人', due_chapter: 10 }, 'planned'),
  record('foreshadow', 'missing-page', { description: '被撕走的一页交接记录', due_chapter: 15, resolution: '' }, 'seeded'),
  record('reader_state', '5:v1', { known: ['交接记录不完整'], expectations: ['缺页由谁带走'], emotions: ['不安'], fatigue: [] }, 'simulated'),
  record('experiment', 'window:1', { issue_key: '重复独白', factor: '减少重复解释', variant_a: '他又想起那句解释，又一次怀疑自己的判断。', variant_b: '他把那句解释划掉，在旁边写下时间。' }, 'model_supported_trial'),
]
creativeApi.overview = async () => structuredClone(overview)
creativeApi.artifacts = async () => structuredClone(records)
creativeApi.authorRecords = async () => []
const unavailable = async () => { throw new Error('此隔离预览不写入真实服务') }
creativeApi.authorSample = unavailable
creativeApi.authorProfile = unavailable
creativeApi.bindProfile = unavailable
creativeApi.humanReview = unavailable
creativeApi.feedback = unavailable
creativeApi.upload = unavailable
creativeApi.budget = async (_id, payload) => {
  const update = payload as { limits: CreativeOverview['session']['config']['budget'] }
  Object.assign(overview.session.limits, update.limits)
  overview.session.version += 1
  return structuredClone(overview.session)
}
creativeApi.sources = async (_id, payload) => {
  const item = record('source', crypto.randomUUID(), payload as Record<string, unknown>, 'available')
  records.push(item)
  return item
}

if (import.meta.env.DEV) {
  installWorkbenchFixtures(configuration)
  const router = createMemoryRouter([{ element: <PreviewLayout />, children: [
    { path: '/', element: <BookShelf /> }, { path: '/novels/new', element: <CreateNovel /> },
    { path: '/novels/:novelId', element: <NovelStudio /> }, { path: '/login', element: <Login /> },
    { path: '/register', element: <Register /> },
    { path: '/settings/members', element: <TenantSettings /> },
    { path: '*', element: <Navigate to="/" replace /> },
  ] }])
  createRoot(document.getElementById('root')!).render(<ConfigProvider locale={zhCN} theme={workbenchTheme}>
    <App><RouterProvider router={router} /></App>
  </ConfigProvider>)
}
