import { App } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import ResearchConsole from './ResearchConsole'

const { api } = vi.hoisted(() => ({ api: {
  capabilities: vi.fn(), search: vi.fn(), review: vi.fn(), current: vi.fn(), job: vi.fn(), createBatch: vi.fn(),
} }))
vi.mock('@/components/AppShell', () => ({ AppShell: ({ children }: { children: ReactNode }) => children }))
vi.mock('@/api/research', () => ({ researchApi: api, researchErrorMessage: () => '请求失败' }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

const material = {
  knowledge_version_id: 'knowledge-test', project_genre: 'fantasy', version: 1,
  status: 'draft', sample_count: 2, writing_guidance: ['日常转入事件'],
  originality_rules: ['不复制专名'], limitations: ['低置信度'],
}

describe('写作素材库', () => {
  it.each(['failed', 'partial'])('keeps %s details visible even for legacy completed phase', async (status) => {
    api.capabilities.mockResolvedValue({})
    api.createBatch.mockResolvedValue({ job_id: 'job-1', batch_id: 'batch-1', status: 'queued' })
    api.job.mockResolvedValue({
      job_id: 'job-1', batch_id: 'batch-1', status, phase: 'completed',
      processed: status === 'partial' ? 1 : 0, total: 10,
      error: '女频: 来源目录暂不可用：HTTP 520',
    })
    render(<App><ResearchConsole /></App>)
    fireEvent.click(screen.getByText('采集新资料', { selector: 'summary' }))
    fireEvent.click(screen.getByRole('button', { name: /提交批次/ }))
    await waitFor(() => expect(api.createBatch).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText(
      status === 'failed' ? '批次执行失败' : '批次部分完成'
    )).toBeVisible(), { timeout: 5000 })
    expect(screen.getByText('采集新资料', { selector: 'summary' }).closest('details')).toHaveAttribute('open')
    expect(screen.queryByText('已完成')).not.toBeInTheDocument()
    for (const item of screen.getAllByText(/女频: 来源目录暂不可用/)) expect(item).toBeVisible()
    expect(screen.getByText(/来源站点暂时不可用/)).toBeVisible()
  })

  it('shows pending collected materials and opens their review without copying IDs', async () => {
    api.capabilities.mockResolvedValue({
      genre_labels: { fantasy: '奇幻 / 玄幻', xianxia: '仙侠' },
      source_to_project_genres: { 玄幻: ['fantasy', 'xianxia'] },
    })
    api.search.mockResolvedValue({ items: [{
      ...material, content: material, matched_terms: [], score: 1,
    }] })
    render(<App><ResearchConsole /></App>)
    expect(screen.getByRole('heading', { name: '写作素材库' })).toBeInTheDocument()
    await waitFor(() => expect(api.capabilities).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: /检索/ }))
    await waitFor(() => expect(api.search).toHaveBeenCalledWith(expect.objectContaining({
      project_genre: 'fantasy', approved_only: false,
    })))
    fireEvent.click(await screen.findByText('版本 1', { exact: true }))
    fireEvent.click(screen.getByRole('button', { name: /选择此版本审核/ }))
    expect(screen.getByRole('textbox', { name: /审核人/ })).toBeVisible()
    expect(screen.getAllByText('低置信度').length).toBeGreaterThan(0)
  })
})
