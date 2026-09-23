import { useMemo, useState } from 'react'

import type { ChampionProfile, ChampionSkin } from '../../lib/api'
import { pct } from '../../lib/format'
import { Chip } from '@/components/ui/chips'

/**
 * Every skin, from Community Dragon's catalogue.
 *
 * Not Data Dragon's list, which counts each chroma as a skin of its own: Ahri
 * would read as 95 skins, 74 of them recolours with no art to show. Chromas
 * are counted on the skin they recolour instead.
 *
 * The grid loads square tiles (38 KB each, measured 2026-09-21) and only the
 * selected skin loads its splash (100 KB), so a 24 skin champion costs under
 * a megabyte rather than two and a half.
 */
export default function SkinsPanel({
  profile,
  initial,
}: {
  profile: ChampionProfile
  /** A skin number from the link, as the home page's skin board sends. */
  initial?: number | null
}) {
  const skins = profile.skins
  const name = profile.champion.name
  // The hero above already shows the base splash, so without a skin in the
  // link the stage opens on the newest skin instead of repeating it.
  const [selected, setSelected] = useState<number | null>(initial ?? null)
  const [line, setLine] = useState<string | null>(null)

  // Only lines with more than one skin become a filter. Most lines hold one
  // skin per champion, and a row of one-item filters is a list, not a choice.
  const lines = useMemo(() => {
    const counts = new Map<string, number>()
    for (const s of skins) if (s.line) counts.set(s.line, (counts.get(s.line) ?? 0) + 1)
    return [...counts].filter(([, n]) => n > 1).sort((a, b) => b[1] - a[1])
  }, [skins])

  if (skins.length === 0) {
    return (
      <p className="text-sm text-ink-faint">
        {name}'s skins have not loaded from Community Dragon yet.
      </p>
    )
  }

  const stage = skins.find((s) => s.num === selected) ?? skins[skins.length - 1]
  const shown = line ? skins.filter((s) => s.line === line) : skins
  const counted = skins.some((s) => s.sightings !== null)

  return (
    <div>
      <Stage skin={stage} champion={name} total={profile.skin_sightings} />

      <p className="mt-3 max-w-prose text-xs leading-relaxed text-ink-faint">
        {sightingNote(name, profile.skin_sightings, profile.skin_sightings_floor, counted)}
      </p>

      <div className="mt-6 flex flex-wrap items-center gap-2 text-sm">
        <span className="display mr-1 text-base font-600 text-ink">
          {skins.length} skins
        </span>
        {lines.length > 0 && (
          <>
            <Chip active={line === null} onClick={() => setLine(null)}>
              All
            </Chip>
            {lines.map(([label, n]) => (
              <Chip key={label} active={line === label} onClick={() => setLine(label)}>
                {label}
                {/* Its own chip, because "Star Guardian Season 2 2" is a
                    puzzle when the count sits in the same run of text. */}
                <span className="tnum ml-1.5 bg-raised px-1 text-xs text-ink-faint">{n}</span>
              </Chip>
            ))}
          </>
        )}
      </div>

      <ul className="mt-4 grid grid-cols-[repeat(auto-fill,minmax(6.5rem,1fr))] gap-x-3 gap-y-5">
        {shown.map((skin) => (
          <li key={skin.id}>
            <button
              type="button"
              onClick={() => setSelected(skin.num)}
              aria-pressed={skin.num === stage.num}
              className="group block w-full text-left"
            >
              <span
                className={`relative block aspect-square overflow-hidden bg-raised ring-1 transition-[box-shadow] ${
                  skin.num === stage.num ? 'ring-2 ring-gold' : 'ring-line group-hover:ring-ink-faint'
                }`}
              >
                {skin.tile_url && (
                  <img
                    src={skin.tile_url}
                    alt=""
                    loading="lazy"
                    className="size-full object-cover"
                  />
                )}
                {skin.sightings !== null && profile.skin_sightings > 0 && (
                  <span
                    className="absolute inset-x-0 bottom-0 h-1 bg-deep/70"
                    aria-hidden
                  >
                    <span
                      className="block h-full bg-accent"
                      style={{ width: `${(skin.sightings / profile.skin_sightings) * 100}%` }}
                    />
                  </span>
                )}
              </span>
              <span
                className="mt-1.5 block truncate text-sm font-600 text-ink group-hover:text-gold-bright"
                title={skin.name}
              >
                {skin.num === 0 ? 'Original' : shortName(skin.name, name)}
              </span>
              <span className="block truncate text-xs text-ink-faint">
                {[skin.rarity, skin.legacy ? 'Legacy' : null].filter(Boolean).join(', ') ||
                  (skin.num === 0 ? 'Base skin' : ' ')}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Stage({ skin, champion, total }: { skin: ChampionSkin; champion: string; total: number }) {
  const facts = [
    skin.rarity,
    skin.legacy ? 'Legacy' : null,
    skin.chromas > 0 ? `${skin.chromas} ${skin.chromas === 1 ? 'chroma' : 'chromas'}` : null,
  ].filter(Boolean)

  return (
    <figure className="notch relative isolate overflow-hidden border border-line bg-panel">
      {skin.splash_url && (
        <img
          // Keyed, so a new skin replaces the old image instead of the old one
          // lingering until the new splash arrives.
          key={skin.splash_url}
          src={skin.splash_url}
          alt={`${skin.num === 0 ? champion : skin.name} splash art`}
          className="aspect-[16/9] max-h-[30rem] w-full object-cover object-[50%_22%]"
        />
      )}
      <figcaption className="art-scrim absolute inset-0 flex flex-col justify-end p-4 sm:p-6">
        {skin.line && <p className="eyebrow">{skin.line}</p>}
        <p className="display mt-1 text-[clamp(1.6rem,4vw,2.6rem)] font-800 uppercase leading-[0.95] text-ink">
          {skin.num === 0 ? champion : skin.name}
        </p>
        {facts.length > 0 && <p className="mt-1.5 text-sm text-ink-dim">{facts.join(', ')}</p>}
        {skin.sightings !== null && total > 0 && (
          <p className="tnum mt-1 text-sm text-ink-dim">
            Worn in <span className="font-600 text-ink">{pct(skin.sightings / total)}</span> of{' '}
            {total} live sightings
          </p>
        )}
        {skin.description && (
          <p className="mt-3 hidden max-w-[60ch] text-sm leading-relaxed text-ink-dim sm:block">
            {skin.description}
          </p>
        )}
      </figcaption>
    </figure>
  )
}


/**
 * What the counts stand on. Riot publishes no skin for a finished game, so the
 * only source is live games, counted as they are looked up here.
 */
function sightingNote(champion: string, total: number, floor: number, counted: boolean): string {
  const how =
    'Riot does not publish which skin anyone wore in a finished game, so we count them in live games as people look those games up here.'
  if (counted) return `${how} The bars show the share of ${total} sightings of ${champion}.`
  if (total === 0) return `${how} We have not seen ${champion} in a live game yet.`
  return `${how} We have seen ${champion} ${total} ${total === 1 ? 'time' : 'times'}; the counts appear at ${floor}.`
}

/**
 * A skin's name without its champion's, for a tile under a heading that
 * already names the champion: "Cowgirl" rather than "Cowgirl Miss Fortune",
 * which truncated to "Cowgirl Miss For..." at phone width. The full name stays
 * on the stage and in the tooltip.
 */
function shortName(skin: string, champion: string): string {
  const short = skin.split(champion).map((part) => part.trim()).filter(Boolean).join(' ')
  return short || skin
}
