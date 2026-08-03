import { describe, expect, it } from 'vitest'
import { createIdempotencyKey } from './idempotency'

describe('createIdempotencyKey', () => {
  it('creates a distinct RFC 4122 version 4 UUID for every command', () => {
    const first = createIdempotencyKey()
    const second = createIdempotencyKey()
    expect(first).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i)
    expect(second).not.toBe(first)
  })
})
