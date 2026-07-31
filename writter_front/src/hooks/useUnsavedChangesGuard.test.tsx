import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider, useNavigate } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  useUnsavedChangesGuard,
  type DiscardConfirmation,
  type GuardedAction,
} from './useUnsavedChangesGuard'

afterEach(cleanup)

function DirtyEditor({ requestConfirmation }: { requestConfirmation: DiscardConfirmation }) {
  const navigate = useNavigate()
  const guard = useUnsavedChangesGuard(true, requestConfirmation)
  return (
    <>
      <span>编辑中</span>
      <button onClick={() => guard(() => navigate('/previous'))}>返回</button>
      <button onClick={() => guard(() => undefined, { pageUnload: true })}>切换工作区</button>
    </>
  )
}

function setup() {
  let confirm: GuardedAction | undefined
  let cancel: (() => void) | undefined
  const requestConfirmation = vi.fn<DiscardConfirmation>((onConfirm, onCancel) => {
    confirm = onConfirm
    cancel = onCancel
  })
  const router = createMemoryRouter([
    { path: '/previous', element: <span>上一页</span> },
    { path: '/edit', element: <DirtyEditor requestConfirmation={requestConfirmation} /> },
  ], { initialEntries: ['/previous', '/edit'], initialIndex: 1 })
  render(<RouterProvider router={router} />)
  return {
    router,
    requestConfirmation,
    confirm: () => confirm,
    cancel: () => cancel,
  }
}

describe('useUnsavedChangesGuard', () => {
  it('stays on the page when browser history navigation is cancelled', async () => {
    const { router, requestConfirmation, cancel } = setup()

    await act(() => router.navigate(-1))
    expect(requestConfirmation).toHaveBeenCalledOnce()
    act(() => cancel()?.())

    expect(router.state.location.pathname).toBe('/edit')
    expect(screen.getByText('编辑中')).toBeInTheDocument()
  })

  it('continues browser history navigation after confirmation', async () => {
    const { router, confirm } = setup()

    await act(() => router.navigate(-1))
    await act(async () => { await confirm()?.() })

    expect(router.state.location.pathname).toBe('/previous')
    expect(screen.getByText('上一页')).toBeInTheDocument()
  })

  it('does not show a second prompt for an already confirmed app navigation', async () => {
    const { requestConfirmation, confirm } = setup()

    fireEvent.click(screen.getByRole('button', { name: '返回' }))
    expect(requestConfirmation).toHaveBeenCalledOnce()
    await act(async () => { await confirm()?.() })

    expect(requestConfirmation).toHaveBeenCalledOnce()
    expect(screen.getByText('上一页')).toBeInTheDocument()
  })

  it('coalesces repeated protected actions while confirmation is open', () => {
    const { requestConfirmation } = setup()
    const button = screen.getByRole('button', { name: '返回' })

    fireEvent.click(button)
    fireEvent.click(button)

    expect(requestConfirmation).toHaveBeenCalledOnce()
  })

  it('does not stack a history prompt over an open app-navigation prompt', async () => {
    const { router, requestConfirmation, cancel } = setup()

    fireEvent.click(screen.getByRole('button', { name: '返回' }))
    await act(() => router.navigate(-1))

    expect(requestConfirmation).toHaveBeenCalledOnce()
    expect(router.state.location.pathname).toBe('/edit')
    act(() => cancel()?.())
  })

  it('does not show a native prompt after a confirmed full-page navigation', async () => {
    const { confirm } = setup()

    fireEvent.click(screen.getByRole('button', { name: '切换工作区' }))
    await act(async () => { await confirm()?.() })
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)

    expect(event.defaultPrevented).toBe(false)
  })
})
