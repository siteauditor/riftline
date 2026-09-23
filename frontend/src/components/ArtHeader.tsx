import type { ReactNode } from 'react'

/**
 * A page header with the subject's own art behind it.
 *
 * Every reference that reads as a game site puts art in the background layer
 * and the type straight on top of it: Riot's own pages are full-bleed splash
 * with a scrim, and Blitz and Lolalytics run champion art as a watermark inside
 * their headers. This site used 48px icons on nine pages out of ten, which is
 * what made it read as a spreadsheet.
 *
 * The art is always the subject of the page, never decoration: the champion on
 * a champion page, the player's most-played champion on a profile, the top pick
 * on the tier list. A page with no subject gets no art rather than a stock
 * background, because a stock background would be saying nothing loudly.
 */
export default function ArtHeader({
  art,
  children,
  tall = false,
}: {
  /** Centred splash art, or null when the page has no subject yet. */
  art?: string | null
  children: ReactNode
  tall?: boolean
}) {
  return (
    <section className="relative isolate overflow-hidden border-b border-line-soft">
      {art && (
        <img
          src={art}
          alt=""
          aria-hidden
          // Off to the right and high: splash art puts the face around a third
          // in, and the type sits on the left, so this keeps them apart.
          className="pointer-events-none absolute inset-0 size-full object-cover object-[70%_22%] opacity-60"
          // The page's largest image, so the first one fetched.
          fetchPriority="high"
        />
      )}
      <span aria-hidden className="art-scrim absolute inset-0" />
      <div
        className={`reveal relative mx-auto max-w-[1280px] px-4 ${tall ? 'py-12 sm:py-16' : 'py-7 sm:py-9'}`}
      >
        {children}
      </div>
    </section>
  )
}
