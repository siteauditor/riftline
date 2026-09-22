import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { SectionTitle } from './Stat'
import { queries } from '../lib/queries'
import { pct } from '../lib/format'

/**
 * The skins people actually wear, counted from live games.
 *
 * Riot publishes no skin for a finished game, so this board starts empty on
 * the day its table is created and fills as live games are looked up. Until
 * enough skins clear the floor it renders nothing at all: an empty section
 * would read as broken, and a thin one would rank whoever happened to be
 * looked up.
 */
export default function MostWornSkins() {
  const board = useQuery({
    ...queries.topSkins(),
    staleTime: 10 * 60 * 1000,
    retry: false,
  })
  const skins = board.data?.skins ?? []
  if (skins.length === 0) return null

  return (
    <section className="mx-auto max-w-[1280px] px-4 pb-12">
      <SectionTitle eyebrow="Live games" title="Most worn skins" />
      <p className="mt-1 max-w-[62ch] text-sm text-ink-dim">
        Counted from <span className="tnum">{board.data!.total.toLocaleString('en-US')}</span> players seen
        in live games looked up here. Riot does not say which skin anyone wore once a game is
        over, so this is the only way to count them. Base skins are left out.
      </p>
      <ol className="mt-4 grid grid-cols-[repeat(auto-fill,minmax(8.5rem,1fr))] gap-x-4 gap-y-5">
        {skins.map((skin) => (
          <li key={`${skin.champion.id}-${skin.num}`}>
            <Link to={`/champions/${skin.champion.slug ?? skin.champion.id}?tab=skins&skin=${skin.num}`} className="group block">
              <span className="block aspect-square overflow-hidden bg-raised ring-1 ring-line transition-[box-shadow] group-hover:ring-gold">
                {skin.tile_url && (
                  <img src={skin.tile_url} alt="" loading="lazy" className="size-full object-cover" />
                )}
              </span>
              <span className="mt-1.5 block truncate text-sm font-600 text-ink group-hover:text-gold-bright">
                {skin.name}
              </span>
              <span className="tnum block text-xs text-ink-faint">
                {skin.sightings} of {skin.champion_sightings} {skin.champion.name} (
                {pct(skin.sightings / skin.champion_sightings)})
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  )
}
