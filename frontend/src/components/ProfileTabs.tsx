import { useQuery } from '@tanstack/react-query'

import NavTabs, { type NavTab } from './NavTabs'
import { api, type QueueScope } from '../lib/api'
import { summonerPath } from '../lib/profileAddress'
import { scopeParam } from '../lib/profileScope'

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
  scope,
  className = 'ml-auto',
}: {
  platform: string
  name: string
  tag: string
  className?: string
  /** Carried between the overview and the champions tab, which read the same
   *  games; mastery and the live game are not about a set of games. */
  scope?: QueueScope
}) {
  // No options of its own. `App` already mounts `['health']` with a five-minute poll
  // for the whole session, and a second observer with different staleTime and
  // retry settings just races it for the shared query's configuration.
  const health = useQuery({ queryKey: ['health'], queryFn: api.health })

  const base = summonerPath(platform, name, tag)
  const word = scope ? scopeParam(scope) : null
  const carried = word ? `?queue=${word}` : ''
  const tabs: NavTab[] = [
    { to: `${base}${carried}`, label: 'Overview', end: true },
    { to: `${base}/champions${carried}`, label: 'Champions' },
    { to: `${base}/mastery`, label: 'Mastery' },
  ]
  // Shown unless health has positively said the feature is off. Gating on a
  // truthy value meant a health request that simply had not resolved yet hid
  // the tab, including while standing on /live, where the strip then showed no
  // active tab at all.
  if (health.data?.spectator_enabled !== false) {
    tabs.push({ to: `${base}/live`, label: 'Live' })
  }

  return <NavTabs tabs={tabs} label="Player sections" className={className} />
}
