import { useState } from 'react'

import type { LiveParticipant } from '../../lib/api'
import { compact, pct, positionLabel, timeAgo } from '../../lib/format'

/**
 * The skin a player is wearing, or the champion's base art if that image fails.
 *
 * A chroma used to fail here: spectator reports it by its own number, Community
 * Dragon has no art for it, and the card showed a broken image with the
 * champion's name in it. The server now maps a chroma to the skin it recolours,
 * and this is the net under anything else the image host does not have. The
 * failed URL is remembered rather than a flag, so the next game's skin is still
 * tried.
 */
export function SkinArt({ p, className }: { p: LiveParticipant; className: string }) {
  const [failed, setFailed] = useState<string | null>(null)
  const preferred = p.skin_tile_url
  const src = preferred && preferred !== failed ? preferred : p.champion.icon_url
  if (!src) return null
  return (
    <img
      src={src}
      alt={p.champion.name}
      className={className}
      loading="lazy"
      onError={() => {
        if (src === preferred) setFailed(preferred)
      }}
    />
  )
}

export function MasteryChip({ p }: { p: LiveParticipant }) {
  // Not known: the lookup did not finish, which says nothing about the player.
  if (!p.mastery_known) return null
  if (!p.mastery) {
    return (
      <span
        className="text-[11px] text-ink-faint"
        title={`Riot reports no mastery on ${p.champion.name} for this player, so this may be their first game on it.`}
      >
        No mastery
      </span>
    )
  }
  const m = p.mastery
  return (
    <span
      className="tnum whitespace-nowrap text-[11px] text-ink-dim"
      title={
        `Mastery ${m.level} on ${p.champion.name}, ${m.points.toLocaleString()} points` +
        (m.last_play_time ? `. Last played ${timeAgo(m.last_play_time)}.` : '.')
      }
    >
      <span className="font-600 text-gold-bright">M{m.level}</span> {compact(m.points)}
    </span>
  )
}

export function RoleRecord({ p }: { p: LiveParticipant }) {
  const r = p.champion_record
  if (!r) return null
  return (
    // "Champ WR", not "Pick": on the tier list "Pick" is the pick rate, and one
    // word meaning two numbers on one site is how people misread both.
    <span
      className="tnum whitespace-nowrap text-[11px] text-ink-faint"
      title={`${p.champion.name} as ${positionLabel(p.position)} in our stored games: ${r.wins} wins, ${r.games - r.wins} losses, ${pct(r.win_rate, 1)}. This is the champion, not this player.`}
    >
      Champ WR {pct(r.win_rate)}
    </span>
  )
}

export function Loadout({ p }: { p: LiveParticipant }) {
  return (
    <span className="flex items-center gap-0.5">
      {p.spells.map((s, i) => (
        <img
          key={`${s.id}-${i}`}
          src={s.icon_url ?? undefined}
          alt={s.name ?? ''}
          title={s.name ?? ''}
          className="size-4 rounded-sm bg-raised"
          loading="lazy"
        />
      ))}
      {p.keystone?.icon_url && (
        <span className="ml-0.5 grid size-4 place-items-center rounded-full bg-raised">
          <img src={p.keystone.icon_url} alt="" className="size-3.5" loading="lazy" />
        </span>
      )}
      {p.secondary_tree?.icon_url && (
        <img src={p.secondary_tree.icon_url} alt="" className="size-3" loading="lazy" />
      )}
    </span>
  )
}
