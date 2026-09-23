import { useState } from 'react'
import type { ReactNode } from 'react'

import ChampionTile from './ChampionTile'
import { TILE_SIZE, type TileSize } from './scale'
import type { Band, PoolChampion } from './pool'
import { SectionTitle } from '../Stat'
import { buttonVariants } from '@/components/ui/button'

/**
 * Below `sm` the tail is clamped to four rows of 32px tiles, which is 36
 * champions at 390 and enough to read it as texture. Fourteen unbroken rows of
 * grey squares is the wall this page exists to remove, and it only happens on a
 * phone: a desktop tail is four to six rows and is never clamped.
 */
const PHONE_TAIL_ROWS = 36

export default function BandSection({
  band,
  champions,
  size,
  eyebrow,
  title,
  aside,
  selectedId,
  onSelect,
  collapsible = false,
  gap = 8,
}: {
  band: Band
  /** Already filtered, so a section can be empty while the band is not. */
  champions: PoolChampion[]
  size: TileSize
  eyebrow: string
  title: string
  aside: ReactNode
  selectedId: number | null
  onSelect: (champion: PoolChampion) => void
  /** The unplayed band, which is most of the roster on a new account. */
  collapsible?: boolean
  gap?: number
}) {
  const [open, setOpen] = useState(!collapsible)
  const [showAll, setShowAll] = useState(false)

  // A band with nothing in it renders nothing at all: no heading, no rule. That
  // is what lets the smallest pool in the corpus (8 champions) read as one core
  // champion, one middle and six tail rather than as three headings and a gap.
  if (champions.length === 0) return null

  // Clamped in CSS rather than by slicing the array, so the desktop tail keeps
  // every champion and only the phone gets the button.
  const clamped = size === 'tail' && !showAll && champions.length > PHONE_TAIL_ROWS

  return (
    <section data-band={band.id}>
      <SectionTitle
        eyebrow={eyebrow}
        title={title}
        aside={
          <span className="flex items-center gap-3">
            {aside}
            {collapsible && (
              <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                aria-expanded={open}
                className={buttonVariants({ variant: 'outline', size: 'xs', className: 'font-600' })}
              >
                {open ? 'Hide' : 'Show'}
              </button>
            )}
          </span>
        }
      />
      {open && (
        <>
          <div
            className={`mt-3 grid justify-start ${clamped ? 'max-h-[144px] overflow-hidden sm:max-h-none sm:overflow-visible' : ''}`}
            style={{
              gridTemplateColumns: `repeat(auto-fill, ${TILE_SIZE[size]}px)`,
              gap,
            }}
          >
            {champions.map((champion) => (
              <ChampionTile
                key={champion.id}
                champion={champion}
                size={size}
                selected={champion.id === selectedId}
                onSelect={onSelect}
              />
            ))}
          </div>
          {clamped && (
            <button
              type="button"
              onClick={() => setShowAll(true)}
              className="mt-3 text-xs text-ink-dim underline decoration-line underline-offset-2 hover:text-gold-bright sm:hidden"
            >
              Show all {champions.length} champions
            </button>
          )}
        </>
      )}
    </section>
  )
}
