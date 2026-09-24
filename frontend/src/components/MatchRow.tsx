import { useState } from 'react'
import { Link } from 'react-router-dom'

import type { MatchSummary, ParticipantBrief } from '../lib/api'
import RankBadge from './RankBadge'
import TimeAgo from './TimeAgo'
import ItemIcon from './items/ItemIcon'
import Scoreboard from './match/Scoreboard'
import { LANE_TEXT, laneColor } from './story/lanes'
import { useNow } from '../lib/clock'

// Ranked solo and flex: the queues the win-chance model covers.
const STORY_QUEUES = new Set([420, 440])
import {
  compact,
  duration,
  kdaColor,
  kdaRatio,
  ordinal,
  pct,
  positionLabel,
  scoreColor,
  timeAgo,
} from '../lib/format'
import Hint from './Hint'
import { summonerPath } from '../lib/profileAddress'
import { WITHHELD, withheldText } from '../lib/withheld'

/**
 * One game in the history feed.
 *
 * A row, not a card. Twenty identical bordered rectangles stacked vertically
 * read as twenty separate objects; a match history is one list, so the rows sit
 * flush and a hairline does the separating. Result is carried by a single edge
 * stripe plus a faint tint rather than washing the whole row in colour, so a
 * losing streak stays readable instead of turning the page into a red wall.
 */
