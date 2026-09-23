import type { CSSProperties, ReactNode } from 'react'

/**
 * The band at the top of the live page that says what state it is in.
 *
 * One object for all three states, because they are the same fact answered
 * differently: in a game, the game just ended, or not playing. The rule down
 * the left carries the subject's own rank colour, the site's repeated motif.
 */
export default function StatusBand({
  accent,
  iconUrl,
  title,
  detail,
  aside,
}: {
  accent: string
  iconUrl?: string | null
  title: ReactNode
  detail?: ReactNode
  aside?: ReactNode
}) {
  return (
    <section
      className="accent-edge flex flex-wrap items-center gap-x-4 gap-y-3 bg-panel/50 py-3 pl-4 pr-3"
      style={{ '--accent': accent } as CSSProperties}
    >
      {/* The text keeps a floor of 14rem, so on a phone the countdown wraps to
          its own line instead of squeezing the title into four words tall. */}
      <div className="flex min-w-[14rem] flex-1 items-center gap-4">
        {iconUrl && (
          <img src={iconUrl} alt="" className="size-10 shrink-0 ring-1 ring-line" loading="lazy" decoding="async" />
        )}
        <div className="min-w-0">
          <p className="display text-lg font-700 leading-tight text-ink">{title}</p>
          {detail && <p className="mt-0.5 text-xs text-ink-dim">{detail}</p>}
        </div>
      </div>
      {aside && <div className="shrink-0">{aside}</div>}
    </section>
  )
}
