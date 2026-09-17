import type { ReactElement } from 'react'

/**
 * Lane position glyphs: Riot's own, from the client.
 *
 * The geometry is copied verbatim out of
 * `rcp-fe-lol-static-assets/global/default/svg/position-{lane}.svg`, mirrored by
 * Community Dragon, which is the same asset family this app already reads
 * champion, item and profile art from. These are the shapes League players
 * already know, so drawing lookalikes was the wrong call.
 *
 * Two things changed on the way in, both deliberate:
 *
 * * Riot's fills (#c8aa6e for the lane, #785a28 at half opacity for the rest of
 *   the frame) become `currentColor`, so an icon takes the colour of whatever it
 *   sits in: gold on an active filter, dim on an inactive one, faint in a table
 *   row. Fetching the files instead would fix them to client gold.
 * * They are inlined rather than referenced. A CSS `mask` would flatten the two
 *   layers into one silhouette, and since the quiet layer is the *rest* of the
 *   frame, top and bottom would come out identical.
 *
 * `fillRule="evenodd"` is load-bearing: those paths cut their own holes.
 */

/** The dim half: the frame the lane is not in. Riot draws this at 0.5 opacity. */
const QUIET = 0.42

const SHAPES: Record<string, ReactElement> = {
  TOP: (
    <>
      <path
        opacity={QUIET}
        fill="currentColor"
        fillRule="evenodd"
        d="M21,14H14v7h7V14Zm5-3V26L11.014,26l-4,4H30V7.016Z"
      />
      <polygon
        fill="currentColor"
        points="4 4 4.003 28.045 9 23 9 9 23 9 28.045 4.003 4 4"
      />
    </>
  ),
  JUNGLE: (
    <path
      fill="currentColor"
      fillRule="evenodd"
      d="M25,3c-2.128,3.3-5.147,6.851-6.966,11.469A42.373,42.373,0,0,1,20,20a27.7,27.7,0,0,1,1-3C21,12.023,22.856,8.277,25,3ZM13,20c-1.488-4.487-4.76-6.966-9-9,3.868,3.136,4.422,7.52,5,12l3.743,3.312C14.215,27.917,16.527,30.451,17,31c4.555-9.445-3.366-20.8-8-28C11.67,9.573,13.717,13.342,13,20Zm8,5a15.271,15.271,0,0,1,0,2l4-4c0.578-4.48,1.132-8.864,5-12C24.712,13.537,22.134,18.854,21,25Z"
    />
  ),
  MIDDLE: (
    <>
      <path
        opacity={QUIET}
        fill="currentColor"
        fillRule="evenodd"
        d="M30,12.968l-4.008,4L26,26H17l-4,4H30ZM16.979,8L21,4H4V20.977L8,17,8,8h8.981Z"
      />
      <polygon
        fill="currentColor"
        points="25 4 4 25 4 30 9 30 30 9 30 4 25 4"
      />
    </>
  ),
  BOTTOM: (
    <>
      <path
        opacity={QUIET}
        fill="currentColor"
        fillRule="evenodd"
        d="M13,20h7V13H13v7ZM4,4V26.984l3.955-4L8,8,22.986,8l4-4H4Z"
      />
      <polygon
        fill="currentColor"
        points="29.997 5.955 25 11 25 25 11 25 5.955 29.997 30 30 29.997 5.955"
      />
    </>
  ),
  UTILITY: (
    <path
      fill="currentColor"
      fillRule="evenodd"
      d="M26,13c3.535,0,8-4,8-4H23l-3,3,2,7,5-2-3-4h2ZM22,5L20.827,3H13.062L12,5l5,6Zm-5,9-1-1L13,28l4,3,4-3L18,13ZM11,9H0s4.465,4,8,4h2L7,17l5,2,2-7Z"
    />
  ),
  /*
   * "All" has no Riot glyph, because in the client every position is a choice
   * and "all of them" is not one. Built from the same 34-unit grid and the same
   * cut corner as the lane frames, so it belongs to the row it sits in.
   */
  ALL: (
    <>
      <path
        opacity={QUIET}
        fill="currentColor"
        d="M18.5,18.5h12v12h-12ZM3.5,3.5h12v12H3.5Z"
      />
      <path fill="currentColor" d="M18.5,3.5h12v12h-12ZM3.5,18.5h12v12H3.5Z" />
    </>
  ),
}

interface Props {
  /** Riot's team position, or "ALL". Anything unknown renders nothing. */
  position: string | null | undefined
  className?: string
}

export default function PositionIcon({ position, className }: Props) {
  const shape = SHAPES[(position ?? '').toUpperCase()]
  if (!shape) return null
  return (
    <svg
      viewBox="0 0 34 34"
      aria-hidden="true"
      focusable="false"
      // Sized by the caller so it tracks the type it sits beside.
      className={className ?? 'size-[1.15em]'}
    >
      {shape}
    </svg>
  )
}
