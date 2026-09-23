import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { DraftResponse } from '../../lib/api'
import { mainType, otherType } from '../../lib/damage'
import TeamMix from './TeamMix'

afterEach(cleanup)

type Damage = DraftResponse['team_damage']

const champion = (id: number, name: string) => ({ id, name, icon_url: null, slug: name.toLowerCase() })

function damage(allies: Damage['allies'], available = true): Damage {
  return { available, allies, enemies: null, min_games: 10, one_sided_share: 0.7 }
}

describe('TeamMix', () => {
  it('states each type with its share, and names who is left out', () => {
    render(
      <TeamMix
        side="allies"
        damage={damage({
          shares: { physical: 0.62, magic: 0.31, true: 0.07 },
          measured: 2,
          missing: [champion(901, 'Smolder')],
          leaning: null,
        })}
      />,
    )
    expect(screen.getByText(/damage/).textContent).toBe(
      '62% physical, 31% magic, 7% true damage, without Smolder (under 10 games).',
    )
  })

  it('says which picks are marked when your side leans one way', () => {
    render(
      <TeamMix
        side="allies"
        damage={damage({ shares: { physical: 0.86, magic: 0.05, true: 0.09 }, measured: 3, missing: [], leaning: 'physical' })}
      />,
    )
    expect(screen.getByText(/damage/).textContent).toBe(
      '86% physical, 5% magic, 9% true damage. Mostly physical: picks that deal mostly magic are marked.',
    )
  })

  it('says the enemy side leans without pointing at picks', () => {
    const mix = { shares: { physical: 0.1, magic: 0.85, true: 0.05 }, measured: 4, missing: [], leaning: 'magic' as const }
    render(<TeamMix side="enemies" damage={{ ...damage(null), enemies: mix }} />)
    const text = screen.getByText(/damage/).textContent
    expect(text).toContain('Mostly magic.')
    expect(text).not.toContain('marked')
  })

  it('says a side is not measured rather than drawing an empty bar', () => {
    const { rerender } = render(
      <TeamMix
        side="allies"
        damage={damage({ shares: null, measured: 0, missing: [champion(1, 'Ahri'), champion(2, 'Zed')], leaning: null })}
      />,
    )
    expect(screen.getByText(/Damage mix/).textContent).toBe('Damage mix: Ahri and Zed have under 10 games so far.')

    rerender(
      <TeamMix
        side="allies"
        damage={damage({ shares: null, measured: 0, missing: [champion(1, 'Ahri')], leaning: null }, false)}
      />,
    )
    expect(screen.getByText(/Damage mix/).textContent).toBe('Damage mix: not measured yet.')
  })

  it('draws nothing for a side that is not on the board', () => {
    const { container } = render(<TeamMix side="allies" damage={damage(null)} />)
    expect(container.textContent).toBe('')
  })
})

describe('damage types', () => {
  it('name the type a pick deals most and the one that balances a lean', () => {
    expect(mainType({ physical: 0.2, magic: 0.7, true: 0.1 })).toBe('magic')
    expect(mainType({ physical: 0.5, magic: 0.4, true: 0.1 })).toBe('physical')
    expect(otherType('physical')).toBe('magic')
    expect(otherType('magic')).toBe('physical')
  })
})
