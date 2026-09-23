// Serve the built site the way production nginx does, for checking a
// prerender by hand.
//
//     node prerender/serve.mjs [--pages /tmp/pages/local] [--api http://127.0.0.1:8000] [--port 5174]
//                              [--live http://127.0.0.1:3000]
//
// The order is nginx's `try_files`: the prerendered file for the path, then
// a static file from dist/, then the shell. /api/* is proxied to the API.
// With --live, a profile that has a file is asked of the live renderer
// (live.mjs) first and served its file when that cannot answer, as nginx's
// `@live_profile` does. Not used in production, where nginx.conf is the
// authority; this exists so the hydration of a prerendered page can be
// watched in a browser on a machine without Docker.

import { createReadStream } from 'node:fs'
import { stat } from 'node:fs/promises'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const args = Object.fromEntries(
  process.argv.slice(2).reduce((out, arg, i, all) => {
    if (arg.startsWith('--')) out.push([arg.slice(2), all[i + 1] ?? 'true'])
    return out
  }, []),
)
const dist = path.resolve(here, '..', 'dist')
// Resolved, so a forward-slash path from a Unix-style shell on Windows still
// compares with what path.join produces.
const pages = path.resolve(args.pages ?? path.join(dist, 'pages', 'dev'))
const apiBase = args.api ?? 'http://127.0.0.1:8000'
const port = Number(args.port ?? 5174)
const liveBase = args.live ?? null
const PROFILE_PATH = /^\/summoner\/[^/]+\/[^/]+\/[^/]+$/

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript',
  '.css': 'text/css',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.txt': 'text/plain',
  '.webmanifest': 'application/manifest+json',
  '.json': 'application/json',
}

async function exists(file) {
  try {
    return (await stat(file)).isFile()
  } catch {
    return false
  }
}

function send(res, file, extra = {}) {
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] ?? 'application/octet-stream', ...extra })
  createReadStream(file).pipe(res)
}

http
  .createServer(async (req, res) => {
    const url = new URL(req.url, 'http://local')
    if (url.pathname.startsWith('/api/')) {
      // The method and body go through as sent: the draft board and the
      // group editor POST, and forwarding everything as a GET answered them
      // 405 Method Not Allowed (seen 2026-09-23).
      const hasBody = req.method !== 'GET' && req.method !== 'HEAD'
      const chunks = []
      if (hasBody) for await (const chunk of req) chunks.push(chunk)
      const upstream = await fetch(new URL(url.pathname + url.search, apiBase), {
        method: req.method,
        headers: {
          accept: 'application/json',
          ...(req.headers['content-type'] ? { 'content-type': req.headers['content-type'] } : {}),
        },
        body: hasBody ? Buffer.concat(chunks) : undefined,
      })
      res.writeHead(upstream.status, { 'Content-Type': upstream.headers.get('content-type') ?? 'application/json' })
      res.end(Buffer.from(await upstream.arrayBuffer()))
      return
    }
    // Decoded, as nginx's $uri is: a profile whose name holds a space is a
    // file with a space in its name.
    const decoded = decodeURIComponent(url.pathname)
    const clean = decoded === '/' ? '/' : decoded.replace(/\/$/, '')
    const candidates = [
      path.join(pages, clean === '/' ? 'index.html' : `${clean.slice(1)}.html`),
      path.join(dist, clean.slice(1) || 'nothing'),
    ]
    if (process.env.SERVE_DEBUG) {
      for (const file of candidates) console.log(`${url.pathname} -> ${file}: ${await exists(file)}`)
    }
    if (liveBase && PROFILE_PATH.test(clean) && (await exists(candidates[0]))) {
      try {
        const upstream = await fetch(new URL(url.pathname + url.search, liveBase), {
          signal: AbortSignal.timeout(8000),
        })
        if (upstream.ok) {
          res.writeHead(200, {
            'Content-Type': 'text/html; charset=utf-8',
            'X-Prerendered': upstream.headers.get('x-prerendered') ?? 'live',
          })
          res.end(Buffer.from(await upstream.arrayBuffer()))
          return
        }
      } catch {
        // Down or slow: the file, below.
      }
    }
    for (const file of candidates) {
      if (await exists(file)) {
        const isPage = file.startsWith(pages)
        send(res, file, isPage ? { 'X-Prerendered': 'yes' } : {})
        return
      }
    }
    send(res, path.join(dist, 'index.html'), { 'X-Robots-Tag': 'noindex, nofollow' })
  })
  .listen(port, () => console.log(`serving ${pages} over ${dist} on http://127.0.0.1:${port}, api ${apiBase}`))
