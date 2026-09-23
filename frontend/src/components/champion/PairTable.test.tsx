import { cleanup, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'

import type { ChampionDetail, PairEntry } from '../../lib/api'
import { calledCount, pairPatches } from '../../lib/pairs'
import PairTable from './PairTable'
import RunePanel from './RunePanel'

afterEach(cleanup)

function pair(id: number, name: string, wins: number, games: number, lift: number, call: PairEntry['call'] = 'level'): PairEntry {
  return {
    champion: { id, name, icon_url: null, slug: name.toLowerCase() },
    games,
    wins,
    win_rate: wins / games,
    own_rate: 0.52,
    lift,
    call,
    patches: ['16.18', '16.17'],
    confidence_win_rate: 0.3,
    confidence_high: 0.7,
    position: null,
    avg_laning_score: null,
    avg_gold_diff_14: null,
    timeline_games: 0,
  }
}

const rows = [
  pair(1, 'Yone', 2, 7, -0.012),
  pair(2, 'Syndra', 30, 40, 0.061, 'favoured'),
  pair(3, 'Akali', 9, 30, -0.071, 'unfavoured'),
]

function renderTable(order: 'worst' | 'best') {
  render(
    <MemoryRouter>
      <TooltipProvider>
        <PairTable
          title="Lane matchups"
          rows={rows}
          order={order}
          query=""
          championName="Ahri"
          strength={100}
          showGold
          linkFor={() => '/champions/x'}
        />
      </TooltipProvider>
    </MemoryRouter>,
  )
  return screen.getAllByRole('row').slice(1)
}

describe('PairTable', () => {
  it('orders by the gap from the usual rate, hardest first, and says each call', () => {
    const body = renderTable('worst')
    expect(body.map((r) => within(r).getByRole('link').textContent)).toEqual(['Akali', 'Yone', 'Syndra'])
    expect(body[0].textContent).toContain('9-21')
    expect(body[0].textContent).toContain('-7.1')
    expect(body[0].textContent).toContain('unfavoured')
    expect(body[1].textContent).toContain('not called')
  })

  it('turns round for the easiest first', () => {
    const body = renderTable('best')
    expect(within(body[0]).getByRole('link').textContent).toBe('Syndra')
  })

  it('counts the calls and names the patches read', () => {
    expect(calledCount(rows)).toBe(2)
    expect(pairPatches(rows)).toBe('16.18 and 16.17')
  })
})

describe('RunePanel', () => {
  it('names the keystone and writes a page out in words, shards included', () => {
    const rune = (id: number, name: string) => ({ id, name, icon_url: null })
    const facet = (ids: number[], runes: ReturnType<typeof rune>[]) => ({
      ids,
      games: 20,
      wins: 11,
      win_rate: 0.55,
      pick_rate: 0.4,
      range_low: 0.34,
      range_high: 0.74,
      slot_delta: null,
      slot_buyers: 0,
      items: [],
      spells: [],
      runes,
    })
    const runes: ChampionDetail['runes'] = {
      keystones: [facet([8005], [rune(8005, 'Press the Attack')])],
      pages: [
        facet(
          [8000, 8005, 8009, 9103, 8014, 8300, 8304, 8321, 5008, 5010, 5001],
          [
            rune(8000, 'Precision'),
            rune(8005, 'Press the Attack'),
            rune(8009, 'Presence of Mind'),
            rune(9103, 'Legend: Bloodline'),
            rune(8014, 'Coup de Grace'),
            rune(8300, 'Inspiration'),
            rune(8304, 'Magical Footwear'),
            rune(8321, 'Cash Back'),
            rune(5008, 'Adaptive Force'),
            rune(5010, 'Move Speed'),
            rune(5001, 'Health Scaling'),
          ],
        ),
      ],
    }
    render(<RunePanel runes={runes} />)
    expect(screen.getAllByText('Press the Attack').length).toBeGreaterThan(0)
    expect(
      screen.getByText(
        'Press the Attack, Presence of Mind, Legend: Bloodline, Coup de Grace; Magical Footwear, Cash Back; Adaptive Force, Move Speed, Health Scaling',
      ),
    ).toBeTruthy()
  })
})
