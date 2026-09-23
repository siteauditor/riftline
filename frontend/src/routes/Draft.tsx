import { useMemo, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'

import ArtHeader from '../components/ArtHeader'
import Head from '../components/Head'
import SelectField from '../components/SelectField'
import ChampionPicker from '../components/ChampionPicker'
import CopyButton from '../components/CopyButton'
import PositionIcon from '../components/PositionIcon'
import { Results, SuggestionSkeleton } from '../components/draft/Results'
import RiotIdField from '../components/draft/RiotIdField'
import Slot from '../components/draft/Slot'
import TeamMix from '../components/draft/TeamMix'
import { useDraftBoard } from '../components/draft/useDraftBoard'
import { EmptyState, ErrorView } from '../components/StateViews'
import { api, POSITIONS, type DraftRequest, type DraftResponse } from '../lib/api'
import {
  CAPS,
  COMFORT_LEVELS,
  MAX_CHECKS,
  addCheck,
  addTo,
  boardIsSet,
  clearBoard,
  minGamesOptions,
  removeCheck,
  removeFrom,
  requestKey,
  setComfort,
  setLaneUnknown,
  setMinGames,
  setRole,
  toggleLane,
  unavailable,
  type RiotIdChoice,
} from '../lib/draftBoard'
import { parseRiotId, pct, plausibleRiotId, positionLabel } from '../lib/format'
import { queries } from '../lib/queries'
import { heads } from '../lib/seo'
import { rememberRegion, useLastRegion, useLastRiotId } from '../lib/storage'
import { useChampionArt } from '../lib/useChampionArt'
import { useDebounced } from '../lib/useDebounced'
import { Chip, ChipGroup } from '@/components/ui/chips'
import { toast } from 'sonner'

// Long enough that adding two champions in a row is one request, short enough
// that the list re-ranks while the hand is still on the mouse.
const RERANK_MS = 250

/**
 * Draft assistant.
 *
 * Every suggestion shows its reasoning, and the list is ordered by what the
 * records actually support rather than what they claim: measured on the live
 * API on 2026-09-21, a 10-2 lane record over twelve games was lifting a pick
 * from 50.7% to 60.0% and putting it top. The page therefore shows both the
 * supported score it ranks on and the unrestrained "if that holds" figure.
 *
 * The board lives in the URL so a draft can be shared or reloaded, read through
 * `useHydratedSearchParams` because the prerendered HTML is the empty board
 * whatever the link says. The Riot ID does not: it identifies a person, so it
 * stays in this browser.
 */
export default function Draft() {
  const { board, update, hydrated } = useDraftBoard()
  const taken = unavailable(board)

  const [chosenRegion, setChosenRegion] = useState<string | null>(null)
  const rememberedRegion = useLastRegion()
  const platform = chosenRegion ?? rememberedRegion ?? 'euw1'
  const savedRiotId = useLastRiotId()
  const parsedRiotId = savedRiotId ? parseRiotId(savedRiotId) : null
  const riot: RiotIdChoice | null =
    parsedRiotId && plausibleRiotId(parsedRiotId)
      ? { platform, name: parsedRiotId.name, tag: parsedRiotId.tag }
      : null

  const { data: championData } = useQuery({
    ...queries.champions(),
    staleTime: 6 * 60 * 60 * 1000,
  })
  const championById = useMemo(
    () => new Map((championData?.champions ?? []).map((c) => [c.id, c])),
    [championData],
  )

  // The request as a string, settled: a primitive, so the debounce compares by
  // value, and the query waits until it has settled rather than asking once for
  // every champion added in a burst.
  const key = requestKey(board, riot)
  const settledKey = useDebounced(key, RERANK_MS)
  const draft = useQuery({
    queryKey: ['draft', settledKey],
    queryFn: ({ signal }) => api.draft(JSON.parse(settledKey) as DraftRequest, signal),
    // Not while hydrating (the prerendered page is the empty board) and not
    // while the key is still settling, so a link with a board in it asks once.
    enabled: hydrated && settledKey === key,
    // The previous ranking stays on screen while the next one loads, so adding
    // a champion never blanks the page.
    placeholderData: keepPreviousData,
    retry: false,
  })

  const corpus = useQuery(queries.corpus())
  const empty = corpus.data && corpus.data.total_matches === 0
  // Who you are facing, else who you know is on the board. Not the top
  // suggestion: that changed with every champion added, and the header art
  // swapped with it.
  const heroArt = useChampionArt(board.lane ?? board.enemies[0] ?? board.allies[0] ?? null)
  const read = draft.data
  // Each enemy's likely role, from the last answer, for the enemy chips.
  const enemyRole = new Map(
    (read?.enemy_roles ?? []).map((r) => [r.champion.id, `${positionLabel(r.position)} ${pct(r.probability, 0)}`]),
  )
  const checking = new Map([...taken, ...board.check.map((id) => [id, 'checked'] as const)])

  return (
    <div>
      <Head {...heads.draft()} />
      <ArtHeader art={heroArt}>
        <p className="eyebrow">
          {positionLabel(board.role)} · {boardIsSet(board) ? 'pick phase' : 'ban phase'}
        </p>
        <h1 className="display mt-1 text-[clamp(2rem,5vw,3.2rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
          Draft assistant
        </h1>
        {/* Off on a phone: there the board has to reach the first suggestion
            within a screen, and the page said the first suggestion started at
            989 px of an 844 px screen. */}
        <p className="mt-3 hidden max-w-prose text-sm leading-relaxed text-ink-dim sm:block">
          Pick your role, then fill in the draft as it happens. Suggestions are ranked by
          what the records can support, not by what a handful of games claims, and every
          row shows where its number came from.
        </p>
      </ArtHeader>

      <div className="mx-auto max-w-[1280px] px-4 py-6">

      {empty ? (
        <div className="mt-6">
          <EmptyState
            title="No matches ingested yet"
            body="Draft advice is built from a corpus of matches. Run the crawler first: python -m scripts.ingest crawl --target 500, then python -m scripts.ingest aggregate."
          />
        </div>
      ) : (
        // On a phone the order is the board, the answer, then the settings; on
        // a wide screen the board and the settings share the left column.
        <div className="mt-5 grid gap-6 [grid-template-areas:'board'_'results'_'settings'] lg:grid-cols-[320px_1fr] lg:grid-rows-[auto_1fr] lg:[grid-template-areas:'board_results'_'settings_results']">
          {/* The board */}
          <aside className="space-y-4 [grid-area:board]">
            <div>
              <span className="mb-1 block text-xs text-ink-faint">Your role</span>
              <ChipGroup label="Your role" className="gap-1">
                {POSITIONS.map((p) => (
                  <Chip
                    key={p.id}
                    size="sm"
                    active={board.role === p.id}
                    onClick={() => update(setRole(p.id))}
                  >
                    <PositionIcon position={p.id} className="size-4" />
                    {p.label}
                  </Chip>
                ))}
              </ChipGroup>
            </div>

            <div>
              <Slot
                label="Your team"
                placeholder="Add an ally"
                ids={board.allies}
                cap={CAPS.allies}
                championById={championById}
                unavailable={taken}
                onAdd={(id) => update(addTo('allies', id))}
                onRemove={(id) => update(removeFrom('allies', id))}
              />
              {read?.role_clash && (
                <p className="mt-1 text-[11px] leading-snug text-gold-bright">
                  {read.role_clash.champion.name} is played {positionLabel(read.position).toLowerCase()} in{' '}
                  {pct(read.role_clash.share, 0)} of games. Is your role right?
                </p>
              )}
              {/* Only for a side on the board: the last answer can still hold
                  a side the board has just cleared. */}
              {board.allies.length > 0 && <TeamMix damage={read?.team_damage} side="allies" />}
            </div>

            <div>
              <Slot
                label="Enemy team"
                placeholder="Add an enemy"
                ids={board.enemies}
                cap={CAPS.enemies}
                championById={championById}
                unavailable={taken}
                onAdd={(id) => update(addTo('enemies', id))}
                onRemove={(id) => update(removeFrom('enemies', id))}
                lane={board.lane}
                onToggleLane={(id) => update(toggleLane(id))}
                roleNote={(id) => enemyRole.get(id) ?? null}
              />
              {board.enemies.length > 0 && (
                <LaneStatus
                  data={read}
                  unknown={board.laneUnknown}
                  onUnknown={(unknown) => update(setLaneUnknown(unknown))}
                />
              )}
              {board.enemies.length > 0 && <TeamMix damage={read?.team_damage} side="enemies" />}
            </div>

            <Slot
              label="Banned"
              placeholder="Add a champion"
              ids={board.bans}
              cap={CAPS.bans}
              championById={championById}
              unavailable={taken}
              onAdd={(id) => update(addTo('bans', id))}
              onRemove={(id) => update(removeFrom('bans', id))}
            />

            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <CopyButton
                text={() => window.location.href}
                className="text-xs text-ink-faint underline decoration-line underline-offset-2 transition-colors hover:text-ink"
              >
                Copy this draft’s link
              </CopyButton>
              {boardIsSet(board) && (
                <button
                  type="button"
                  onClick={() => {
                    update(clearBoard)
                    toast('Board cleared')
                  }}
                  className="text-xs text-ink-faint underline decoration-line underline-offset-2 transition-colors hover:text-ink"
                >
                  Clear the board
                </button>
              )}
            </div>
          </aside>

          {/* Settings */}
          <div className="space-y-4 self-start [grid-area:settings]">
            <RiotIdField
              platform={platform}
              onPlatformChange={(v) => {
                setChosenRegion(v)
                rememberRegion(v)
              }}
              status={read?.personalisation}
              comfort={board.comfort}
            />

            <SelectField
              label="Weigh what you can play"
              className="justify-between text-sm"
              value={String(board.comfort)}
              onValueChange={(v) => update(setComfort(Number(v)))}
              disabled={!riot}
              options={COMFORT_LEVELS.map((c) => ({ value: String(c.value), label: c.label }))}
            />

            <SelectField
              label="Min games per champion"
              className="justify-between text-sm"
              value={String(board.min)}
              onValueChange={(v) => update(setMinGames(Number(v)))}
              options={minGamesOptions(board.min)}
            />
          </div>

          {/* Results */}
          <div className="min-w-0 [grid-area:results]">
            {draft.isError && (
              <ErrorView error={draft.error} onRetry={() => draft.refetch()} />
            )}

            {draft.isPending && !draft.isError && <SuggestionSkeleton />}

            {read && (
              <Results
                data={read}
                comfort={board.comfort}
                min={board.min}
                stale={draft.isPlaceholderData}
                onMinGames={(min) => update(setMinGames(min))}
                onUncheck={(id) => update(removeCheck(id))}
                checker={
                  <ChampionPicker
                    label="Check a champion"
                    placeholder="How would they do here?"
                    inputId="draft-check"
                    onPick={(id) => update(addCheck(id))}
                    unavailable={checking}
                    full={board.check.length >= MAX_CHECKS}
                    count={board.check.length > 0 ? `${board.check.length}/${MAX_CHECKS}` : undefined}
                  />
                }
              />
            )}
          </div>
        </div>
      )}
    </div>
    </div>
  )
}

/**
 * Who the board thinks is in your lane, and the way to say otherwise.
 *
 * With nobody marked, the enemies' likely roles give each one a chance of
 * being your laner, and their lane records count by that chance. "No lane
 * opponent yet" stops the guess, which makes the pick a blind one: each
 * suggestion then lists the lanes it is known to lose.
 */
function LaneStatus({
  data,
  unknown,
  onUnknown,
}: {
  data: DraftResponse | undefined
  unknown: boolean
  onUnknown: (unknown: boolean) => void
}) {
  const opponent = data?.lane_opponent
  const button =
    'rounded-sm text-[11px] text-ink-faint underline decoration-line underline-offset-2 outline-none hover:text-ink focus-visible:ring-2 focus-visible:ring-accent/60'
  if (unknown) {
    return (
      <p className="mt-1.5 text-[11px] leading-snug text-ink-faint">
        Lane opponent unknown: each pick lists the lanes it is known to lose.{' '}
        <button type="button" className={button} onClick={() => onUnknown(false)}>
          Guess from the enemy picks
        </button>
      </p>
    )
  }
  if (!opponent) return null
  if (opponent.source === 'marked') {
    return (
      <p className="mt-1.5 text-[11px] leading-snug text-ink-faint">
        In your lane: {opponent.champion.name}, as you marked.
      </p>
    )
  }
  return (
    <p className="mt-1.5 text-[11px] leading-snug text-ink-faint">
      Probably in your lane: {opponent.champion.name}, {pct(opponent.probability, 0)} likely from how
      often each enemy plays each role. Mark the right one, or{' '}
      <button type="button" className={button} onClick={() => onUnknown(true)}>
        treat the lane as unknown
      </button>
      .
    </p>
  )
}
