import { useQuery } from '@tanstack/react-query'

import type { MethodReport } from '../../lib/api'
import { queries } from '../../lib/queries'

/** The four explainers, in reading order. */
export type ExplainerSlug = 'score' | 'win-chance' | 'death-review' | 'lane-labels'

export const EXPLAINERS: { slug: ExplainerSlug; title: string; short: string }[] = [
  { slug: 'score', title: 'The Riftline score', short: 'A 0 to 10 for every player in every game, from seven role-relative measures.' },
  { slug: 'win-chance', title: 'The win chance', short: 'Each side’s chance to win, minute by minute, and the moments that moved it.' },
  { slug: 'death-review', title: 'The death review', short: 'Which deaths were traded, which takedowns converted, and what each cost.' },
  { slug: 'lane-labels', title: 'Lane labels', short: 'Won, even or lost at 14 minutes, placed against the same role.' },
]

/** One report for the hub and all four pages, so moving between them is free. */
export function useMethod() {
  return useQuery({ ...queries.method(), staleTime: 10 * 60 * 1000 })
}

/** When the figures on a page last changed, for the page's own metadata. */
export function reportModified(report: MethodReport | undefined, slug: ExplainerSlug): string | null {
  if (!report) return null
  if (slug === 'win-chance' || slug === 'death-review') return report.win_model?.trained_at ?? null
  return report.score.audited_at
}
