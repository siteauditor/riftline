import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useDebounced } from './useDebounced'

describe('useDebounced', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it('settles once the value has stopped changing for the whole wait', () => {
    const { result, rerender } = renderHook(({ value }) => useDebounced(value, 250), {
      initialProps: { value: 'a' },
    })
    rerender({ value: 'ab' })
    act(() => vi.advanceTimersByTime(200))
    rerender({ value: 'abc' })
    act(() => vi.advanceTimersByTime(200))
    // Each change starts the wait again: a steady typist costs one request a word.
    expect(result.current).toBe('a')
    act(() => vi.advanceTimersByTime(50))
    expect(result.current).toBe('abc')
  })

  it('leaves no timer running once the value has settled', () => {
    // The draft board passed an object, a new one every render, and re-rendered
    // every 250 ms for as long as the page was open. The same key again must
    // not start another wait.
    const { rerender } = renderHook(({ value }) => useDebounced(value, 250), {
      initialProps: { value: 'MIDDLE|122,64|103' },
    })
    act(() => vi.advanceTimersByTime(300))
    rerender({ value: 'MIDDLE|122,64|103' })
    rerender({ value: 'MIDDLE|122,64|103' })
    expect(vi.getTimerCount()).toBe(0)
  })
})
