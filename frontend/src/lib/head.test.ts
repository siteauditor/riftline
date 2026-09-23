import { beforeEach, describe, expect, it } from 'vitest'

import { applyHead, canonicalUrl, headTags, jsonForHtml, ORIGIN, renderHeadHtml, type PageHead } from './head'

const head: PageHead = {
  title: 'Aatrox top build & runes <patch 16.18>',
  description: 'What "the numbers" say.',
  path: '/champions/aatrox',
}

describe('jsonForHtml', () => {
  it('cannot close a script tag or break a line, and still parses as JSON', () => {
    const value = { s: '</script><b>', line: `a${String.fromCharCode(0x2028)}b${String.fromCharCode(0x2029)}` }
    const text = jsonForHtml(value)
    expect(text).not.toContain('<')
    expect(text).not.toContain(String.fromCharCode(0x2028))
    expect(text).not.toContain(String.fromCharCode(0x2029))
    expect(JSON.parse(text)).toEqual(value)
  })
})

describe('headTags and renderHeadHtml', () => {
  it('writes one marked tag per key with the canonical absolute', () => {
    const keys = headTags(head).map((t) => t.key)
    expect(new Set(keys).size).toBe(keys.length)
    expect(keys).toEqual(expect.arrayContaining(['title', 'description', 'canonical', 'og:title', 'og:url']))
    expect(canonicalUrl(head.path)).toBe(`${ORIGIN}/champions/aatrox`)

    const html = renderHeadHtml(head)
    expect(html).toContain(`<link rel="canonical" href="${ORIGIN}/champions/aatrox" data-head="canonical">`)
    expect(html).toContain('data-head="title"')
    expect(html).not.toContain('<patch')
    expect(html).toContain('&lt;patch 16.18&gt;')
    expect(html).toContain('&quot;the numbers&quot;')
    expect(html).not.toContain('name="robots"')
  })

  it('marks a thin page noindex but lets its links count', () => {
    const html = renderHeadHtml({ ...head, noindex: true, robots: 'noindex, follow' })
    expect(html).toMatch(/<meta name="robots" content="noindex, follow"/)
  })

  it('carries JSON-LD as a script that cannot escape', () => {
    const html = renderHeadHtml({ ...head, jsonLd: { '@type': 'Thing', name: '</script>' } })
    expect(html).toContain('<script type="application/ld+json"')
    expect(html).not.toContain('</script></script>')
  })
})

describe('applyHead', () => {
  beforeEach(() => {
    document.head.innerHTML = '<title>Riftline</title><meta name="description" content="site default">'
  })

  it('adopts the shell tags and never leaves two titles', () => {
    applyHead(head)
    expect(document.title).toBe(head.title)
    expect(document.querySelectorAll('title').length).toBe(1)
    expect(document.querySelectorAll('meta[name="description"]').length).toBe(1)
    expect(document.querySelector('meta[name="description"]')?.getAttribute('content')).toBe(head.description)
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe(`${ORIGIN}/champions/aatrox`)

    applyHead({ ...head, title: 'Ahri mid build', path: '/champions/ahri' })
    expect(document.title).toBe('Ahri mid build')
    expect(document.querySelectorAll('title').length).toBe(1)
    expect(document.querySelectorAll('link[rel="canonical"]').length).toBe(1)
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe(`${ORIGIN}/champions/ahri`)
  })

  it('removes a robots meta once the page is no longer thin', () => {
    applyHead({ ...head, noindex: true, robots: 'noindex, follow' })
    expect(document.querySelector('meta[name="robots"]')).not.toBeNull()
    applyHead(head)
    expect(document.querySelector('meta[name="robots"]')).toBeNull()
  })
})
