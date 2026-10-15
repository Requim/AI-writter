import { App } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import SimpleCreateNovel from './SimpleCreateNovel'

const { api } = vi.hoisted(() => ({ api: {
  genreTaxonomy: vi.fn(), planningOptions: vi.fn(), create: vi.fn(),
} }))
vi.mock('@/api/novel', () => ({ novelApi: api }))
vi.mock('@/components/AppShell', () => ({ AppShell: ({ children }: { children: ReactNode }) => children }))

afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('simple novel creation', () => {
  it('creates a short-plan novel and enters its conversation workbench', async () => {
    api.genreTaxonomy.mockResolvedValue([{ value: 'suspense', label: '悬疑', description: '谜团驱动', subgenres: [], reader_experiences: [], pace_options: [], prompt_axes: {} }])
    api.planningOptions.mockResolvedValue({
      constraints: { min_chapters: 1, max_chapters: 200, min_chapter_words: 3000, max_chapter_words: 7000, default_tolerance_ratio: 0.1, default_lock_window: 5 },
      presets: [{ preset: 'short', label: '短篇', target_chapters: 12, target_total_words: 50400, target_volumes: 1 }],
    })
    api.create.mockResolvedValue({ novel_id: 'novel-7', thread_id: 'thread-7', status: 'draft' })
    const router = createMemoryRouter([
      { path: '/novels/new', element: <SimpleCreateNovel /> },
      { path: '/novels/:novelId', element: <div>conversation target</div> },
    ], { initialEntries: ['/novels/new'] })
    render(<App><RouterProvider router={router} /></App>)

    await screen.findByRole('combobox', { name: '小说类型' })
    await userEvent.type(screen.getByRole('textbox', { name: '作品名' }), '雾站来信')
    await userEvent.type(screen.getByRole('textbox', { name: '故事起点' }), '一封晚到十年的信让两位旧友在雨夜重逢。')
    fireEvent.click(screen.getByRole('button', { name: '创建并开始讨论' }))

    await waitFor(() => expect(api.create).toHaveBeenCalledWith(expect.objectContaining({
      novel_type: 'suspense', title: '雾站来信', summary: '一封晚到十年的信让两位旧友在雨夜重逢。',
      planning: { preset: 'short', target_chapters: 12, target_total_words: 50400 },
    })))
    expect(await screen.findByText('conversation target')).toBeInTheDocument()
  })
})
