import { tierColor, tierLabel } from '../lib/format'
import { crestUrl } from '../lib/rankArt'

/**
 * A rank as a small inline pill.
 *
 * `RankCard` is the big version on a profile; this is the one that goes in a
 * roster row or beside a match, so it carries Riot's mini crest rather than the
 * full emblem: 2 KB of SVG, and the shape is what players read first.
 *
 * Four states, not two, and the extra two are the point. A player who hid their
 * identity is not unranked, and a lookup that did not finish is not unranked
 * either. Rendering all three as one grey "Unranked" would be three different
 * claims wearing the same label.
 */
export type RankState = 'ranked' | 'unranked' | 'hidden' | 'bot' | 'unknown'

interface Props {
  state?: RankState
  tier?: string | null
  division?: string | null
  leaguePoints?: number | null
  /** Apex tiers span thousands of LP, so the number carries the meaning. */
  showLp?: boolean
  size?: 'sm' | 'md'
  /**
   * Replaces the default tooltip. A caller that wraps this in its own titled
   * element gets nothing: the inner title always wins on hover.
   */
  title?: string
}

const COPY: Record<Exclude<RankState, 'ranked'>, { label: string; title: string }> = {
  unranked: {
    label: 'Unranked',
    title: 'This player has no ranked record in this queue.',
  },
  hidden: {
    label: 'Hidden',
    title:
      'This player hides their identity from third-party tools. Riot returns no ' +
      'account id for them, so their rank cannot be looked up.',
  },
  bot: { label: 'Bot', title: 'Not a player.' },
  unknown: {
    label: 'Unknown',
    title: 'We could not finish looking this rank up. It is not a claim that they are unranked.',
  },
}

export default function RankBadge({
  state = 'ranked',
  tier,
  division,
  leaguePoints,
  showLp = false,
  size = 'sm',
  title,
}: Props) {
  const pad = size === 'sm' ? 'px-1.5 py-0.5 text-[11px]' : 'px-2 py-1 text-xs'

  if (state !== 'ranked' || !tier) {
    const copy = COPY[state === 'ranked' ? 'unranked' : state]
    return (
      <span
        title={title ?? copy.title}
        className={`inline-flex shrink-0 items-center rounded-sm border border-dashed border-line ${pad} font-500 text-ink-faint`}
      >
        {copy.label}
      </span>
    )
  }

  const colour = tierColor(tier)
  return (
    <span
      title={
        title ??
        (leaguePoints != null
          ? `${tierLabel(tier, division)}, ${leaguePoints.toLocaleString()} LP`
          : tierLabel(tier, division))
      }
      className={`tnum inline-flex shrink-0 items-center gap-1 ${pad} font-600`}
      style={{
        color: colour,
        background: `color-mix(in srgb, ${colour} 14%, transparent)`,
      }}
    >
      <img
        src={crestUrl(tier)}
        alt=""
        aria-hidden
        loading="lazy"
        className={size === 'sm' ? 'size-3.5' : 'size-4'}
      />
      {tierLabel(tier, division)}
      {showLp && leaguePoints != null && (
        <span className="font-500 opacity-70">{leaguePoints.toLocaleString()} LP</span>
      )}
    </span>
  )
}
