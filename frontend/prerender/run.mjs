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
//
// It also keeps the build's hashed files (`dist/assets`) in `<out>/_shared`,
// named in a record per build (`_shared/builds/<id>.json`), and nginx falls
// back to them: a page held in a cache, or a tab left open, asks for the files
// of the build it was rendered with, and the new web image holds only its
// own. How long each is kept is `retention.mjs`.

import { copyFile, mkdir, readdir, readFile, rename, rm, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'

import { selectKept } from './retention.mjs'
import { assemble, dist, loadBuild, parseArgs, realFetch, routeFetchToApi } from './shared.mjs'

const args = parseArgs(process.argv.slice(2))
const apiBase = args.api ?? process.env.API_BASE ?? 'http://127.0.0.1:8000'
const outRoot = args.out ?? process.env.PRERENDER_OUT ?? path.join(dist, 'pages')
const buildId = args['build-id'] ?? process.env.BUILD_ID ?? 'dev'
const concurrency = Number(args.concurrency ?? 6)
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
  await keepAssets(outRoot, tmp)

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
  await prune(outRoot, buildId)
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

// Where every kept build's hashed files live, beside the builds' pages, and
// the record of which files each build uses.
const SHARED = '_shared'
const RECORDS = path.join(SHARED, 'builds')

/**
 * This build's files into the shared folder, and their names into its
 * record, so the files can be dropped when no kept build names them. Hashed
 * names never collide, so a file already there is the same file. The nightly
 * run renders the deployed build again, which moves its record's time on.
 */
async function keepAssets(root, buildDir) {
  const from = path.join(dist, 'assets')
  const to = path.join(root, SHARED, 'assets')
  await mkdir(to, { recursive: true })
  const names = []
  for (const name of await readdir(from)) {
    if (!(await stat(path.join(from, name))).isFile()) continue
    names.push(name)
    const target = path.join(to, name)
    if (!(await isFile(target))) await copyFile(path.join(from, name), target)
  }
  await writeFile(path.join(buildDir, '_assets.json'), JSON.stringify(names))
  await mkdir(path.join(root, RECORDS), { recursive: true })
  await writeFile(
    path.join(root, RECORDS, `${buildId}.json`),
    JSON.stringify({ id: buildId, renderedAt: Date.now(), assets: names }),
  )
}

/** Old page folders, old records, and every shared file no kept record names. */
async function prune(root, current) {
  const folders = []
  for (const name of await readdir(root)) {
    if (name.endsWith('.tmp') || name.startsWith('_')) continue
    const info = await stat(path.join(root, name))
    if (info.isDirectory()) folders.push({ name, mtime: info.mtimeMs })
  }
  const records = []
  for (const file of await readdir(path.join(root, RECORDS))) {
    if (!file.endsWith('.json')) continue
    try {
      records.push(JSON.parse(await readFile(path.join(root, RECORDS, file), 'utf8')))
    } catch {
      // Unreadable: kept out of the choice, and removed with the old ones.
      records.push({ id: file.slice(0, -'.json'.length), renderedAt: 0, assets: [] })
    }
  }
  const kept = selectKept({ current, folders, records, now: Date.now() })

  for (const folder of folders) {
    if (kept.pages.has(folder.name)) continue
    await rm(path.join(root, folder.name), { recursive: true, force: true })
    console.log(`prerender: removed old build ${folder.name}`)
  }
  const keep = new Set()
  for (const record of records) {
    if (kept.records.has(record.id)) {
      for (const file of record.assets ?? []) keep.add(file)
    } else {
      await rm(path.join(root, RECORDS, `${record.id}.json`), { force: true })
    }
  }
  // A kept page folder from before the records names its files itself.
  for (const name of kept.pages) {
    try {
      for (const file of JSON.parse(await readFile(path.join(root, name, '_assets.json'), 'utf8'))) keep.add(file)
    } catch {
      // A build from before the files were kept names none.
    }
  }
  const dir = path.join(root, SHARED, 'assets')
  let dropped = 0
  for (const name of await readdir(dir)) {
    if (keep.has(name)) continue
    await rm(path.join(dir, name), { force: true })
    dropped += 1
  }
  console.log(`prerender: files of ${kept.records.size} builds kept` + (dropped ? `, ${dropped} files removed` : ''))
}

async function isFile(file) {
  try {
    return (await stat(file)).isFile()
  } catch {
    return false
  }
}

main().catch((error) => {
  console.error(`prerender: ${error instanceof Error ? error.stack ?? error.message : String(error)}`)
  process.exit(1)
})
