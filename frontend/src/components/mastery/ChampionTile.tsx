import type { CSSProperties } from 'react'

import Hint from '../Hint'
import type { PoolChampion } from './pool'
import { levelStep, TILE_SIZE, type TileSize } from './scale'
import { compact, timeAgo } from '../../lib/format'

export default function ChampionTile({
  champion,
  size,
  selected,
  onSelect,
  now,
}: {
  champion: PoolChampion
  size: TileSize
  selected: boolean
  onSelect: (champion: PoolChampion) => void
  /** The page's reading of the clock, for "played 3d ago". */
  now: number
}) {
  const step = levelStep(champion.level)
  const px = TILE_SIZE[size]
  // The number is drawn on the two larger sizes only. At 32px a 10px badge
  // takes a third of the tile and the tail stops reading as texture, so there
  // the level lives in the label and the tooltip instead.
  const showLevel = size !== 'tail' && champion.level > 0
  const text = label(champion, now)

  return (
    <Hint text={text}>
      <button
        type="button"
        id={`mastery-tile-${champion.id}`}
        data-tile={champion.id}
        data-level-step={champion.level}
        data-corpus={champion.record ? 'true' : 'false'}
        onClick={() => onSelect(champion)}
        aria-label={text}
        style={{ width: px, height: px, '--tile-ring': step.color } as CSSProperties}
        className={`relative shrink-0 overflow-hidden transition-transform hover:z-10 hover:scale-110 ${
          selected ? 'outline outline-2 outline-offset-2 outline-ink' : ''
        }`}
      >
        <span
          aria-hidden
          className="absolute inset-0"
          style={{ boxShadow: `inset 0 0 0 2px ${step.color}` }}
        />
        {champion.iconUrl ? (
          <img
            src={champion.iconUrl}
            alt=""
            loading="lazy"
            className="size-full object-cover"
            style={champion.points ? undefined : { filter: 'grayscale(1)', opacity: 0.35 }}
          />
        ) : (
          // A champion Riot named and Data Dragon does not list yet. There is no
          // art to draw and a broken image would read as our failure.
          <span className="grid size-full place-items-center bg-raised text-ink-faint">?</span>
        )}

        {showLevel && (
          <span
            className="tnum absolute bottom-0 right-0 px-1 text-[10px] font-700 leading-tight"
            style={{ background: step.color, color: step.ink }}
          >
            {champion.level}
          </span>
        )}

        {/* Teal, the interface colour, because it means there is more to see on
            this one. The slot is always in the DOM so a late analytics answer
            cannot reflow a grid of 173 tiles. */}
        <span
          aria-hidden
          className={`absolute left-0 top-0 size-1.5 ${champion.record ? 'bg-accent-bright' : ''}`}
        />
      </button>
    </Hint>
  )
}

function label(champion: PoolChampion, now: number): string {
  const parts = [champion.name]
  if (champion.points > 0) {
    parts.push(`level ${champion.level}`, `${compact(champion.points)} points`)
    if (champion.lastPlayed) parts.push(`played ${timeAgo(champion.lastPlayed, now)}`)
    if (champion.record) parts.push(`${champion.record.games} stored games`)
  } else {
    parts.push('never played')
  }
  return parts.join(', ')
}
