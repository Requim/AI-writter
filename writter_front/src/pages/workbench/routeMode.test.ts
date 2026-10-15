import { describe, expect, it } from 'vitest'
import { conversationWorkbenchEnabled } from './routeMode'

describe('conversation workbench route mode', () => {
  it('defaults to the workbench and preserves an explicit legacy switch', () => {
    expect(conversationWorkbenchEnabled(undefined)).toBe(true)
    expect(conversationWorkbenchEnabled('true')).toBe(true)
    expect(conversationWorkbenchEnabled('false')).toBe(false)
  })
})
