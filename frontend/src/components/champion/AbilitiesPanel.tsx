import type { ChampionAbility, ChampionDetail, FacetEntry } from '../../lib/api'
import { compact, pct, positionLabel } from '../../lib/format'
import { SLOT_KEY } from './tabs'

interface Props {
  /** From the profile. Empty while it loads or when Riot's file is missing. */
  passive: ChampionAbility | null
  abilities: ChampionAbility[]
  /** From the numbers. Absent on a patch with no games for this champion. */
  skills?: ChampionDetail['skills']
  /** What the skill figures were counted over, for the sentence that says so. */
  slice?: { patch: string; position: string }
  championName: string
}

/**
 * The passive and the four abilities, and what our own games say about each.
 *
 * Riot's text is `description`, never `tooltip`: the tooltip is written against
 * `{{ totaldamage }}` placeholders that only resolve inside the client. Skill
 * priority and level-up order live here rather than under Laning, which is
 * about minute 14 and only held them because there was nowhere else.
 */
export default function AbilitiesPanel({ passive, abilities, skills, slice, championName }: Props) {
  const first = shares(skills?.first ?? [], (e) => e.ids[0])
  const maxedFirst = shares(skills?.priority ?? [], (e) => e.ids[0])
  const hasNumbers = first.total > 0 || maxedFirst.total > 0
  const bySlot = (slot: number) => abilities[slot - 1]

  return (
    <div className="space-y-8">
      {abilities.length === 0 && !passive ? (
        <p className="text-sm text-ink-faint">
          {championName}'s abilities have not loaded from Riot's data files yet. The skill
          figures below still come from our own games.
        </p>
      ) : (
        <section aria-label={`${championName}'s abilities`}>
          {hasNumbers && slice && (
            <p className="mb-3 text-xs text-ink-faint">
              Level 1 and max order from {compact(Math.max(first.total, maxedFirst.total))} games
              with a timeline, {positionLabel(slice.position)} on patch {slice.patch}.
            </p>
          )}
          <ol className="border-t border-line-soft">
            {passive && <AbilityRow ability={passive} />}
            {abilities.map((ability, i) => (
              <AbilityRow
                key={ability.slot}
                ability={ability}
                // The ultimate is on a fixed schedule; a share for it would be
                // a statement about Riot's rules, not about players.
                figures={
                  i < 3
                    ? [
                        first.total > 0 && {
                          label: 'Taken at level 1',
                          value: pct(first.by.get(i + 1) ?? 0),
                        },
                        maxedFirst.total > 0 && {
                          label: 'Maxed first',
                          value: pct(maxedFirst.by.get(i + 1) ?? 0),
                        },
                      ].filter((f): f is { label: string; value: string } => Boolean(f))
                    : []
                }
              />
            ))}
          </ol>
        </section>
      )}

      {skills && skills.priority.length > 0 && (
        <section>
          <div className="mb-2 flex flex-wrap items-baseline gap-x-3">
            <h3 className="display text-base font-600 text-ink">Skill priority</h3>
            <p className="text-xs text-ink-faint">
              Which abilities get maxed, and in what order. The ultimate is on a fixed schedule,
              so it is not a choice and is left out.
            </p>
          </div>
          <div className="border-t border-line-soft">
            {skills.priority.map((entry) => (
              <SkillRow key={entry.ids.join()} entry={entry} ability={bySlot} arrows />
            ))}
          </div>
        </section>
      )}

      {skills && skills.order.length > 0 && (
        <section>
          <div className="mb-2 flex flex-wrap items-baseline gap-x-3">
            <h3 className="display text-base font-600 text-ink">Level-up order</h3>
            <p className="text-xs text-ink-faint">The first fifteen points, in sequence.</p>
          </div>
          <div className="border-t border-line-soft">
            {skills.order.map((entry) => (
              <SkillRow key={entry.ids.join()} entry={entry} ability={bySlot} />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

/** Share of games per slot, keyed by what `slotOf` reads off each entry. */
function shares(entries: FacetEntry[], slotOf: (e: FacetEntry) => number | undefined) {
  const games = new Map<number, number>()
  let total = 0
  for (const entry of entries) {
    const slot = slotOf(entry)
    if (slot === undefined) continue
    games.set(slot, (games.get(slot) ?? 0) + entry.games)
    total += entry.games
  }
  const by = new Map<number, number>()
  for (const [slot, n] of games) by.set(slot, total ? n / total : 0)
  return { by, total }
}

function AbilityRow({
  ability,
  figures = [],
}: {
  ability: ChampionAbility
  figures?: { label: string; value: string }[]
}) {
  const meta = [
    ability.cooldown && { label: 'Cooldown', value: `${ability.cooldown}s` },
    ability.cost && { label: 'Cost', value: ability.cost },
    ability.range && { label: 'Range', value: ability.range },
  ].filter((m): m is { label: string; value: string } => Boolean(m))

  return (
    <li className="grid grid-cols-[3rem_minmax(0,1fr)] gap-x-4 gap-y-2 border-b border-line-soft py-4 sm:grid-cols-[3rem_minmax(0,1fr)_12rem]">
      <AbilityIcon ability={ability} size={48} />
      <div className="min-w-0">
        <h3 className="display text-lg font-700 leading-tight text-ink">{ability.name}</h3>
        {meta.length > 0 && (
          <dl className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs">
            {meta.map((m) => (
              <div key={m.label} className="flex gap-1.5">
                <dt className="text-ink-faint">{m.label}</dt>
                <dd className="tnum text-ink-dim">{m.value}</dd>
              </div>
            ))}
          </dl>
        )}
        <p className="mt-2 max-w-[70ch] whitespace-pre-line text-sm leading-relaxed text-ink-dim">
          {ability.description}
        </p>
      </div>
      {figures.length > 0 && (
        <dl className="col-start-2 flex gap-6 sm:col-start-3 sm:flex-col sm:gap-2 sm:text-right">
          {figures.map((f) => (
            <div key={f.label}>
              <dt className="text-xs text-ink-faint">{f.label}</dt>
              <dd className="tnum display text-xl font-700 text-ink">{f.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </li>
  )
}

/** The icon with its key in the corner, or the bare key when there is no icon. */
function AbilityIcon({ ability, size }: { ability: ChampionAbility | undefined; size: number }) {
  const key = ability?.slot ?? '?'
  return (
    <span
      className="relative grid shrink-0 place-items-center bg-raised ring-1 ring-line"
      style={{ width: size, height: size }}
      title={ability ? `${key}: ${ability.name}` : undefined}
    >
      {ability?.icon_url ? (
        <img src={ability.icon_url} alt="" loading="lazy" className="size-full object-cover" />
      ) : (
        <span className="font-display text-xs font-700 text-ink">{key}</span>
      )}
      {ability?.icon_url && (
        <span className="absolute bottom-0 right-0 bg-deep/85 px-[3px] font-display text-[10px] font-700 leading-[13px] text-ink">
          {key === 'P' ? '' : key}
        </span>
      )}
    </span>
  )
}

function SkillRow({
  entry,
  ability,
  arrows,
}: {
  entry: FacetEntry
  ability: (slot: number) => ChampionAbility | undefined
  arrows?: boolean
}) {
  return (
    <div className="flex items-center gap-2.5 border-b border-line-soft px-2 py-2 lift">
      <div className="flex flex-wrap items-center gap-1">
        {entry.ids.map((slot, i) => {
          const found = ability(slot)
          return (
            <span key={i} className="flex items-center gap-1">
              {arrows && i > 0 && <span className="text-xs text-ink-faint">&rsaquo;</span>}
              {found ? (
                <AbilityIcon ability={found} size={arrows ? 32 : 24} />
              ) : (
                <span
                  className="grid size-6 place-items-center bg-raised font-display text-xs font-700 text-ink"
                  title={`Ability ${SLOT_KEY[slot - 1] ?? slot}`}
                >
                  {SLOT_KEY[slot - 1] ?? slot}
                </span>
              )}
            </span>
          )
        })}
      </div>
      <div className="ml-auto shrink-0 text-right">
        <p
          className="tnum text-sm font-600"
          style={{
            color:
              entry.win_rate >= 0.55
                ? 'var(--color-gold-bright)'
                : entry.win_rate >= 0.5
                  ? 'var(--color-win)'
                  : 'var(--color-ink-dim)',
          }}
        >
          {pct(entry.win_rate, 1)}
        </p>
        <p className="tnum text-xs text-ink-faint">
          {compact(entry.games)} games, {pct(entry.pick_rate)}
        </p>
      </div>
    </div>
  )
}
