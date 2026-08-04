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
