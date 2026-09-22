import { useState } from 'react'

import { ApiError, PLATFORMS, api, type Group } from '../../lib/api'
import { editLink, riotIdsIn } from '../../lib/groups'
import { lastRegion, rememberRegion } from '../../lib/storage'
import CopyButton from './CopyButton'

function message(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.kind === 'rate_limited' && error.retryAfter) {
    return `${error.message} Try again in about ${Math.ceil(error.retryAfter)} seconds.`
  }
  return error instanceof Error ? error.message : fallback
}

const button =
  'rounded-sm border border-line px-3 py-1.5 text-xs font-600 text-ink-dim transition-colors hover:border-gold hover:text-gold-bright disabled:opacity-50 disabled:hover:border-line disabled:hover:text-ink-dim'

/**
 * Changing a group, for whoever holds its edit key. Every call carries the key
 * as a header; the server refuses anything else.
 */
export default function EditPanel({
  group,
  editKey,
  onChanged,
  onKeyChanged,
  onDeleted,
}: {
  group: Group
  editKey: string
  onChanged: () => void
  onKeyChanged: (key: string) => void
  onDeleted: () => void
}) {
  const [region, setRegion] = useState(() => lastRegion() ?? 'euw1')
  const room = group.max_members - group.members.length

  function pickRegion(id: string) {
    setRegion(id)
    rememberRegion(id)
  }

  return (
    <section className="frame" aria-labelledby="edit-heading">
      <header className="border-b border-line-soft px-4 py-2.5">
        <h2 id="edit-heading" className="eyebrow">
          Edit this group
        </h2>
      </header>
      <div className="grid gap-6 px-4 py-4 lg:grid-cols-2">
        <div className="space-y-5">
          <AddOne
            group={group}
            editKey={editKey}
            region={region}
            onRegion={pickRegion}
            room={room}
            onAdded={onChanged}
          />
          <AddMany group={group} editKey={editKey} region={region} room={room} onAdded={onChanged} />
        </div>
        <div className="space-y-5">
          <Players group={group} editKey={editKey} onChanged={onChanged} />
          <Settings
            group={group}
            editKey={editKey}
            onChanged={onChanged}
            onKeyChanged={onKeyChanged}
            onDeleted={onDeleted}
          />
        </div>
      </div>
    </section>
  )
}

function AddOne({
  group,
  editKey,
  region,
  onRegion,
  room,
  onAdded,
}: {
  group: Group
  editKey: string
  region: string
  onRegion: (id: string) => void
  room: number
  onAdded: () => void
}) {
  const [riotId, setRiotId] = useState('')
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)

  async function submit() {
    const value = riotId.trim()
    if (!value.includes('#')) {
      setResult({ ok: false, text: 'Write the Riot ID with its tag: Name#TAG.' })
      return
    }
    setBusy(true)
    setResult(null)
    try {
      const added = await api.addGroupMember(group.slug, editKey, {
        riot_id: value,
        platform: region,
        label: label.trim() || null,
      })
      setResult({ ok: true, text: `Added ${added.riot_id} (${added.platform_label}).` })
      setRiotId('')
      setLabel('')
      onAdded()
    } catch (error) {
      setResult({ ok: false, text: message(error, 'That player could not be added.') })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        void submit()
      }}
      className="space-y-2"
    >
      <h3 className="display text-base font-700 text-ink">Add a player</h3>
      <div className="flex flex-wrap gap-2">
        <input
          value={riotId}
          onChange={(e) => setRiotId(e.target.value)}
          placeholder="Name#TAG"
          aria-label="Riot ID"
          name="riot-id"
          className="control min-w-[10rem] flex-[2] text-sm"
          disabled={room <= 0}
        />
        <select
          value={region}
          onChange={(e) => onRegion(e.target.value)}
          aria-label="Region"
          className="control"
        >
          {PLATFORMS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="Label, e.g. Top"
          aria-label="Label (optional)"
          maxLength={24}
          name="label"
          className="control min-w-[7rem] flex-1 text-sm"
          disabled={room <= 0}
        />
        <button type="submit" disabled={busy || room <= 0 || !riotId.trim()} className={button}>
          {busy ? 'Adding' : 'Add'}
        </button>
      </div>
      <p className="text-xs text-ink-faint">
        {room > 0
          ? `Room for ${room} more of ${group.max_members}.`
          : `The group is full at ${group.max_members}. Remove someone to add another.`}
      </p>
      {result && (
        <p role={result.ok ? 'status' : 'alert'} className={`text-xs ${result.ok ? 'text-win' : 'text-loss'}`}>
          {result.text}
        </p>
      )}
    </form>
  )
}

