import { useCallback, useEffect, useRef } from 'react'
import { useBlocker } from 'react-router-dom'

export type GuardedAction = () => void | Promise<void>
export interface NavigationGuardOptions {
  pageUnload?: boolean
}
export type NavigationGuard = (
  action: GuardedAction,
  options?: NavigationGuardOptions,
) => void
export type DiscardConfirmation = (
  onConfirm: GuardedAction,
  onCancel?: () => void,
) => void

/** 同时保护应用内导航、浏览器历史导航和页面关闭。 */
export function useUnsavedChangesGuard(
  hasUnsavedChanges: boolean,
  requestConfirmation: DiscardConfirmation,
): NavigationGuard {
  const allowNavigationRef = useRef(false)
  const promptSourceRef = useRef<'explicit' | 'blocker' | undefined>(undefined)
  const blocker = useBlocker(({ currentLocation, nextLocation }) => {
    if (!hasUnsavedChanges || allowNavigationRef.current) return false
    return currentLocation.pathname !== nextLocation.pathname
      || currentLocation.search !== nextLocation.search
      || currentLocation.hash !== nextLocation.hash
  })

  const runAllowed = useCallback(async (
    action: GuardedAction,
    options?: NavigationGuardOptions,
  ) => {
    allowNavigationRef.current = true
    let keepAllowed = false
    try {
      await action()
      keepAllowed = options?.pageUnload === true
    } finally {
      if (!keepAllowed) allowNavigationRef.current = false
    }
  }, [])

  const guard = useCallback<NavigationGuard>((action, options) => {
    if (!hasUnsavedChanges) {
      void action()
      return
    }
    if (promptSourceRef.current) return
    promptSourceRef.current = 'explicit'
    requestConfirmation(
      async () => {
        try {
          await runAllowed(action, options)
        } finally {
          promptSourceRef.current = undefined
        }
      },
      () => { promptSourceRef.current = undefined },
    )
  }, [hasUnsavedChanges, requestConfirmation, runAllowed])

  useEffect(() => {
    if (!hasUnsavedChanges) return
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      if (allowNavigationRef.current) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warnBeforeUnload)
    return () => window.removeEventListener('beforeunload', warnBeforeUnload)
  }, [hasUnsavedChanges])

  useEffect(() => {
    if (blocker.state !== 'blocked') return
    if (promptSourceRef.current === 'explicit') {
      blocker.reset()
      return
    }
    if (promptSourceRef.current === 'blocker') return
    promptSourceRef.current = 'blocker'
    requestConfirmation(
      async () => {
        promptSourceRef.current = undefined
        await runAllowed(() => blocker.proceed())
      },
      () => {
        promptSourceRef.current = undefined
        blocker.reset()
      },
    )
  }, [blocker, requestConfirmation, runAllowed])

  return guard
}
