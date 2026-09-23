import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'

import LobbyRanks from './LobbyRanks'

afterEach(cleanup)

function renderLobby(buckets: { tier: string; games: number }[]) {
  const measured = buckets.reduce((sum, b) => sum + b.games, 0)
  return render(
    <TooltipProvider>
      <LobbyRanks lobby={{ total: measured + 10, measured, buckets, as_of: null }} />
    </TooltipProvider>,
  )
}

describe('LobbyRanks', () => {
  it('names the largest bucket, not the first', () => {
    // Buckets come highest first. The headline read "Master+" for a corpus
    // that was mostly Gold.
    renderLobby([
      { tier: 'MASTER+', games: 20 },
      { tier: 'DIAMOND', games: 30 },
      { tier: 'GOLD', games: 50 },
    ])
    expect(screen.getByText(/of these games were/).textContent).toBe(
      '50% of these games were Gold lobbies (100 of 110 measured)',
    )
  })

  it('says Master+ when that is where most of the games were', () => {
    renderLobby([
      { tier: 'MASTER+', games: 95 },
      { tier: 'DIAMOND', games: 5 },
    ])
    expect(screen.getByText(/of these games were/).textContent).toContain('95% of these games were Master+ lobbies')
  })

  it('shows nothing when no lobby was measured', () => {
    const { container } = render(
      <TooltipProvider>
        <LobbyRanks lobby={{ total: 40, measured: 0, buckets: [], as_of: null }} />
      </TooltipProvider>,
    )
    expect(container.textContent).toBe('')
  })
})