function AddMany({
  group,
  editKey,
  region,
  room,
  onAdded,
}: {
  group: Group
  editKey: string
  region: string
  room: number
  onAdded: () => void
}) {
  const [text, setText] = useState('')
  const [progress, setProgress] = useState<string | null>(null)
  const [failures, setFailures] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const ids = riotIdsIn(text)
  const label = PLATFORMS.find((p) => p.id === region)?.label ?? region

  // One at a time: each is a Riot lookup, and the key's limit is shared with
  // every search on the site.
  async function run() {
    setBusy(true)
    setFailures([])
    const failed: string[] = []
    let added = 0
    for (const [i, id] of ids.slice(0, room).entries()) {
      setProgress(`Adding ${i + 1} of ${Math.min(ids.length, room)}: ${id}`)
      try {
        await api.addGroupMember(group.slug, editKey, { riot_id: id, platform: region })
        added += 1
      } catch (error) {
        failed.push(`${id}: ${message(error, 'could not be added')}`)
        if (error instanceof ApiError && error.kind === 'rate_limited') {
          failed.push('Stopped there: the rest can be pasted again in a minute.')
          break
        }
      }
    }
    setBusy(false)
    setProgress(`${added} added.`)
    setFailures(failed)
    if (added) {
      setText('')
      onAdded()
    }
  }

  return (
    <details className="group">
      <summary className="cursor-pointer text-sm text-ink-dim hover:text-ink">
        Paste several at once
      </summary>
      <div className="mt-2 space-y-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={5}
          name="riot-ids"
          aria-label="Riot IDs, one per line"
          placeholder={'One Riot ID per line, or paste the lobby chat:\nFaker#KR1 joined the lobby'}
          className="control w-full resize-y font-mono text-xs leading-relaxed"
        />
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void run()}
            disabled={busy || ids.length === 0 || room <= 0}
            className={button}
          >
            {busy ? 'Adding' : `Add ${Math.min(ids.length, room)} on ${label}`}
          </button>
          <span className="text-xs text-ink-faint">
            {ids.length === 0
              ? 'No Riot IDs found yet.'
              : ids.length > room
                ? `${ids.length} found; only ${room} fit.`
                : `${ids.length} found.`}
          </span>
        </div>
        {progress && <p role="status" className="text-xs text-ink-dim">{progress}</p>}
        {failures.length > 0 && (
          <ul role="alert" className="space-y-0.5 text-xs text-loss">
            {failures.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        )}
      </div>
    </details>
  )
}

