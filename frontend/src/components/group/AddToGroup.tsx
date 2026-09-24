import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

import { api } from '../../lib/api'
import { useSavedGroups } from '../../lib/groups'
import { publicErrorText } from '../../lib/errors'

/**
 * Put the player on this profile into one of the groups this browser can
 * edit. A popover: it floats over the page in a portal, so the art header's
 * clipping, which cut off a list that used to open in the page's flow, no
 * longer reaches it, and it closes on Escape and on a click outside.
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
      toast.success(`Added to ${name}`)
    } catch (error) {
      // The group's own answers ("already in this group") are its message;
      // anything from Riot is said in the site's words.
      setStatus({ slug, ok: false, text: publicErrorText(error).body })
    } finally {
      setBusy(null)
    }
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="xs" className="font-600">
          Add to group
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 space-y-2 rounded-md border-white/10 bg-panel/95 p-3 text-xs shadow-[0_20px_50px_-16px_rgb(0_0_0/0.85)] backdrop-blur-md">
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
      </PopoverContent>
    </Popover>
  )
}