export default function MatchRow({
  match,
  platform,
  puuid,
}: {
  match: MatchSummary
  platform: string
  /** Whose history this is, so the scoreboard can mark their line. */
  puuid: string
}) {
  const [open, setOpen] = useState(false)
  // Once opened the scoreboard stays mounted, so closing rolls it shut rather
  // than cutting it off, and opening again costs no request.
  const [opened, setOpened] = useState(false)
  const now = useNow()
  const { win, is_remake: remake } = match
  // Why there is no score, in words: the API's reason, in scoring's order.
  const withheld =
    match.score === null ? (withheldText(match.score_withheld) ?? WITHHELD.not_scored_yet) : null

  const edge = remake
    ? 'var(--color-ink-faint)'
    : win
      ? 'var(--color-win)'
      : 'var(--color-loss)'
  const tint = remake
    ? 'transparent'
    : win
      ? 'color-mix(in srgb, var(--color-win) 7%, transparent)'
      : 'color-mix(in srgb, var(--color-loss) 7%, transparent)'

  return (
    <article
      className="border-b border-l-[3px] border-line-soft border-l-transparent"
      style={{ borderLeftColor: edge, background: `linear-gradient(0deg, ${tint}, ${tint})` }}
    >
    <div className="grid grid-cols-1 gap-x-4 gap-y-3 px-3 py-3 lift sm:grid-cols-[104px_auto_1fr_auto]">
      {/* Context */}
      <div className="flex items-baseline gap-2 sm:block">
        <p className="eyebrow truncate text-ink-dim">{match.queue_name}</p>
        <p className="text-xs text-ink-faint">
          <TimeAgo at={match.game_creation} />
        </p>
        {/* Measured, unlike the crawl bracket, but measured *late*: Riot keeps
            no historical rank, so this is where these players sit today, not
            where they sat when the game was played. The tooltip says so. */}
        {match.lobby_rank_tier && (
          // The caveat goes on the badge itself. Wrapping it in a titled span
          // did nothing: RankBadge sets its own title, the inner one wins on
          // hover, and the wrapper was `w-fit` with no padding, so there was no
          // pixel where the outer tooltip could ever fire.
          <span className="mt-1 hidden items-center gap-1.5 sm:inline-flex">
            <RankBadge
              tier={match.lobby_rank_tier}
              division={match.lobby_rank_division}
              title={
                `Median rank of the ${match.lobby_ranked_players} of ` +
                `${match.lobby_players_total} players we could identify, measured ` +
                `${match.lobby_rank_measured_at ? timeAgo(match.lobby_rank_measured_at, now) : 'later'}. ` +
                'This is their rank now, not their rank when this game was played.' +
                (match.lobby_queue_matches_game
                  ? ''
                  : ' This mode has no rank of its own, so it is their solo queue standing.')
              }
            />
            {/* Visible, not only in a tooltip: a lobby identified 6 of 10 and
                one identified 10 of 10 otherwise render identically. */}
            <span className="tnum text-[11px] text-ink-faint">
              {match.lobby_ranked_players}/{match.lobby_players_total}
            </span>
          </span>
        )}
        <p className="mt-0 text-xs text-ink-faint sm:mt-1.5">
          <span className={remake ? 'text-ink-faint' : win ? 'text-win' : 'text-loss'}>
            {remake ? 'Remake' : win ? 'Win' : 'Loss'}
          </span>
          <span className="mx-1.5 text-line">|</span>
          <span className="tnum">{duration(match.game_duration)}</span>
        </p>
      </div>

      {/* Champion, spells, runes */}
      <div className="flex items-center gap-2">
        <div className="relative shrink-0">
          {match.champion.icon_url && (
            <img
              src={match.champion.icon_url}
              alt={match.champion.name}
              className="size-12 rounded-sm"
              loading="lazy"
            />
          )}
          <span className="tnum absolute -bottom-1 -right-1 rounded-full bg-deep px-1.5 text-[11px] font-600 text-ink-dim ring-1 ring-line">
            {match.champ_level}
          </span>
        </div>

        <div className="flex flex-col gap-0.5">
          {match.spells.map((s, i) => (
            <img
              key={`${s.id}-${i}`}
              src={s.icon_url ?? undefined}
              alt={s.name ?? ''}
              title={s.name ?? ''}
              className="size-[22px] rounded-sm bg-raised"
              loading="lazy"
            />
          ))}
        </div>

        <div className="flex flex-col gap-0.5">
          {[match.keystone, match.secondary_tree].map((r, i) => (
            <span
              key={i}
              className="grid size-[22px] place-items-center rounded-full bg-raised"
            >
              {r?.icon_url && <img src={r.icon_url} alt="" className="size-5" loading="lazy" />}
            </span>
          ))}
        </div>
      </div>

      {/* Numbers */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div>
          <p className="tnum display text-[22px] font-700 text-ink">
            {match.kills} <span className="text-ink-faint">/</span>{' '}
            <span className="text-loss">{match.deaths}</span>{' '}
            <span className="text-ink-faint">/</span> {match.assists}
          </p>
          <p
            className="tnum text-xs font-600"
            style={{ color: kdaColor(match.kda, match.deaths) }}
          >
            {kdaRatio(match.kills, match.deaths, match.assists)} KDA
          </p>
          {/* Only present once this match's timeline has been fetched. Rows
              without one simply omit it rather than showing a placeholder. */}
          {match.score !== null && (
            <p className="mt-1 flex items-baseline gap-1.5">
              <Hint
                text={
                  `Riftline score ${match.score.toFixed(1)} of 10, ` +
                  `${ordinal(match.placement ?? 0)} of ten in this lobby. ` +
                  (match.score_sample
                    ? `Measured against ${match.score_sample.toLocaleString('en-US')} games in this role.`
                    : '')
                }
              >
                <span
                  tabIndex={0}
                  className="tnum display text-[17px] font-700 outline-none"
                  style={{ color: scoreColor(match.score) }}
                >
                  {match.score.toFixed(1)}
                </span>
              </Hint>
              <span className="text-[11px] text-ink-faint">
                {ordinal(match.placement ?? 0)} of 10
              </span>
            </p>
          )}
          {/*
            A withheld score is its reason in words, never a blank and never a
            zero. Leaving it out told a reader with a page of ARAM games nothing
            about why the column was empty, and the dash that followed was 1.3
            to 1 against the page.
          */}
          {withheld && (
            <Hint text={withheld.long}>
              <p tabIndex={0} className="mt-1 text-xs text-ink-faint outline-none">
                {withheld.short}
              </p>
            </Hint>
          )}
          {/* At most two: the rarest earned badges, which is the order the
              server sends them in. The rest are on the scoreboard. */}
          {match.badges.length > 0 && (
            <p className="mt-1 flex flex-wrap gap-1">
              {match.badges.slice(0, 2).map((badge) => (
                <Hint key={badge.id} text={badge.detail}>
                  <span tabIndex={0} className="w-fit rounded-sm bg-gold/15 px-1.5 py-0.5 text-[11px] font-600 text-gold-bright">
                    {badge.label}
                  </span>
                </Hint>
              ))}
            </p>
          )}
          {match.laning_score !== null && (
            <p
              className="tnum mt-0.5 text-xs text-ink-faint"
              title={
                match.laning_opponent
                  ? `Laning phase at 14 minutes against ${match.laning_opponent.name}` +
                    (match.gold_diff_14 !== null
                      ? `: ${match.gold_diff_14 >= 0 ? '+' : ''}${match.gold_diff_14} gold`
                      : '')
                  : 'Laning phase at 14 minutes'
              }
            >
              <span className="text-ink-faint">Laning </span>
              <span
                style={{
                  color:
                    match.laning_score >= 0.5
                      ? 'var(--color-win)'
                      : 'var(--color-loss)',
                }}
              >
                {Math.round(match.laning_score * 100)}
              </span>
              <span className="text-line"> : </span>
              {100 - Math.round(match.laning_score * 100)}
              {match.laning_label && (
                <span className="ml-1.5" style={{ color: laneColor(match.laning_label) }}>
                  {LANE_TEXT[match.laning_label]}
                </span>
              )}
            </p>
          )}
        </div>

        <dl className="grid grid-cols-2 gap-x-5 gap-y-0.5 text-xs text-ink-dim sm:grid-cols-1">
          <div className="flex gap-1.5">
            <dt className="text-ink-faint">CS</dt>
            <dd className="tnum">
              {match.cs}{' '}
              <span className="text-ink-faint">({match.cs_per_min.toFixed(1)}/m)</span>
            </dd>
          </div>
          <div className="flex gap-1.5">
            <dt className="text-ink-faint">KP</dt>
            <dd className="tnum">{pct(match.kill_participation)}</dd>
          </div>
        </dl>

        <dl className="grid grid-cols-2 gap-x-5 gap-y-0.5 text-xs text-ink-dim sm:grid-cols-1">
          <div className="flex gap-1.5">
            <dt className="text-ink-faint">Dmg</dt>
            <dd className="tnum">{compact(match.damage_to_champions)}</dd>
          </div>
          <div className="flex gap-1.5">
            <dt className="text-ink-faint">Vis</dt>
            <dd className="tnum">{match.vision_score}</dd>
          </div>
        </dl>

        <div className="flex flex-col gap-1.5">
          <div className="flex gap-1">
            {match.items.map((item, i) => (
              <ItemIcon key={i} item={item} size={26} className="rounded-sm bg-raised" />
            ))}
            {match.trinket && (
              <ItemIcon item={match.trinket} size={26} className="rounded-full bg-raised" />
            )}
          </div>
          {match.multi_kill && (
            <span className="w-fit rounded-sm bg-gold/15 px-1.5 py-0.5 text-[11px] font-600 text-gold-bright">
              {match.multi_kill}
            </span>
          )}
        </div>
      </div>

      {/* Both teams, and the way into the full scoreboard */}
      <div className="flex items-start gap-2">
        <div className="hidden grid-cols-2 gap-x-4 lg:grid">
          {match.teams.map((team, i) => (
            <ul key={i} className="space-y-[3px]">
              {team.map((p) => (
                <TeamMember key={p.puuid || `${i}-${p.champion.id}`} p={p} platform={platform} />
              ))}
            </ul>
          ))}
        </div>
        <Hint text={open ? 'Hide the scoreboard' : 'Every player, scored'}>
        <button
          onClick={() => {
            setOpen((o) => !o)
            setOpened(true)
          }}
          aria-expanded={open}
          aria-label={open ? 'Hide the scoreboard' : 'Show the scoreboard'}
          className="ml-auto shrink-0 self-center rounded-sm px-1.5 py-3 text-ink-faint transition-colors hover:bg-raised hover:text-ink"
        >
          <svg
            viewBox="0 0 10 6"
            aria-hidden="true"
            focusable="false"
            className={`size-2.5 transition-transform ${open ? 'rotate-180' : ''}`}
          >
            <path
              d="M1 1l4 4 4-4"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
            />
          </svg>
        </button>
        </Hint>
      </div>
    </div>

    {/* The scoreboard rolls open rather than appearing. A grid row going from
        0fr to 1fr is the one way CSS animates to a height it does not know;
        the inner box clips while the row grows. */}
    <div
      className="grid transition-[grid-template-rows] duration-200 ease-out"
      style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
    >
      <div className="min-h-0 overflow-hidden" inert={!open} aria-hidden={!open}>
        {opened && (
          <Scoreboard
            matchId={match.match_id}
            subjectPuuid={puuid}
            platform={platform}
            // Only where a story exists: the win-chance model is trained on
            // ranked Summoner's Rift, and ARAM or Arena would link to a page
            // saying so.
            storyHref={
              STORY_QUEUES.has(match.queue_id)
                ? `/match/${encodeURIComponent(match.match_id)}?player=${encodeURIComponent(puuid)}`
                : undefined
            }
          />
        )}
      </div>
    </div>
    </article>
  )
}

function TeamMember({ p, platform }: { p: ParticipantBrief; platform: string }) {
  const [name, tag] = (p.riot_id ?? '').split('#')
  const label = name || 'Unknown'
  return (
    <li className="flex items-center gap-1.5 text-[11px] leading-none">
      {p.champion.icon_url && (
        <img
          src={p.champion.icon_url}
          alt={p.champion.name}
          title={`${p.champion.name}, ${positionLabel(p.position)}`}
          className="size-4 shrink-0 rounded-sm"
          loading="lazy"
        />
      )}
      {name && tag ? (
        <Link
          to={summonerPath(platform, name, tag)}
          className="truncate text-ink-dim hover:text-gold-bright hover:underline"
        >
          {label}
        </Link>
      ) : (
        <span className="truncate text-ink-faint">{label}</span>
      )}
    </li>
  )
}
