import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CountUp from './CountUp'

const pct = (n: number) => `${n.toFixed(1)}%`

describe('CountUp', () => {
  // Frames are driven by hand: a count that depends on the browser's own
  // frame clock cannot be observed in a background tab, let alone in jsdom.
  let frames: FrameRequestCallback[]
  let now: number

  function advance(ms: number) {
    now += ms
    const due = frames.splice(0)
    act(() => due.forEach((cb) => cb(now)))
  }

  beforeEach(() => {
    frames = []
    now = 1_000
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => frames.push(cb))
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {})
    vi.spyOn(performance, 'now').mockImplementation(() => now)
    window.matchMedia = vi.fn().mockReturnValue({ matches: false }) as unknown as typeof window.matchMedia
  })

  afterEach(() => {
    delete document.documentElement.dataset.hydrated
    vi.restoreAllMocks()
  })

  it('shows the value at once on a page being hydrated, so the HTML is matched', () => {
    const { container } = render(<CountUp value={52.7} format={pct} />)
    expect(container.textContent).toBe('52.7%')
    expect(frames).toHaveLength(0)
  })

  it('counts from zero to the value on a page the app navigated to', () => {
    document.documentElement.dataset.hydrated = 'true'
    const { container } = render(<CountUp value={52.7} format={pct} />)
    expect(container.textContent).toBe('0.0%')
    advance(100)
    const midway = parseFloat(container.textContent!)
    expect(midway).toBeGreaterThan(0)
    expect(midway).toBeLessThan(52.7)
    advance(700)
    expect(container.textContent).toBe('52.7%')
  })

  it('counts a new value from the one shown, never from zero again', () => {
    document.documentElement.dataset.hydrated = 'true'
    const { container, rerender } = render(<CountUp value={50} format={pct} />)
    advance(800)
    expect(container.textContent).toBe('50.0%')
    rerender(<CountUp value={60} format={pct} />)
    advance(0)
    expect(container.textContent).toBe('50.0%')
    advance(100)
    const midway = parseFloat(container.textContent!)
    expect(midway).toBeGreaterThan(50)
    expect(midway).toBeLessThan(60)
    advance(700)
    expect(container.textContent).toBe('60.0%')
  })

  it('shows the value at once under reduced motion', () => {
    document.documentElement.dataset.hydrated = 'true'
    window.matchMedia = vi.fn().mockReturnValue({ matches: true }) as unknown as typeof window.matchMedia
    const { container } = render(<CountUp value={52.7} format={pct} />)
    expect(container.textContent).toBe('52.7%')
    expect(frames).toHaveLength(0)
  })
})