function Players({
  group,
  editKey,
  onChanged,
}: {
  group: Group
  editKey: string
  onChanged: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  if (group.members.length === 0) return null

  async function remove(puuid: string) {
    setError(null)
    try {
      await api.removeGroupMember(group.slug, editKey, puuid)
      onChanged()
    } catch (e) {
      setError(message(e, 'That player could not be removed.'))
    }
  }

  async function relabel(puuid: string, label: string) {
    setError(null)
    try {
      await api.setGroupMemberLabel(group.slug, editKey, puuid, label.trim() || null)
      onChanged()
    } catch (e) {
      setError(message(e, 'The label could not be saved.'))
    }
  }

  return (
    <div className="space-y-2">
      <h3 className="display text-base font-700 text-ink">Players</h3>
      <ul className="divide-y divide-line-soft border-y border-line-soft">
        {group.members.map((m) => (
          <li key={m.puuid} className="flex items-center gap-2 py-1.5 text-sm">
            <span className="min-w-0 flex-1 truncate text-ink">{m.riot_id}</span>
            <input
              defaultValue={m.label ?? ''}
              maxLength={24}
              placeholder="Label"
              aria-label={`Label for ${m.riot_id}`}
              className="control w-24 text-xs"
              onBlur={(e) => {
                if (e.target.value.trim() !== (m.label ?? '')) void relabel(m.puuid, e.target.value)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
              }}
            />
            <button
              type="button"
              onClick={() => void remove(m.puuid)}
              className="text-xs text-ink-faint underline decoration-line underline-offset-2 hover:text-loss"
            >
              Remove
            </button>
          </li>
        ))}
      </ul>
      {error && <p role="alert" className="text-xs text-loss">{error}</p>}
    </div>
  )
}

function Settings({
  group,
  editKey,
  onChanged,
  onKeyChanged,
  onDeleted,
}: {
  group: Group
  editKey: string
  onChanged: () => void
  onKeyChanged: (key: string) => void
  onDeleted: () => void
}) {
  const [name, setName] = useState(group.name)
  const [confirm, setConfirm] = useState<'key' | 'delete' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function act(run: () => Promise<void>, fallback: string) {
    setBusy(true)
    setError(null)
    try {
      await run()
    } catch (e) {
      setError(message(e, fallback))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault()
          void act(async () => {
            await api.renameGroup(group.slug, editKey, name)
            onChanged()
          }, 'The name could not be saved.')
        }}
      >
        <h3 className="display text-base font-700 text-ink">Name</h3>
        <div className="flex gap-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={60}
            aria-label="Group name"
            name="group-name"
            className="control min-w-0 flex-1 text-sm"
          />
          <button
            type="submit"
            disabled={busy || !name.trim() || name.trim() === group.name}
            className={button}
          >
            Rename
          </button>
        </div>
      </form>

      <div className="space-y-2">
        <h3 className="display text-base font-700 text-ink">Edit link</h3>
        <p className="text-xs leading-relaxed text-ink-dim">
          Anyone with it can change this group. If it reached someone it should not have, make a
          new one: the old link stops working at once.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <CopyButton text={editLink(group.slug, editKey)} className={button}>
            Copy edit link
          </CopyButton>
          {confirm === 'key' ? (
            <>
              <span className="text-xs text-ink-dim">Every copy of the current edit link stops working.</span>
              <button
                type="button"
                disabled={busy}
                className={button}
                onClick={() =>
                  void act(async () => {
                    const { key } = await api.rotateGroupKey(group.slug, editKey)
                    setConfirm(null)
                    onKeyChanged(key)
                  }, 'A new link could not be made.')
                }
              >
                Make it
              </button>
              <button type="button" className="text-xs text-ink-faint hover:text-ink" onClick={() => setConfirm(null)}>
                Cancel
              </button>
            </>
          ) : (
            <button type="button" className={button} onClick={() => setConfirm('key')}>
              Make a new edit link
            </button>
          )}
        </div>
      </div>

      <div className="space-y-2">
        <h3 className="display text-base font-700 text-ink">Delete</h3>
        {confirm === 'delete' ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-ink-dim">
              The group and both its links go for good. The players' games stay on Riftline.
            </span>
            <button
              type="button"
              disabled={busy}
              className="rounded-sm border border-loss/60 px-3 py-1.5 text-xs font-600 text-loss transition-colors hover:bg-loss-deep disabled:opacity-50"
              onClick={() =>
                void act(async () => {
                  await api.deleteGroup(group.slug, editKey)
                  onDeleted()
                }, 'The group could not be deleted.')
              }
            >
              Delete the group
            </button>
            <button type="button" className="text-xs text-ink-faint hover:text-ink" onClick={() => setConfirm(null)}>
              Cancel
            </button>
          </div>
        ) : (
          <button type="button" className={button} onClick={() => setConfirm('delete')}>
            Delete this group
          </button>
        )}
      </div>
      {error && <p role="alert" className="text-xs text-loss">{error}</p>}
    </div>
  )
}
