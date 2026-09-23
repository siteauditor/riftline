// Prerender every page the API lists, into files nginx serves as the page.
//
//     node prerender/run.mjs [--api http://api:8000] [--out /pages] [--build-id abc123]
//
// Runs after `pnpm build` (which also builds dist/server/entry-server.js) and
// against a running API, which is where every number on every page comes
// from. On the server it runs at each deploy and each night, in the web
// image's build stage, writing into a volume nginx reads.
//
// What it writes: `<out>/<build-id>/<path>.html` for every page (`/` becomes
// `index.html`), plus `_manifest.json` saying what happened. A page the API
// marks as not indexable is still written, with a noindex meta, so the URL
// still works for people and the rule lives in one place. It writes to a
// temporary directory and renames at the end, so a half-finished run is never
// served, and it exits non-zero when a required page failed or too few pages
// rendered, so a deploy does not switch to a build that cannot prerender.

import { mkdir, readdir, rename, rm, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'

import { assemble, dist, loadBuild, parseArgs, realFetch, routeFetchToApi } from './shared.mjs'

const args = parseArgs(process.argv.slice(2))
const apiBase = args.api ?? process.env.API_BASE ?? 'http://127.0.0.1:8000'
const outRoot = args.out ?? process.env.PRERENDER_OUT ?? path.join(dist, 'pages')
const buildId = args['build-id'] ?? process.env.BUILD_ID ?? 'dev'
const concurrency = Number(args.concurrency ?? 6)
const keepBuilds = 2
// Below this share of the manifest rendered, something is wrong with the
// build rather than with a page, and the deploy should not switch to it.
const MIN_RENDERED_SHARE = 0.9

routeFetchToApi(apiBase)

async function main() {
  const { template, render, renderHeadHtml, jsonForHtml } = await loadBuild()

  const manifestResponse = await realFetch(new URL('/api/meta/pages', apiBase))
  if (!manifestResponse.ok) {
    throw new Error(`GET /api/meta/pages answered ${manifestResponse.status}`)
  }
  const manifest = await manifestResponse.json()
  const pages = manifest.pages
  console.log(`prerender: ${pages.length} pages, index patch ${manifest.index_patch ?? 'none'}, build ${buildId}`)

  const tmp = path.join(outRoot, `${buildId}.tmp`)
  const final = path.join(outRoot, buildId)
  await rm(tmp, { recursive: true, force: true })
  await mkdir(tmp, { recursive: true })

  const results = []
  let next = 0
  async function worker() {
    while (next < pages.length) {
      const page = pages[next]
      next += 1
      results.push(await renderOne(page, { template, tmp, render, renderHeadHtml, jsonForHtml }))
    }
  }
  await Promise.all(Array.from({ length: concurrency }, () => worker()))

  const ok = results.filter((r) => r.ok)
  const failed = results.filter((r) => !r.ok)
  const requiredFailed = failed.filter((r) => r.required)
  const summary = {
    buildId,
    generatedAt: new Date().toISOString(),
    indexPatch: manifest.index_patch ?? null,
    pages: pages.length,
    rendered: ok.length,
    indexable: ok.filter((r) => r.indexable).length,
    withErrors: ok.filter((r) => r.errors.length > 0).length,
    failed: failed.map((r) => ({ path: r.path, error: r.error })),
  }
  await writeFile(path.join(tmp, '_manifest.json'), JSON.stringify(summary, null, 2))

  const share = pages.length ? ok.length / pages.length : 0
  if (requiredFailed.length > 0 || share < MIN_RENDERED_SHARE) {
    console.error(
      `prerender: FAILED, ${ok.length}/${pages.length} rendered` +
        (requiredFailed.length ? `, required pages failed: ${requiredFailed.map((r) => r.path).join(', ')}` : ''),
    )
    for (const r of failed.slice(0, 10)) console.error(`  ${r.path}: ${r.error}`)
    process.exit(1)
  }

  await rm(final, { recursive: true, force: true })
  await rename(tmp, final)
  await pruneOldBuilds(outRoot, buildId)
  console.log(
    `prerender: ${ok.length}/${pages.length} pages rendered into ${final}` +
      ` (${summary.indexable} indexable, ${summary.withErrors} rendered their error state)`,
  )
  for (const r of failed) console.log(`  not rendered: ${r.path}: ${r.error}`)
}

async function renderOne(page, { template, tmp, render, renderHeadHtml, jsonForHtml }) {
  const base = { path: page.path, required: Boolean(page.required), indexable: Boolean(page.indexable) }
  try {
    const rendered = await render(page.path, { noindex: !page.indexable })
    if (rendered.status >= 300 || !rendered.html) {
      return { ...base, ok: false, error: `status ${rendered.status}` }
    }
    const html = assemble(template, rendered, { renderHeadHtml, jsonForHtml })
    const file = page.path === '/' ? 'index.html' : `${page.path.replace(/^\//, '')}.html`
    const target = path.join(tmp, file)
    await mkdir(path.dirname(target), { recursive: true })
    await writeFile(target, html)
    return { ...base, ok: true, errors: rendered.errors }
  } catch (error) {
    return { ...base, ok: false, error: error instanceof Error ? error.message : String(error) }
  }
}

async function pruneOldBuilds(root, current) {
  let names
  try {
    names = await readdir(root)
  } catch {
    return
  }
  const builds = []
  for (const name of names) {
    if (name === current || name.endsWith('.tmp')) continue
    const full = path.join(root, name)
    const info = await stat(full)
    if (info.isDirectory()) builds.push({ name, mtime: info.mtimeMs })
  }
  builds.sort((a, b) => b.mtime - a.mtime)
  for (const old of builds.slice(keepBuilds - 1)) {
    await rm(path.join(root, old.name), { recursive: true, force: true })
    console.log(`prerender: removed old build ${old.name}`)
  }
}

main().catch((error) => {
  console.error(`prerender: ${error instanceof Error ? error.stack ?? error.message : String(error)}`)
  process.exit(1)
})
