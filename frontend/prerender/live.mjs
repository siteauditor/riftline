// Render a profile page on request, with the rank Riot gives now.
//
//     node prerender/live.mjs [--api http://api:8000] [--port 3000]
//
// Why a server at all, when every other page is a file: a profile's file is
// written from storage, and a stored rank moves only when someone opens the
// page, so the title and description a crawler or a link preview read were up
// to a day behind the player (Veystrix#999 read Bronze I in Telegram's
// preview while the page itself showed Silver IV, 2026-09-24). Here the
// header's profile is the live one, within the API's league cache
// (TTL_LEAGUE, five minutes), and the rest of the page is what the file holds.
//
// Guarded, because a crawler must never wait on Riot:
// - Only profiles the manifest lists (`GET /api/meta/pages`), with the same
//   indexable flag the file got. Anything else is a 404, and nginx serves
//   what it would have served without this server.
// - A call that can reach Riot gets LIVE_BUDGET_MS. Slow, rate limited, or an
//   expired key: the live answer is dropped and the page renders from
//   storage, the same HTML as the file.
// - At most MAX_LIVE renders ask Riot at once. A burst of crawler requests
//   beyond that renders from storage rather than queueing on the key, which
//   visitors share.
// - nginx falls back to the file when this server is down, slow or failing
//   (frontend/nginx.conf, `@live_profile`), so the worst case is the old
//   behaviour.

import http from 'node:http'

import { assemble, loadBuild, parseArgs, realFetch, routeFetchToApi } from './shared.mjs'

const args = parseArgs(process.argv.slice(2))
const apiBase = args.api ?? process.env.API_BASE ?? 'http://127.0.0.1:8000'
const port = Number(args.port ?? process.env.PORT ?? 3000)
const buildId = process.env.BUILD_ID ?? 'dev'

// A live profile answers in well under a second from the API's cache and in
// one or two Riot calls when it is cold; three seconds is a cold answer with
// room, and short enough that a crawler never sees a slow page.
const LIVE_BUDGET_MS = Number(process.env.LIVE_BUDGET_MS ?? 3000)
const MAX_LIVE = Number(process.env.MAX_LIVE ?? 2)
// The manifest changes when a player crosses the ten-game floor, which the
// nightly run does in bulk; ten minutes late for a new profile is fine.
const MANIFEST_TTL_MS = 10 * 60 * 1000

const PROFILE_PATH = /^\/summoner\/[^/]+\/[^/]+\/[^/]+$/

// Only the calls that can reach Riot are bounded. `source=stored` answers
// from the database, and cutting one short would drop the stored header the
// page falls back to.
routeFetchToApi(apiBase, {
  signalFor: (input) =>
    input.startsWith('/api/') && !input.includes('source=stored')
      ? AbortSignal.timeout(LIVE_BUDGET_MS)
      : undefined,
})

const build = await loadBuild()

let manifest = { pages: new Map(), fetchedAt: 0 }
async function listedPages() {
  if (Date.now() - manifest.fetchedAt < MANIFEST_TTL_MS) return manifest.pages
  try {
    const response = await realFetch(new URL('/api/meta/pages', apiBase), {
      signal: AbortSignal.timeout(5000),
    })
    if (!response.ok) throw new Error(`answered ${response.status}`)
    const body = await response.json()
    manifest = {
      pages: new Map(body.pages.map((p) => [p.path, Boolean(p.indexable)])),
      fetchedAt: Date.now(),
    }
  } catch (error) {
    // The last good list keeps serving; an empty one sends every request to
    // the file, which is the right answer while the API is starting.
    console.error(`live: manifest unavailable (${error instanceof Error ? error.message : error})`)
  }
  return manifest.pages
}

let liveInFlight = 0

async function renderProfile(pathname, indexable) {
  const live = liveInFlight < MAX_LIVE
  if (live) liveInFlight += 1
  try {
    const rendered = await build.render(pathname, { noindex: !indexable, live })
    const fresh = Boolean(
      rendered.state?.queries?.some((q) => q.queryKey?.[0] === 'profile' && q.state?.status === 'success'),
    )
    return { rendered, fresh }
  } finally {
    if (live) liveInFlight -= 1
  }
}

function plain(res, status, text) {
  res.writeHead(status, { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store' })
  res.end(text)
}

http
  .createServer(async (req, res) => {
    const url = new URL(req.url ?? '/', 'http://live.local')
    if (url.pathname === '/healthz') return plain(res, 200, 'ok')
    if (req.method !== 'GET' && req.method !== 'HEAD') return plain(res, 405, 'method not allowed')

    let decoded
    try {
      decoded = decodeURIComponent(url.pathname)
    } catch {
      return plain(res, 404, 'not a page')
    }
    if (!PROFILE_PATH.test(decoded)) return plain(res, 404, 'not a profile')
    const pages = await listedPages()
    if (!pages.has(decoded)) return plain(res, 404, 'not listed')

    const started = Date.now()
    try {
      // The path alone, as nginx's files are: the query string never changes
      // the HTML, which is what useHydratedSearchParams hydrates against.
      const { rendered, fresh } = await renderProfile(url.pathname, pages.get(decoded))
      if (rendered.status >= 300 || !rendered.html) return plain(res, 502, `status ${rendered.status}`)
      const html = assemble(build.template, rendered, build)
      res.writeHead(200, {
        'Content-Type': 'text/html; charset=utf-8',
        // The API's league cache is five minutes; an edge copy older than
        // that would undo the point of rendering here.
        'Cache-Control': 'public, max-age=0, s-maxage=300',
        'X-Prerendered': fresh ? `live ${buildId}` : `stored ${buildId}`,
      })
      res.end(req.method === 'HEAD' ? undefined : html)
      console.log(`live: ${decoded} ${fresh ? 'live' : 'stored'} ${Date.now() - started}ms`)
    } catch (error) {
      console.error(`live: ${decoded} failed: ${error instanceof Error ? error.message : error}`)
      if (!res.headersSent) plain(res, 502, 'render failed')
    }
  })
  .listen(port, () => console.log(`live: profiles on :${port}, api ${apiBase}, build ${buildId}`))
