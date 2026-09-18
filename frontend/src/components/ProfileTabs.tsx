import { NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { api } from '../lib/api'

/**
 * The Overview / Champions / Mastery / Live nav on a summoner page.
 *
 * Extracted because it was written out twice, in Profile and in Mastery, and the
 * two had already drifted apart in how they mark the current tab.
 *
 * Live only appears when the server says spectator lookups are available. Riot
 * announced Spectator-V5's deactivation in 2025, so the day it goes the tab
 * should quietly stop existing rather than becoming a link to an error.
 */
export default function ProfileTabs({
  platform,
  name,
  tag,
}: {
  platform: string
  name: string
  tag: string
}) {
  // No options of its own. `App` already mounts `['health']` with a 30s poll
  // for the whole session, and a second observer with different staleTime and
  // retry settings just races it for the shared query's configuration.
  const health = useQuery({ queryKey: ['health'], queryFn: api.health })

  const base = `/summoner/${platform}/${encodeURIComponent(name)}/${encodeURIComponent(tag)}`
  const tabs: { to: string; label: string; end?: boolean }[] = [
    { to: base, label: 'Overview', end: true },
    { to: `${base}/champions`, label: 'Champions' },
    { to: `${base}/mastery`, label: 'Mastery' },
  ]
  // Shown unless health has positively said the feature is off. Gating on a
  // truthy value meant a health request that simply had not resolved yet hid
  // the tab, including while standing on /live, where the strip then showed no
  // active tab at all.
  if (health.data?.spectator_enabled !== false) {
    tabs.push({ to: `${base}/live`, label: 'Live' })
  }

  return (
    <nav className="ml-auto flex gap-1 text-sm">
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          end={tab.end}
          to={tab.to}
          className={({ isActive }) =>
            `border-b-2 px-3 pb-1.5 pt-1 font-display font-600 transition-colors ${
              isActive
                ? 'border-gold text-gold-bright'
                : 'border-transparent text-ink-dim hover:text-ink'
            }`
          }
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  )
}
