// Which builds the pages volume keeps: their pages, and their hashed files.
//
// Pages and files are kept for different lengths of time, because they are
// asked for by different things. nginx serves the current build's pages, and
// the one before stays beside them. A file is asked for by any page a browser
// or Cloudflare still holds, and by a tab left open, which loads a route's
// code only when someone opens it: Cloudflare sent every page to browsers
// with four hours of `max-age` until 2026-09-24, and a deploy is often several
// a day, so two builds' files were not enough. Each build's files are named in
// a record, `_shared/builds/<id>.json`, and kept while the record is: for the
// current build, the two newest others, and every build rendered in the last
// week. Hashed names never collide, so keeping more builds costs only the
// files that changed (the whole set is about 2 MB).

export const PAGE_BUILDS = 2
export const FILE_BUILDS = 3
export const FILE_DAYS = 7
const DAY_MS = 24 * 60 * 60 * 1000

/**
 * @param {{ current: string, folders: {name: string, mtime: number}[],
 *           records: {id: string, renderedAt: number}[], now: number }} input
 * @returns {{ pages: Set<string>, records: Set<string> }} the page folders and
 *   the file records to keep, by build id.
 */
export function selectKept({ current, folders, records, now }) {
  const pages = new Set([
    current,
    ...folders
      .filter((f) => f.name !== current)
      .sort((a, b) => b.mtime - a.mtime)
      .slice(0, PAGE_BUILDS - 1)
      .map((f) => f.name),
  ])
  const others = records.filter((r) => r.id !== current).sort((a, b) => b.renderedAt - a.renderedAt)
  const kept = new Set([
    current,
    ...others.slice(0, FILE_BUILDS - 1).map((r) => r.id),
    ...others.filter((r) => now - r.renderedAt <= FILE_DAYS * DAY_MS).map((r) => r.id),
  ])
  return { pages, records: kept }
}
