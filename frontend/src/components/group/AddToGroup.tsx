import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../../lib/api'
import { useSavedGroups } from '../../lib/groups'

/**
 * Put the player on this profile into one of the groups this browser can
 * edit. A native disclosure, so it opens and closes without script and from
 * the keyboard.
 *
 * The list opens in the page's flow rather than floating: the profile's art
 * header clips what overflows it, and a floating list was cut off at its
 * bottom edge.
 */
export default function AddToGroup({
  platform,
  riotId,
}: {
  platform: string
  riotId: string
}) {
  const editable = useSavedGroups().filter((g) => g.key)
  const [status, setStatus] = useState<{ slug: string; ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  async function add(slug: string, key: string, name: string) {
    setBusy(slug)
    setStatus(null)
    try {
      await api.addGroupMember(slug, key, { riot_id: riotId, platform })
      setStatus({ slug, ok: true, text: `Added to ${name}.` })
    } catch (error) {
      setStatus({
        slug,
        ok: false,
        text: error instanceof Error ? error.message : 'Could not add them.',
      })
    } finally {
      setBusy(null)
    }
  }

  return (
    <details>
      <summary className="w-fit cursor-pointer list-none rounded-sm border border-line px-2 py-0.5 font-600 text-ink-dim transition-colors hover:border-gold hover:text-gold-bright [&::-webkit-details-marker]:hidden">
        Add to group
      </summary>
      <div className="frame mt-1.5 w-64 max-w-full space-y-2 px-3 py-2.5 text-xs">
        {editable.length === 0 ? (
          <p className="leading-relaxed text-ink-dim">
            No group this browser can edit.{' '}
            <Link to="/groups" className="underline decoration-line underline-offset-2 hover:text-gold-bright">
              Make one
            </Link>
          </p>
        ) : (
          <ul className="space-y-1">
            {editable.map((g) => (
              <li key={g.slug} className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() => void add(g.slug, g.key as string, g.name)}
                  className="min-w-0 flex-1 truncate rounded-sm px-1.5 py-1 text-left text-ink transition-colors hover:bg-raised disabled:opacity-50"
                >
                  {busy === g.slug ? 'Adding…' : g.name}
                </button>
                <Link to={`/g/${g.slug}`} className="shrink-0 text-ink-faint hover:text-ink">
                  Open
                </Link>
              </li>
            ))}
          </ul>
        )}
        {status && (
          <p role={status.ok ? 'status' : 'alert'} className={status.ok ? 'text-win' : 'text-loss'}>
            {status.text}{' '}
            {status.ok && (
              <Link to={`/g/${status.slug}`} className="underline decoration-line underline-offset-2">
                Open it
              </Link>
            )}
          </p>
        )}
      </div>
    </details>
  )
}
