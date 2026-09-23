import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'

import type { Group, GroupMember, LaneRecord } from '../../lib/api'
import { pct, positionLabel, scoreColor, timeAgo } from '../../lib/format'
import PositionIcon from '../PositionIcon'
import RankBadge from '../RankBadge'
import ReviewPanel from '../ReviewPanel'
import StrengthsPanel from '../StrengthsPanel'
import { laneColor } from '../story/lanes'
import { COLUMNS, type SortKey } from './sorting'
import { buttonVariants } from '@/components/ui/button'

const SOLO = 'RANKED_SOLO_5x5'

function RankCell({ member }: { member: GroupMember }) {
  const solo = member.ranks.find((r) => r.queue === SOLO && r.tier)
  const shown = solo ?? member.ranks.find((r) => r.tier)
  if (shown) {
    return (
      <span className="inline-flex flex-wrap items-center gap-1.5">
        <RankBadge tier={shown.tier} division={shown.division} leaguePoints={shown.league_points} showLp />
        {!solo && <span className="text-[11px] text-ink-faint">{shown.queue_label}</span>}
      </span>
    )
  }
  if (member.rank_read_at === null) {
    return <span className="text-xs text-ink-faint">Not read yet</span>
  }
  return <RankBadge state="unranked" />
}

function num(value: number | null, digits = 1): string {
  return value === null ? '–' : value.toFixed(digits)
}

function WinRateCell({ member }: { member: GroupMember }) {
  if (member.win_rate === null) {
    return (
      <span className="text-ink-faint" title={member.withheld ?? undefined}>
        –
      </span>
    )
  }
  return (
    <span className={`tnum font-600 ${member.win_rate >= 0.5 ? 'text-ink' : 'text-ink-dim'}`}>
      {pct(member.win_rate)}
    </span>
  )
}

function ScoreCell({ member }: { member: GroupMember }) {
  if (member.avg_score === null) {
    return (
      <span
        className="text-ink-faint"
        title={`${member.scored_games} scored games here; the average needs 5`}
      >
        –
      </span>
    )
  }
  return (
    <span
      className="tnum display text-base font-700"
      style={{ color: scoreColor(member.avg_score) }}
      title={`Over ${member.scored_games} scored games`}
    >
      {member.avg_score.toFixed(1)}
    </span>
  )
}

/** Newest on the left, as the profile's form strip reads. */
function Form({ results }: { results: boolean[] }) {
  if (results.length === 0) return <span className="text-xs text-ink-faint">–</span>
  const wins = results.filter(Boolean).length
  return (
    <span
      className="inline-flex gap-0.5"
      title={`Last ${results.length}, newest first: ${wins} won, ${results.length - wins} lost`}
    >
      {results.map((won, i) => (
        <span
          key={i}
          aria-hidden
          className={`block h-3.5 w-1.5 rounded-[1px] ${won ? 'bg-win' : 'bg-loss/80'}`}
        />
      ))}
      <span className="sr-only">
        {wins} of the last {results.length} won
      </span>
    </span>
  )
}

/** Every role's lanes added up: one bar for the table. */
function LaneStrip({ lanes }: { lanes: LaneRecord[] }) {
  const total = lanes.reduce((n, r) => n + r.games, 0)
  if (total === 0) return <span className="text-xs text-ink-faint">–</span>
  const parts = (['won_big', 'won', 'even', 'lost', 'lost_big'] as const).map((k) => ({
    k,
    n: lanes.reduce((sum, r) => sum + r[k], 0),
  }))
  const won = parts[0].n + parts[1].n
  const lost = parts[3].n + parts[4].n
  return (
    <span className="inline-flex items-center gap-2" title={`At 14 minutes: ${won} won, ${parts[2].n} even, ${lost} lost, of ${total}`}>
      <span className="flex h-1.5 w-16 overflow-hidden rounded-full bg-raised" aria-hidden>
        {parts
          .filter((p) => p.n > 0)
          .map((p) => (
            <span
              key={p.k}
              style={{
                width: `${(p.n / total) * 100}%`,
                background: laneColor(p.k),
                opacity: p.k === 'won' || p.k === 'lost' ? 0.6 : 1,
              }}
            />
          ))}
      </span>
      <span className="tnum text-[11px] text-ink-faint">
        {won}-{parts[2].n}-{lost}
      </span>
    </span>
  )
}

