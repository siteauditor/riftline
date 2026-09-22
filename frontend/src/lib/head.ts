import { createContext } from 'react'

/**
 * The document head, decided once per page and rendered the same way twice.
 *
 * A prerendered page arrives with its title, description, canonical, social
 * card and JSON-LD already in `<head>`, each tag marked `data-head`. When the
 * app hydrates, or moves to another page, it updates those same tags in place
 * rather than adding new ones, so the head never holds two titles and the
 * canonical a crawler read is the one the app keeps. Google asks for exactly
 * that: the canonical in the source, and JavaScript that does not change it.
 *
 * No head library: the whole job is a list of tags and two ways to emit them.
 */

export const SITE_NAME = 'Riftline'
export const ORIGIN = 'https://riftline.rhasta.space'
export const DEFAULT_IMAGE = `${ORIGIN}/og-default.png`

export interface PageHead {
  /** The full title, with the site name already on it. */
  title: string
  description: string
  /** The canonical path: clean, no query string. */
  path: string
  type?: 'website' | 'article'
  image?: string | null
  /** A page shown to people but kept out of search. */
  noindex?: boolean
  jsonLd?: Record<string, unknown> | Record<string, unknown>[]
  /** BCP 47, for the day pages exist in more than one language. */
  locale?: string
}

export interface HeadTag {
  /** What the client updates by: one tag per key, always. */
  key: string
  tag: 'title' | 'meta' | 'link' | 'script'
  attrs?: Record<string, string>
  text?: string
}

export function canonicalUrl(path: string): string {
  return `${ORIGIN}${path}`
}

/** The tags a page's head is made of, in the order they are written. */
export function headTags(head: PageHead): HeadTag[] {
  const url = canonicalUrl(head.path)
  const image = head.image ?? DEFAULT_IMAGE
  const tags: HeadTag[] = [
    { key: 'title', tag: 'title', text: head.title },
    { key: 'description', tag: 'meta', attrs: { name: 'description', content: head.description } },
    { key: 'canonical', tag: 'link', attrs: { rel: 'canonical', href: url } },
    { key: 'og:title', tag: 'meta', attrs: { property: 'og:title', content: head.title } },
    { key: 'og:description', tag: 'meta', attrs: { property: 'og:description', content: head.description } },
    { key: 'og:url', tag: 'meta', attrs: { property: 'og:url', content: url } },
    { key: 'og:type', tag: 'meta', attrs: { property: 'og:type', content: head.type ?? 'website' } },
    { key: 'og:image', tag: 'meta', attrs: { property: 'og:image', content: image } },
    { key: 'og:site_name', tag: 'meta', attrs: { property: 'og:site_name', content: SITE_NAME } },
    { key: 'twitter:card', tag: 'meta', attrs: { name: 'twitter:card', content: 'summary_large_image' } },
    { key: 'twitter:title', tag: 'meta', attrs: { name: 'twitter:title', content: head.title } },
    { key: 'twitter:description', tag: 'meta', attrs: { name: 'twitter:description', content: head.description } },
    { key: 'twitter:image', tag: 'meta', attrs: { name: 'twitter:image', content: image } },
  ]
  if (head.noindex) {
    tags.push({ key: 'robots', tag: 'meta', attrs: { name: 'robots', content: 'noindex, nofollow' } })
  }
  if (head.jsonLd) {
    tags.push({ key: 'jsonld', tag: 'script', attrs: { type: 'application/ld+json' }, text: jsonForHtml(head.jsonLd) })
  }
  return tags
}

/** Every key a page may set, so a page that drops one clears the last page's. */
export const MANAGED_KEYS = [
  'title', 'description', 'canonical', 'og:title', 'og:description', 'og:url', 'og:type',
  'og:image', 'og:site_name', 'twitter:card', 'twitter:title', 'twitter:description',
  'twitter:image', 'robots', 'jsonld',
]

/**
 * JSON that is safe inside a script element: `<` is escaped so that a name
 * containing `</script>` cannot end the element early.
 */
export function jsonForHtml(value: unknown): string {
  // U+2028 and U+2029 are line terminators to a script parser and not to JSON,
  // so they are escaped too; spelled by code so this file never contains one.
  const separators = new RegExp(`[${String.fromCharCode(0x2028)}${String.fromCharCode(0x2029)}]`, 'g')
  return JSON.stringify(value)
    .replace(/</g, '\\u003c')
    .replace(separators, (c) => `\\u${c.charCodeAt(0).toString(16)}`)
}

function escapeAttr(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function escapeText(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** The head as HTML, for the prerenderer. Each tag carries its `data-head` key. */
export function renderHeadHtml(head: PageHead): string {
  return headTags(head)
    .map((t) => {
      const attrs = Object.entries(t.attrs ?? {})
        .map(([k, v]) => ` ${k}="${escapeAttr(v)}"`)
        .join('')
      const marker = ` data-head="${t.key}"`
      if (t.tag === 'title') return `<title${marker}>${escapeText(t.text ?? '')}</title>`
      if (t.tag === 'script') return `<script${attrs}${marker}>${t.text ?? ''}</script>`
      return `<${t.tag}${attrs}${marker}>`
    })
    .join('\n    ')
}

/**
 * Update the live document to match `head`: existing marked tags are edited,
 * missing ones are made, and keys this page does not set are removed. The
 * static `<title>` from index.html is adopted as the managed one the first
 * time, so the shell never ends up with two.
 */
export function applyHead(head: PageHead): void {
  if (typeof document === 'undefined') return
  const root = document.head
  const wanted = new Map(headTags(head).map((t) => [t.key, t]))

  // A marked tag first; failing that, an unmarked one that means the same
  // thing (the shell's own title and metas), which is adopted rather than
  // duplicated.
  const managed = (key: string, spec?: HeadTag): Element | null => {
    const marked = root.querySelector(`[data-head="${key}"]`)
    if (marked) return marked
    if (key === 'title') return root.querySelector('title')
    if (spec?.tag === 'meta' && spec.attrs) {
      const by = spec.attrs.name ? `name="${spec.attrs.name}"` : `property="${spec.attrs.property}"`
      return root.querySelector(`meta[${by}]`)
    }
    return null
  }

  for (const key of MANAGED_KEYS) {
    const spec = wanted.get(key)
    let el = managed(key, spec)
    if (!spec) {
      el?.remove()
      continue
    }
    if (!el) {
      el = document.createElement(spec.tag)
      root.appendChild(el)
    }
    el.setAttribute('data-head', key)
    for (const [k, v] of Object.entries(spec.attrs ?? {})) el.setAttribute(k, v)
    if (spec.tag === 'title') document.title = spec.text ?? ''
    else if (spec.tag === 'script') el.textContent = spec.text ?? ''
  }
}

/**
 * Where the server puts what each page asked for. Provided only by the
 * prerender entry; on the client it is absent and `Head` writes to the DOM.
 */
export interface HeadCollector {
  set(head: PageHead): void
}

export const HeadContext = createContext<HeadCollector | null>(null)
