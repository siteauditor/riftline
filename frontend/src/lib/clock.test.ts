import { renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { renderNow, setServerNow, useLocalOffsetHours, useNow } from './clock'

afterEach(() => {
  setServerNow(null)
  delete window.__RENDERED_AT__
})

describe('renderNow', () => {
  it('is the real clock when nothing was prerendered', () => {
    expect(Math.abs(renderNow() - Date.now())).toBeLessThan(1000)
  })

  it('is the prerender stamp while hydrating, and the server clock while rendering', () => {
    window.__RENDERED_AT__ = 1_000
    expect(renderNow()).toBe(1_000)
    setServerNow(5_000)
    expect(renderNow()).toBe(5_000)
  })
})

describe('useNow', () => {
  it('gives a number near the real clock in the browser', () => {
    const { result } = renderHook(() => useNow())
    expect(Math.abs(result.current - Date.now())).toBeLessThan(10_000)
  })
})

describe('useLocalOffsetHours', () => {
  it('reports whole hours from UTC', () => {
    const { result } = renderHook(() => useLocalOffsetHours())
    expect(result.current).toBe(Math.round(-new Date().getTimezoneOffset() / 60))
    expect(Number.isInteger(result.current)).toBe(true)
  })
})
