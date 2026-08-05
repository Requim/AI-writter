import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { App as AntApp } from 'antd'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { novelApi } from '@/api/novel'
import CreateNovel from './CreateNovel'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('CreateNovel taxonomy loading', () => {
  it('disables creation when genre taxonomy cannot be loaded', async () => {
    vi.spyOn(novelApi, 'genreTaxonomy').mockRejectedValue(new Error('offline'))
    vi.spyOn(novelApi, 'planningOptions').mockResolvedValue({
      constraints: {
        min_chapters: 1, max_chapters: 200, min_chapter_words: 3000, max_chapter_words: 7000,
        default_tolerance_ratio: 0.1, default_lock_window: 5,
      },
      presets: [{ preset: 'short', label: '短篇', target_chapters: 12, target_total_words: 50_400, target_volumes: 1 }],
    })
    const router = createMemoryRouter([{ path: '/', element: <CreateNovel /> }])

    render(
      <AntApp>
        <RouterProvider router={router} />
      </AntApp>,
    )

    expect(await screen.findByText('题材分类无法读取，请确认后端服务已启动')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /创建并进入工作台/ })).toBeDisabled()
    })
  })
})
