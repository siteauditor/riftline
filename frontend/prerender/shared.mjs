// What the file prerender (run.mjs) and the live profile renderer (live.mjs)
// share: reading the build, reaching the API, and putting a rendered page
// into the shell. One copy, so a page rendered either way is the same HTML.

import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
export const dist = path.join(here, '..', 'dist')

export function parseArgs(argv) {
  const out = {}
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg.startsWith('--')) {
      const key = arg.slice(2)
      const next = argv[i + 1]
      if (next && !next.startsWith('--')) {
        out[key] = next
        i += 1
      } else {
        out[key] = 'true'
      }
    }
  }
  return out
}

export const realFetch = globalThis.fetch

/**
 * The app fetches relative "/api/..." paths, which a browser resolves against
 * the page. Node has no page, so they are resolved against the API here.
 * `signalFor(path)` may return an AbortSignal for a request, which is how the
 * live renderer puts a time limit on the calls that can reach Riot.
 */
export function routeFetchToApi(apiBase, { signalFor } = {}) {
  globalThis.fetch = (input, init) => {
    if (typeof input === 'string' && input.startsWith('/')) {
      const signal = signalFor?.(input)
      return realFetch(new URL(input, apiBase), signal ? { ...init, signal } : init)
    }
    return realFetch(input, init)
  }
}

/** The shell and the server bundle of this build. */
export async function loadBuild() {
  const template = await readFile(path.join(dist, 'index.html'), 'utf8')
  if (!template.includes('<!--app-html-->') || !template.includes('<!--app-head-->')) {
    throw new Error('dist/index.html has no <!--app-html--> / <!--app-head--> placeholders')
  }
  const server = await import(pathToFileUrl(path.join(dist, 'server', 'entry-server.js')))
  return { template, ...server }
}

/**
 * The built shell with this page's head, markup and query cache in it. The
 * shell's own marked head tags (its default title and card) are removed
 * first, so the page's replace them rather than sit beside them.
 */
export function assemble(template, rendered, { renderHeadHtml, jsonForHtml }) {
  let html = template
    .replace(/<title\b[^>]*data-head="[^"]*"[^>]*>[^<]*<\/title>\s*/g, '')
    .replace(/<(?:meta|link)\b[^>]*data-head="[^"]*"[^>]*>\s*/g, '')
  const head = rendered.head ? renderHeadHtml(rendered.head) : ''
  // Replaced through functions: a string replacement reads `$&` and `$'` in
  // the markup as patterns, and a Riot ID or a page's JSON can hold a `$`.
  html = html.replace('<!--app-head-->', () => head)
  html = html.replace('<!--app-html-->', () => rendered.html)
  const state =
    `<script>window.__RENDERED_AT__=${Number(rendered.renderedAt)};` +
    `window.__RQ_STATE__=${jsonForHtml(rendered.state)}</script>\n    `
  html = html.replace('<script type="module"', () => `${state}<script type="module"`)
  return html
}

function pathToFileUrl(file) {
  return new URL(`file:///${file.replace(/\\/g, '/')}`).href
}
