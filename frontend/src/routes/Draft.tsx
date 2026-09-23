import { useMemo, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'

import ArtHeader from '../components/ArtHeader'
import Head from '../components/Head'
import SelectField from '../components/SelectField'
import PositionIcon from '../components/PositionIcon'
import { Results, SuggestionSkeleton } from '../components/draft/Results'
import RiotIdField from '../components/draft/RiotIdField'
import Slot from '../components/draft/Slot'
import { useDraftBoard } from '../components/draft/useDraftBoard'
import { EmptyState, ErrorView } from '../components/StateViews'
import { api, POSITIONS, type DraftRequest } from '../lib/api'
import {
  CAPS,
  COMFORT_LEVELS,
  addTo,
  boardIsSet,
  clearBoard,
  minGamesOptions,
  removeFrom,
  requestKey,
  setComfort,
  setMinGames,
  setRole,
  toggleLane,
  unavailable,
  type RiotIdChoice,
} from '../lib/draftBoard'
import { parseRiotId, plausibleRiotId, positionLabel } from '../lib/format'
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

  return (
    <div>
      <Head {...heads.draft()} />
      <ArtHeader art={heroArt}>
        <p className="eyebrow">{positionLabel(board.role)} · pick phase</p>
        <h1 className="display mt-1 text-[clamp(2rem,5vw,3.2rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
          Draft assistant
        </h1>
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-dim">
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
        <div className="mt-5 grid gap-6 lg:grid-cols-[320px_1fr]">
          {/* The board */}
          <aside className="space-y-4">
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
            />

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

            <RiotIdField
              platform={platform}
              onPlatformChange={(v) => {
                setChosenRegion(v)
                rememberRegion(v)
              }}
              status={draft.data?.personalisation}
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

            {boardIsSet(board) && (
              <button
                onClick={() => {
                  update(clearBoard)
                  toast('Board cleared')
                }}
                className="text-xs text-ink-faint underline decoration-line underline-offset-2 transition-colors hover:text-ink"
              >
                Clear the board
              </button>
            )}
          </aside>

          {/* Results */}
          <div className="min-w-0">
            {draft.isError && (
              <ErrorView error={draft.error} onRetry={() => draft.refetch()} />
            )}

            {draft.isPending && !draft.isError && <SuggestionSkeleton />}

            {draft.data && (
              <Results
                data={draft.data}
                comfort={board.comfort}
                min={board.min}
                stale={draft.isPlaceholderData}
                onMinGames={(min) => update(setMinGames(min))}
              />
            )}
          </div>
        </div>
      )}
    </div>
    </div>
  )
}

