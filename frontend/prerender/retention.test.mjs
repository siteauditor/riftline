import { describe, expect, it } from 'vitest'

import { FILE_DAYS, selectKept } from './retention.mjs'

const DAY = 24 * 60 * 60 * 1000
const now = Date.UTC(2026, 8, 24, 12)

describe('selectKept', () => {
  it('keeps the current pages and the newest other build beside them', () => {
    const folders = [
      { name: 'old', mtime: now - 3 * DAY },
      { name: 'cur', mtime: now },
      { name: 'prev', mtime: now - DAY },
    ]
    const { pages } = selectKept({ current: 'cur', folders, records: [], now })
    expect([...pages].sort()).toEqual(['cur', 'prev'])
  })

  it("keeps a week of builds' files however many deploys there were", () => {
    // Six deploys in a day, then one from ten days ago.
    const records = [
      ...['a', 'b', 'c', 'd', 'e'].map((id, i) => ({ id, renderedAt: now - (i + 1) * 3_600_000 })),
      { id: 'cur', renderedAt: now },
      { id: 'ancient', renderedAt: now - 10 * DAY },
    ]
    const { records: kept } = selectKept({ current: 'cur', folders: [], records, now })
    expect([...kept].sort()).toEqual(['a', 'b', 'c', 'cur', 'd', 'e'])
  })

  it('keeps the newest two others even when they are older than a week', () => {
    const records = [
      { id: 'cur', renderedAt: now },
      { id: 'month', renderedAt: now - 30 * DAY },
      { id: 'fortnight', renderedAt: now - 14 * DAY },
      { id: 'quarter', renderedAt: now - 90 * DAY },
    ]
    const { records: kept } = selectKept({ current: 'cur', folders: [], records, now })
    expect([...kept].sort()).toEqual(['cur', 'fortnight', 'month'])
  })

  it('keeps the current build whether or not it has a record yet', () => {
    const { pages, records } = selectKept({ current: 'cur', folders: [], records: [], now })
    expect(pages.has('cur') && records.has('cur')).toBe(true)
    expect(FILE_DAYS).toBe(7)
  })
})
