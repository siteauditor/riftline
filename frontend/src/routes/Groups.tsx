import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'

import Head from '../components/Head'
import { api } from '../lib/api'
import { heads } from '../lib/seo'
import { timeAgo } from '../lib/format'
import { forgetGroup, rememberGroup, useSavedGroups } from '../lib/groups'

/**
 * Make a group, and the groups this browser has made or opened.
 *
 * There is no login: a group is two links, one to look and one to change it,
 * and "your groups" is this browser's memory of both.
 */
export default function Groups() {
  const saved = useSavedGroups()
  const navigate = useNavigate()
  const [name, setName] = useState('')

  const create = useMutation({
    mutationFn: (value: string) => api.createGroup(value),
    onSuccess: (group) => {
      rememberGroup({ slug: group.slug, name: group.name, key: group.key })
      navigate(`/g/${group.slug}`)
    },
  })

  return (
    <div className="mx-auto max-w-[860px] space-y-8 px-4 py-8">
      <Head {...heads.groups()} />
      <header>
        <p className="eyebrow">Groups</p>
        <h1 className="display mt-1 text-[clamp(2rem,5vw,3rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
          Your players, side by side
        </h1>
        <p className="mt-3 max-w-[64ch] text-sm leading-relaxed text-ink-dim">
          Put up to 20 players in one table: a team, a Clash roster, a group of friends. Riftline
          reads each player's history from Riot and shows their rank, record, score and lanes
          together, in every queue or one at a time.
        </p>
      </header>

      <form
        className="frame flex flex-wrap items-end gap-3 px-4 py-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) create.mutate(name.trim())
        }}
      >
        <label className="flex min-w-[14rem] flex-1 flex-col gap-1.5 text-xs">
          <span className="text-ink-faint">Group name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={60}
            placeholder="Clash team, Friday five…"
            className="control w-full text-sm"
            name="group-name"
          />
        </label>
        <button
          type="submit"
          disabled={!name.trim() || create.isPending}
          className="rounded-sm bg-accent px-4 py-2 text-sm font-700 text-deep transition-colors hover:bg-accent-bright disabled:opacity-50"
        >
          {create.isPending ? 'Making it' : 'Make the group'}
        </button>
        {create.isError && (
          <p role="alert" className="w-full text-xs text-loss">
            {create.error instanceof Error ? create.error.message : 'The group could not be made.'}
          </p>
        )}
      </form>

      <section aria-labelledby="links-heading" className="grid gap-4 text-sm sm:grid-cols-2">
        <h2 id="links-heading" className="sr-only">
          How the links work
        </h2>
        <div className="accent-edge bg-panel/50 py-3 pl-4 pr-3">
          <p className="display text-base font-700 text-ink">The view link</p>
          <p className="mt-1 leading-relaxed text-ink-dim">
            Shows the group to anyone who has it. Search engines are told to leave it out.
          </p>
        </div>
        <div className="accent-edge bg-panel/50 py-3 pl-4 pr-3">
          <p className="display text-base font-700 text-ink">The edit link</p>
          <p className="mt-1 leading-relaxed text-ink-dim">
            Adds and removes players. It works like a password: give it only to people who
            should change the group. You can replace it if it gets out.
          </p>
        </div>
      </section>

      <section aria-labelledby="saved-heading">
        <h2 id="saved-heading" className="display text-xl font-700 text-ink">
          In this browser
        </h2>
        {saved.length === 0 ? (
          <p className="mt-2 text-sm text-ink-dim">
            No groups yet. Groups you make or open are listed here, in this browser only.
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-line-soft border-y border-line-soft">
            {saved.map((group) => (
              <li key={group.slug} className="flex items-center gap-3 py-2.5">
                <Link
                  to={`/g/${group.slug}`}
                  className="display min-w-0 flex-1 truncate text-[17px] font-600 text-ink transition-colors hover:text-gold-bright"
                >
                  {group.name}
                </Link>
                <span className="shrink-0 text-xs text-ink-faint">
                  {group.key ? 'You can edit' : 'View only'}, opened {timeAgo(group.at)}
                </span>
                <button
                  type="button"
                  onClick={() => forgetGroup(group.slug)}
                  title={
                    group.key
                      ? 'Remove it from this browser. Keep the edit link somewhere first, or you cannot change the group again.'
                      : 'Remove it from this browser. The group itself stays.'
                  }
                  className="shrink-0 text-xs text-ink-faint underline decoration-line underline-offset-2 hover:text-ink"
                >
                  Forget
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
