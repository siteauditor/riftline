import type { ChampionBaseStat, ChampionProfile } from '../../lib/api'

/**
 * Who the champion is: the story, Riot's own ratings, the base stats, and the
 * tips Riot wrote for each side of the matchup.
 *
 * Nothing here is ours and nothing depends on a sample, so it renders on a
 * patch where the numbers tabs have nothing to say.
 */
export default function StoryPanel({ profile }: { profile: ChampionProfile }) {
  const name = profile.champion.name
  // The long lore needs the optional file; the short one is always there.
  const story = profile.lore ?? profile.blurb

  return (
    <div className="grid gap-x-10 gap-y-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="min-w-0">
        {story ? (
          <section aria-label={`${name}'s story`}>
            {/* A reading measure, not the panel's width: at 1280px a line of
                lore would run past 150 characters. */}
            <p className="max-w-[62ch] whitespace-pre-line text-[15px] leading-[1.75] text-ink-dim">
              {story}
            </p>
            {!profile.lore && (
              <p className="mt-2 text-xs text-ink-faint">
                The short version. The full story has not loaded from Riot's data files yet.
              </p>
            )}
          </section>
        ) : (
          <p className="text-sm text-ink-faint">Riot has not published a story for {name}.</p>
        )}

        {(profile.ally_tips.length > 0 || profile.enemy_tips.length > 0) && (
          <div className="mt-8 grid gap-6 sm:grid-cols-2">
            <Tips title={`Playing ${name}`} tips={profile.ally_tips} />
            <Tips title={`Playing against ${name}`} tips={profile.enemy_tips} />
          </div>
        )}
      </div>

      <aside className="space-y-7">
        {profile.ratings.length > 0 && (
          <section>
            <h3 className="display text-base font-600 text-ink">Riot's ratings</h3>
            <p className="mt-0.5 text-xs text-ink-faint">Out of ten, as the client shows them.</p>
            <dl className="mt-3 space-y-2.5">
              {profile.ratings.map((r) => (
                <div key={r.key} className="grid grid-cols-[5.5rem_1fr_1.5rem] items-center gap-3">
                  <dt className="text-sm text-ink-dim">{r.label}</dt>
                  <dd className="contents">
                    <Segments value={r.value} label={`${r.label} ${r.value} of 10`} />
                    <span className="tnum text-right text-sm font-600 text-ink">{r.value}</span>
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        )}

        {profile.stats.length > 0 && (
          <section>
            <h3 className="display text-base font-600 text-ink">Base stats</h3>
            <p className="mt-0.5 text-xs text-ink-faint">
              Before items and runes. Regeneration is per five seconds.
            </p>
            <table className="mt-3 w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-line text-xs text-ink-faint">
                  <th className="py-1.5 text-left font-500">Stat</th>
                  <th className="py-1.5 text-right font-500">Level 1</th>
                  <th className="py-1.5 text-right font-500">Level 18</th>
                </tr>
              </thead>
              <tbody>
                {profile.stats.map((s) => (
                  <tr key={s.key} className="border-b border-line-soft">
                    <td className="py-1.5 text-ink-dim">{s.label}</td>
                    <td className="tnum py-1.5 text-right text-ink">{formatStat(s, s.level1)}</td>
                    <td className="tnum py-1.5 text-right text-ink">
                      {s.level18 === null ? (
                        s.growth_published === false ? (
                          <span
                            className="text-ink-faint"
                            title="Riot's data files list this growth as zero for every champion this patch, which cannot be right, so the level 18 figure is left out rather than printed equal to level 1."
                          >
                            not published
                          </span>
                        ) : (
                          <span className="text-ink-faint" title="Does not grow with level">
                            same
                          </span>
                        )
                      ) : (
                        formatStat(s, s.level18)
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
      </aside>
    </div>
  )
}

function Tips({ title, tips }: { title: string; tips: string[] }) {
  if (tips.length === 0) return null
  return (
    <section>
      <h3 className="display text-base font-600 text-ink">{title}</h3>
      <ul className="mt-2 space-y-2">
        {tips.map((tip) => (
          <li key={tip} className="border-l-2 border-line pl-3 text-sm leading-relaxed text-ink-dim">
            {tip}
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Ten cells, filled to the value: a rating reads as a count, not a gauge. */
function Segments({ value, label }: { value: number; label: string }) {
  return (
    <span role="img" aria-label={label} className="grid grid-cols-10 gap-[3px]">
      {Array.from({ length: 10 }, (_, i) => (
        <span
          key={i}
          className={`h-2 ${i < value ? 'bg-accent' : 'bg-raised'}`}
        />
      ))}
    </span>
  )
}

function formatStat(stat: ChampionBaseStat, value: number): string {
  // Attack speed is read to three places in game; everything else is whole
  // numbers apart from the regeneration rates.
  if (stat.key === 'attackspeed') return value.toFixed(3)
  if (stat.key.endsWith('regen')) return value.toFixed(1)
  return Math.round(value).toLocaleString('en-US')
}