function profileHref(m: GroupMember): string | null {
  if (!m.game_name || !m.tag_line) return null
  return `/summoner/${m.platform}/${encodeURIComponent(m.game_name)}/${encodeURIComponent(m.tag_line)}`
}

function PlayerCell({ member, cap }: { member: GroupMember; cap: number }) {
  const href = profileHref(member)
  const name = member.game_name ?? member.riot_id
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      {member.profile_icon_url ? (
        <img src={member.profile_icon_url} alt="" className="size-8 shrink-0 ring-1 ring-line" loading="lazy" decoding="async" />
      ) : (
        <span className="size-8 shrink-0 bg-raised ring-1 ring-line" aria-hidden />
      )}
      <span className="min-w-0">
        <span className="flex min-w-0 items-baseline gap-1.5">
          {href ? (
            <Link
              to={href}
              className="display truncate text-[16px] font-600 text-ink transition-colors hover:text-gold-bright"
            >
              {name}
              <span className="ml-0.5 text-[13px] font-400 text-ink-faint">#{member.tag_line}</span>
            </Link>
          ) : (
            <span className="display truncate text-[16px] font-600 text-ink">{name}</span>
          )}
          {member.label && (
            <span className="shrink-0 rounded-sm bg-raised px-1.5 py-px text-[11px] font-600 text-gold-bright">
              {member.label}
            </span>
          )}
        </span>
        <span className="block truncate text-[11px] text-ink-faint">
          {member.platform_label}
          {member.history.pending
            ? `, loading: ${member.history.stored.toLocaleString('en-US')} of up to ${cap.toLocaleString('en-US')} games`
            : `, ${member.history.stored.toLocaleString('en-US')} games stored`}
        </span>
      </span>
    </span>
  )
}

function ExpandButton({
  open,
  onClick,
  name,
}: {
  open: boolean
  onClick: () => void
  name: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={open}
      aria-label={`${open ? 'Hide' : 'Show'} details for ${name}`}
      className={buttonVariants({ variant: 'outline', size: 'xs' })}
    >
      {open ? 'Less' : 'More'}
    </button>
  )
}

