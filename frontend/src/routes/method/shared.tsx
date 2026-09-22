import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import ArtHeader from '../../components/ArtHeader'
import Head from '../../components/Head'
import { ErrorView, Spinner } from '../../components/StateViews'
import type { MethodReport } from '../../lib/api'
import { heads } from '../../lib/seo'
import { EXPLAINERS, reportModified, useMethod, type ExplainerSlug } from './data'

/**
 * The four explainers share one report, one frame and one set of parts.
 *
 * Each page is written to be read on its own: what the number is, how it is
 * made, what it was measured against and where it fails, with the live
 * figures from the nightly run set into the sentences. The prose renders
 * before the report arrives; only the figures wait for it.
 */

export function Explainer({
  slug,
  eyebrow,
  title,
  intro,
  children,
}: {
  slug: ExplainerSlug
  eyebrow: string
  title: string
  intro: ReactNode
  children: (report: MethodReport) => ReactNode
}) {
  const query = useMethod()
  const index = EXPLAINERS.findIndex((e) => e.slug === slug)
  const previous = EXPLAINERS[index - 1]
  const next = EXPLAINERS[index + 1]

  return (
    <article>
      <Head {...heads.explainer(slug, reportModified(query.data, slug))} />
      <ArtHeader>
        <p className="eyebrow">
          <Link to="/method" className="hover:text-ink">
            Method
          </Link>{' '}
          / {eyebrow}
        </p>
        <h1 className="display mt-1 text-[clamp(2rem,5vw,3.2rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
          {title}
        </h1>
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-dim">{intro}</p>
      </ArtHeader>

      <div className="mx-auto max-w-[1080px] space-y-10 px-4 py-8">
        {query.isLoading && <Spinner label="Loading the figures" />}
        {query.isError && <ErrorView error={query.error} onRetry={() => query.refetch()} />}
        {query.data && children(query.data)}

        <nav aria-label="Other explainers" className="flex flex-wrap justify-between gap-4 border-t border-line-soft pt-6 text-sm">
          {previous ? (
            <Link to={`/method/${previous.slug}`} className="text-ink-dim hover:text-gold-bright">
              Previous: {previous.title}
            </Link>
          ) : (
            <span />
          )}
          {next && (
            <Link to={`/method/${next.slug}`} className="text-ink-dim hover:text-gold-bright">
              Next: {next.title}
            </Link>
          )}
        </nav>
      </div>
    </article>
  )
}

export function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-20 space-y-4">
      <h2 id={`${id}-title`} className="display text-2xl font-700 text-ink">
        {title}
      </h2>
      {children}
    </section>
  )
}

export function Prose({ children }: { children: ReactNode }) {
  return <p className="max-w-prose text-sm leading-relaxed text-ink-dim">{children}</p>
}

/** A figure set into a sentence. */
export function B({ children }: { children: ReactNode }) {
  return <b className="font-600 text-ink">{children}</b>
}

export function Aside({ children }: { children: ReactNode }) {
  return (
    <p className="max-w-prose border-l-2 border-gold/50 py-1 pl-3 text-sm leading-relaxed text-ink-dim">
      {children}
    </p>
  )
}
