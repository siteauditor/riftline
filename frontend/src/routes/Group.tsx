import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError, api, type GroupWarm } from '../lib/api'
import { forgetGroup, keyInHash, rememberGroup, useSavedGroups, viewLink } from '../lib/groups'
import { withParams } from '../lib/searchParams'
import CopyButton from '../components/group/CopyButton'
import EditPanel from '../components/group/EditPanel'
import MemberTable from '../components/group/MemberTable'
import { SORT_KEYS, sortMembers, type SortKey } from '../components/group/sorting'
import Together from '../components/group/Together'
import { ErrorView, Spinner } from '../components/StateViews'

// While players are loading, the page asks the server to fetch a little more
// as soon as the last pass ends, and less often once a pass finds nothing to
// do. Each pass is at most five seconds of server time and stops at the key's
// reserve for searches, so an open tab can never starve the site.
const NEXT_PASS_MS = 500
const IDLE_PASS_MS = 8_000
const BUSY_FALLBACK_MS = 15_000

/** One page per slug: its key and warming state start fresh on another group. */
export default function GroupRoute() {
  const { slug = '' } = useParams()
  return <GroupPage key={slug} slug={slug} />
}

function GroupPage({ slug }: { slug: string }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [search, setSearch] = useSearchParams()
  const queryClient = useQueryClient()
  // The key in the address wins, then the one this browser kept. Read on every
  // render rather than once: pasting the edit link over the view link of an
  // open group changes only the fragment, which remounts nothing.
  const addressKey = keyInHash(location.hash)
  const saved = useSavedGroups().find((g) => g.slug === slug)
  const editKey = addressKey ?? saved?.key ?? null
  const [editing, setEditing] = useState(false)
  const [warm, setWarm] = useState<GroupWarm | null>(null)
  const [opened, setOpened] = useState(false)
  const warming = useRef(false)

  // An edit link carries its key after '#'. It is kept in this browser and
  // dropped from the address, so what a visitor copies from the address bar
  // is the view link, never the key.
  useEffect(() => {
    if (!addressKey) return
    rememberGroup({ slug, key: addressKey })
    navigate({ pathname: location.pathname, search: location.search }, { replace: true })
  }, [slug, addressKey, navigate, location.pathname, location.search])

  // A group is a list of people shared by link: not for search engines.
  // nginx sends the same as a header; this covers a crawler that renders.
  useEffect(() => {
    const meta = document.createElement('meta')
    meta.name = 'robots'
    meta.content = 'noindex, nofollow'
    document.head.appendChild(meta)
    return () => meta.remove()
  }, [])

  const queue = search.get('queue') ?? 'all'
  const sortParam = search.get('sort') as SortKey | null
  const sort: SortKey = sortParam && SORT_KEYS.includes(sortParam) ? sortParam : 'rank'
  const set = (patch: Record<string, string | null>) =>
    setSearch((prev) => withParams(prev, patch, { queue: 'all', sort: 'rank' }), { replace: true })

  const query = useQuery({
    queryKey: ['group', slug, queue, editKey],
    queryFn: () => api.group(slug, queue, editKey),
    // A filter change keeps the table on screen while the next one loads.
    placeholderData: (previous) => previous,
    staleTime: 30_000,
    retry: false,
  })
  const data = query.data

  const name = data?.name
  useEffect(() => {
    if (name) rememberGroup({ slug, name })
  }, [slug, name])

  useEffect(() => {
    if (!name) return
    const before = document.title
    document.title = `${name} | Riftline`
    return () => {
      document.title = before
    }
  }, [name])

  // The warming loop: one pass, then the table again, then the next pass. It
  // runs in a background tab too, because the page says it keeps fetching
  // while it is open, and leaving a slow group to fill in another tab is the
  // obvious way to wait for it.
  const pending = data?.pending ?? 0
  const fetching = data?.fetching ?? false
  const updatedAt = query.dataUpdatedAt
  useEffect(() => {
    // One pass on opening even with nothing pending, because ranks go stale
    // after an hour and that pass is one call per player at most, often none.
    if (!fetching || warming.current || (!pending && opened)) return
    const delay = !warm
      ? 0
      : warm.key_busy
        ? warm.retry_after
          ? Math.max(2, warm.retry_after) * 1000
          : BUSY_FALLBACK_MS
        : warm.retry_after
          ? warm.retry_after * 1000
          : warm.calls > 0
            ? NEXT_PASS_MS
            : IDLE_PASS_MS
    const timer = window.setTimeout(async () => {
      warming.current = true
      try {
        setWarm(await api.warmGroup(slug))
      } catch (error) {
        setWarm({
          pending,
          fetching,
          key_busy: true,
          retry_after: error instanceof ApiError && error.retryAfter ? error.retryAfter : 15,
          calls: 0,
          games: 0,
        })
      } finally {
        warming.current = false
        setOpened(true)
        void queryClient.invalidateQueries({ queryKey: ['group', slug] })
      }
    }, delay)
    return () => window.clearTimeout(timer)
  }, [pending, fetching, opened, updatedAt, warm, slug, queryClient])

  function changed() {
    // Straight into a pass: a player just added has everything to fetch.
    setWarm(null)
    setOpened(false)
    // And the panel stays open for the next one, which the first add would
    // otherwise close by making the group non-empty.
    setEditing(true)
    void queryClient.invalidateQueries({ queryKey: ['group', slug] })
  }

  function keyChanged(key: string) {
    rememberGroup({ slug, key })
  }

  function forgetKey() {
    rememberGroup({ slug, key: null })
  }

  if (query.isLoading) {
    return (
      <div className="py-16">
        <Spinner label="Opening the group" />
      </div>
    )
  }
  if (query.isError || !data) {
    const missing = query.error instanceof ApiError && query.error.kind === 'not_found'
    return (
      <div className="mx-auto max-w-[720px] space-y-4 px-4 py-10">
        {missing ? (
          <>
            <h1 className="display text-2xl font-700 text-ink">No group at this link</h1>
            <p className="text-sm text-ink-dim">
              It may have been deleted, or the link was cut short.{' '}
              <Link to="/groups" className="underline decoration-line underline-offset-2 hover:text-gold-bright">
                Your groups
              </Link>
            </p>
            {saved ? (
              <button
                type="button"
                onClick={() => {
                  forgetGroup(slug)
                  navigate('/groups')
                }}
                className="text-xs text-ink-faint underline decoration-line underline-offset-2 hover:text-ink"
              >
                Forget it in this browser
              </button>
            ) : null}
          </>
        ) : (
          <ErrorView error={query.error} onRetry={() => query.refetch()} />
        )}
      </div>
    )
  }

  const canEdit = Boolean(editKey && data.can_edit)
  const staleKey = Boolean(editKey && !data.can_edit)
  const members = sortMembers(data.members, sort)
  const showEdit = canEdit && (editing || data.members.length === 0)
  const queueLabel = data.queues.find((q) => q.key === data.queue)?.label ?? 'All queues'

  return (
    <div className="mx-auto max-w-[1280px] space-y-6 px-4 py-6">
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <p className="eyebrow">
            Group, {data.members.length} of {data.max_members} players
          </p>
          <h1 className="display mt-1 break-words text-[clamp(1.9rem,4.5vw,3rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
            {data.name}
          </h1>
          <p className="mt-2 max-w-[78ch] text-sm leading-relaxed text-ink-dim">
            Ordered by official rank. Every other column sorts, but Riftline does not combine
            them into a rating of its own: Riot does not allow one. Figures come from each
            player's newest {data.history_cap.toLocaleString()} games that Riftline holds, and
            need {data.min_games} games in the queues chosen before they are shown.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <CopyButton
            text={viewLink(slug)}
            className="rounded-sm border border-line px-3 py-1.5 font-600 text-ink-dim transition-colors hover:border-gold hover:text-gold-bright"
          >
            Copy view link
          </CopyButton>
          {canEdit && data.members.length > 0 && (
            <button
              type="button"
              onClick={() => setEditing((v) => !v)}
              aria-expanded={showEdit}
              className="rounded-sm bg-accent px-3 py-1.5 font-700 text-deep transition-colors hover:bg-accent-bright"
            >
              {showEdit ? 'Done editing' : 'Edit group'}
            </button>
          )}
        </div>
      </header>

      {staleKey && (
        <p className="accent-edge bg-panel/50 py-2.5 pl-4 pr-3 text-sm text-ink-dim">
          The edit link this browser kept no longer works: someone made a new one. You can still
          view the group.{' '}
          <button
            type="button"
            onClick={forgetKey}
            className="underline decoration-line underline-offset-2 hover:text-ink"
          >
            Forget the old link
          </button>
        </p>
      )}

      {showEdit && editKey && (
        <EditPanel
          group={data}
          editKey={editKey}
          onChanged={changed}
          onKeyChanged={keyChanged}
          onDeleted={() => {
            forgetGroup(slug)
            navigate('/groups')
          }}
        />
      )}

      {pending > 0 && (
        <p role="status" className="accent-edge bg-panel/50 py-2.5 pl-4 pr-3 text-sm text-ink-dim">
          {!fetching ? (
            <>
              {pending} of {data.members.length} players are still to be read from Riot, and
              Riot is not answering Riftline right now. They fill in once it is back.
            </>
          ) : (
            <>
              <span className="text-ink">
                {pending} of {data.members.length} players still loading from Riot.
              </span>{' '}
              Games arrive a few at a time within Riot's rate limit, and this page keeps fetching
              while it is open; the rest continue overnight.
              {warm?.key_busy &&
                ` Riot's limit is busy right now, so the next try is in about ${Math.ceil(
                  warm.retry_after ?? BUSY_FALLBACK_MS / 1000,
                )} seconds.`}
            </>
          )}
        </p>
      )}

      {data.members.length === 0 ? (
        <p className="py-6 text-sm text-ink-dim">
          {canEdit ? 'Add the first player above.' : 'Nobody is in this group yet.'}
        </p>
      ) : (
        <>
          <div
            className="flex flex-wrap items-center gap-x-1 gap-y-2 border-b border-line-soft text-sm"
            role="group"
            aria-label="Queues"
          >
            {data.queues.map((q) => (
              <button
                key={q.key}
                type="button"
                onClick={() => set({ queue: q.key })}
                aria-pressed={q.key === data.queue}
                className={`-mb-px border-b-2 px-2.5 pb-1.5 pt-1 font-display font-600 transition-colors ${
                  q.key === data.queue
                    ? 'border-gold text-gold-bright'
                    : 'border-transparent text-ink-dim hover:text-ink'
                }`}
              >
                {q.label}
              </button>
            ))}
            {query.isPlaceholderData && (
              <span className="ml-2 text-xs text-ink-faint">Loading {queueLabel}</span>
            )}
          </div>

          <MemberTable
            group={data}
            members={members}
            sort={sort}
            onSort={(key) => set({ sort: key })}
          />

          <Together together={data.together} members={data.members} />
        </>
      )}
    </div>
  )
}
