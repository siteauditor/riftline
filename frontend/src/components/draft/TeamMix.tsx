import type { DraftResponse } from '../../lib/api'
import { DAMAGE_TYPES, otherType } from '../../lib/damage'
import { pct } from '../../lib/format'

const names = new Intl.ListFormat('en-US', { type: 'conjunction' })

/**
 * One side's damage by type, from each of its champions' usual games: a bar and
 * the figures under the picks. Shown, not scored: the draft states the mix and
 * leaves the judgement to the player.
 *
 * The API says when a figure cannot be given: before the stored games carry
 * the damage types (the deploy that added them backfills within minutes), and
 * for a champion with too few games, which is left out and named.
 */
export default function TeamMix({
  damage,
  side,
}: {
  damage: DraftResponse['team_damage'] | undefined
  side: 'allies' | 'enemies'
}) {
  const mix = damage?.[side]
  if (!damage || !mix) return null
  const note = 'mt-1.5 text-[11px] leading-snug text-ink-faint'
  if (!damage.available) {
    return <p className={note}>Damage mix: not measured yet.</p>
  }
  const shares = mix.shares
  const missing = mix.missing.map((c) => c.name)
  if (!shares) {
    return (
      <p className={note}>
        Damage mix: {names.format(missing)} {missing.length === 1 ? 'has' : 'have'} under {damage.min_games}{' '}
        games so far.
      </p>
    )
  }
  // The bar sits beside the figures rather than above them. On a phone, with
  // three picks a side, a bar on its own line under each side put the first
  // suggestion at 855 px, past an 844 px screen; beside the figures, 831 px.
  return (
    <div className="mt-1.5 flex items-start gap-2 text-[11px] leading-snug text-ink-faint">
      <span aria-hidden className="mt-1 flex h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-line">
        {DAMAGE_TYPES.map((t) => (
          <span key={t.key} className={t.bar} style={{ width: `${(shares[t.key] * 100).toFixed(1)}%` }} />
        ))}
      </span>
      <p className="tnum min-w-0">
        {DAMAGE_TYPES.map((t, i) => (
          <span key={t.key}>
            {i > 0 && ', '}
            <span className={t.text}>
              {pct(shares[t.key], 0)} {t.key}
            </span>
          </span>
        ))}{' '}
        damage
        {missing.length > 0 && `, without ${names.format(missing)} (under ${damage.min_games} games)`}.
        {mix.leaning &&
          (side === 'allies'
            ? ` Mostly ${mix.leaning}: picks that deal mostly ${otherType(mix.leaning)} are marked.`
            : ` Mostly ${mix.leaning}.`)}
      </p>
    </div>
  )
}