export default function MemberTable({
  group,
  members,
  sort,
  onSort,
}: {
  group: Group
  members: GroupMember[]
  sort: SortKey
  onSort: (key: SortKey) => void
}) {
  const [open, setOpen] = useState<Set<string>>(() => new Set())
  const toggle = (puuid: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(puuid)) next.delete(puuid)
      else next.add(puuid)
      return next
    })
  const columns = COLUMNS.filter((c) => group.scored_mode || !c.scoredOnly)
  const span = 5 + columns.length + (group.scored_mode ? 1 : 0)

  return (
    <>
      <div className="hidden overflow-x-auto lg:block">
        <table className="w-full min-w-[980px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-xs text-ink-faint">
              <th className="w-8 py-2 text-left font-500">#</th>
              <th className="py-2 text-left font-500">Player</th>
              <th className="py-2 text-left font-500" aria-sort={sort === 'rank' ? 'descending' : 'none'}>
                <SortButton active={sort === 'rank'} onClick={() => onSort('rank')} title="Official rank, then LP">
                  Rank
                </SortButton>
              </th>
              {columns.map((c) => (
                <th key={c.key} className="py-2 pl-3 text-right font-500" aria-sort={sort === c.key ? 'descending' : 'none'}>
                  <SortButton active={sort === c.key} onClick={() => onSort(c.key)} title={c.title}>
                    {c.label}
                  </SortButton>
                </th>
              ))}
              <th className="py-2 pl-3 text-left font-500">Role</th>
              {group.scored_mode && (
                <th className="py-2 pl-3 text-left font-500" title="Lanes won, even and lost at 14 minutes">
                  Lanes
                </th>
              )}
              <th className="py-2 pl-3 text-left font-500">Last 10</th>
              <th className="py-2 pl-3" aria-label="Details" />
            </tr>
          </thead>
          <tbody>
            {members.map((m, i) => {
              const isOpen = open.has(m.puuid)
              return (
                <Fragment key={m.puuid}>
                  <tr className="lift border-b border-line-soft">
                    <td className="tnum py-2.5 text-xs text-ink-faint">{i + 1}</td>
                    <td className="max-w-[260px] py-2.5 pr-3">
                      <PlayerCell member={m} cap={group.history_cap} />
                    </td>
                    <td className="py-2.5">
                      <RankCell member={m} />
                    </td>
                    {columns.map((c) => (
                      <td key={c.key} className="tnum py-2.5 pl-3 text-right text-ink-dim">
                        {c.key === 'win_rate' ? (
                          <WinRateCell member={m} />
                        ) : c.key === 'score' ? (
                          <ScoreCell member={m} />
                        ) : c.key === 'games' ? (
                          <span className="text-ink">{m.games.toLocaleString('en-US')}</span>
                        ) : c.key === 'damage' ? (
                          m.damage_per_min === null ? '–' : Math.round(m.damage_per_min).toLocaleString('en-US')
                        ) : (
                          num(c.value(m), c.key === 'kda' ? 2 : 1)
                        )}
                      </td>
                    ))}
                    <td className="py-2.5 pl-3">
                      {m.main_position ? (
                        <span className="flex items-center gap-1.5 text-xs text-ink-dim" title={positionLabel(m.main_position)}>
                          <PositionIcon position={m.main_position} className="size-4" />
                          <span className="tnum">{pct(m.positions[0]?.share ?? 0)}</span>
                        </span>
                      ) : (
                        <span className="text-xs text-ink-faint">–</span>
                      )}
                    </td>
                    {group.scored_mode && (
                      <td className="py-2.5 pl-3">
                        <LaneStrip lanes={m.lanes} />
                      </td>
                    )}
                    <td className="py-2.5 pl-3">
                      <Form results={m.recent} />
                    </td>
                    <td className="py-2.5 pl-3 text-right">
                      <ExpandButton open={isOpen} onClick={() => toggle(m.puuid)} name={m.riot_id} />
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="border-b border-line-soft bg-panel/40">
                      <td colSpan={span} className="px-3 py-4">
                        <MemberDetail member={m} group={group} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Phones and narrow windows: the table needs about 980px, so below lg
          each player is a card with the same figures, and the same details. */}
      <ul className="lg:hidden">
        {members.map((m, i) => {
          const isOpen = open.has(m.puuid)
          return (
            <li key={m.puuid} className="border-b border-line-soft py-3">
              <div className="grid grid-cols-[1.25rem_minmax(0,1fr)_auto] items-center gap-x-2.5">
                <span className="tnum text-xs text-ink-faint">{i + 1}</span>
                <PlayerCell member={m} cap={group.history_cap} />
                <RankCell member={m} />
              </div>
              <div className="tnum mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 pl-[1.875rem] text-xs text-ink-dim">
                <span>
                  <span className="text-ink">{m.games}</span> games
                </span>
                <span>
                  <WinRateCell member={m} /> won
                </span>
                <span>KDA {num(m.kda, 2)}</span>
                {group.scored_mode && (
                  <span>
                    Score <ScoreCell member={m} />
                  </span>
                )}
                <Form results={m.recent} />
                <span className="ml-auto">
                  <ExpandButton open={isOpen} onClick={() => toggle(m.puuid)} name={m.riot_id} />
                </span>
              </div>
              {isOpen && (
                <div className="mt-3">
                  <MemberDetail member={m} group={group} />
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </>
  )
}

function SortButton({
  active,
  onClick,
  title,
  children,
}: {
  active: boolean
  onClick: () => void
  title: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={`border-b-2 pb-0.5 transition-colors ${
        active ? 'border-gold text-gold-bright' : 'border-transparent hover:text-ink'
      }`}
    >
      {children}
    </button>
  )
}

function MemberDetail({ member, group }: { member: GroupMember; group: Group }) {
  const h = member.history
  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-3">
        <section className="frame">
          <header className="border-b border-line-soft px-4 py-2.5">
            <h3 className="eyebrow">Record in these queues</h3>
          </header>
          <div className="space-y-3 px-4 py-3 text-xs">
            {member.withheld ? (
              <p className="text-ink-dim">{member.withheld}.</p>
            ) : (
              <dl className="tnum grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                <dt className="text-ink-faint">Won</dt>
                <dd className="text-ink">
                  {member.wins} of {member.games}
                </dd>
                <dt className="text-ink-faint">Per game</dt>
                <dd className="text-ink">
                  {num(member.avg_kills)} / {num(member.avg_deaths)} / {num(member.avg_assists)}
                </dd>
                <dt className="text-ink-faint">CS per minute</dt>
                <dd className="text-ink">{num(member.cs_per_min)}</dd>
                <dt className="text-ink-faint">Damage per minute</dt>
                <dd className="text-ink">
                  {member.damage_per_min === null ? '–' : Math.round(member.damage_per_min).toLocaleString('en-US')}
                </dd>
                <dt className="text-ink-faint">Vision per minute</dt>
                <dd className="text-ink">{num(member.vision_per_min, 2)}</dd>
                <dt className="text-ink-faint">Game length</dt>
                <dd className="text-ink">{num(member.avg_minutes, 0)} min</dd>
              </dl>
            )}
            {member.positions.length > 0 && (
              <ul className="flex flex-wrap gap-x-3 gap-y-1">
                {member.positions.map((p) => (
                  <li key={p.position} className="flex items-center gap-1 text-ink-dim" title={`${p.games} games, ${pct(p.win_rate)} won`}>
                    <PositionIcon position={p.position} className="size-3.5" />
                    <span className="tnum">{pct(p.share)}</span>
                  </li>
                ))}
              </ul>
            )}
            {member.champions.length > 0 && (
              <ul className="space-y-1.5">
                {member.champions.map((c) => (
                  <li key={c.champion.id} className="flex items-center gap-2">
                    {c.champion.icon_url && (
                      <img src={c.champion.icon_url} alt="" className="size-6 ring-1 ring-line" loading="lazy" decoding="async" />
                    )}
                    <span className="min-w-0 flex-1 truncate text-ink">{c.champion.name}</span>
                    <span className="tnum text-ink-dim">
                      {c.games} games, {pct(c.win_rate)}, {c.kda.toFixed(2)} KDA
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        {group.scored_mode ? (
          <>
            {member.score_profile.length > 0 ? (
              <StrengthsPanel profiles={member.score_profile} />
            ) : (
              <Note>No scored games in these queues yet.</Note>
            )}
            {member.review.length > 0 || member.lanes.length > 0 ? (
              <ReviewPanel review={member.review} lanes={member.lanes} />
            ) : (
              <Note>
                The death review and lane labels read timelines, which are fetched for each
                player's newest ranked games. None here yet.
              </Note>
            )}
          </>
        ) : (
          <Note>
            {group.queues.find((q) => q.key === group.queue)?.label} has no lanes, so there is no
            Riftline score, death review or lane label here.
          </Note>
        )}
      </div>
      <p className="text-xs leading-relaxed text-ink-faint">
        {h.stored.toLocaleString('en-US')} games of theirs stored in every queue
        {h.oldest ? `, the oldest ${timeAgo(h.oldest)}` : ''}.{' '}
        {h.exhausted
          ? "That is all of their history Riot still lists."
          : h.read >= group.history_cap
            ? `Their newest ${group.history_cap.toLocaleString('en-US')} are read, the most this group reads.`
            : `${h.read.toLocaleString('en-US')} of their newest ${group.history_cap.toLocaleString('en-US')} read so far.`}
        {member.rank_read_at && ` Rank read ${timeAgo(member.rank_read_at)}.`}
      </p>
    </div>
  )
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <p className="accent-edge self-start bg-panel/50 py-2.5 pl-4 pr-3 text-xs leading-relaxed text-ink-dim">
      {children}
    </p>
  )
}
