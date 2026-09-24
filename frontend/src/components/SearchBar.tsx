import { useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { AnchoredList } from '@/components/ui/anchored-list'

import RankBadge from './RankBadge'
import SelectField from './SelectField'
import { api, PLATFORMS, type SuggestResponse } from '../lib/api'
import { parseRiotId } from '../lib/format'
import { useCombobox } from '../lib/useCombobox'
import { useDebounced } from '../lib/useDebounced'
import {
  foldRiotName,
  rememberRegion,
  useLastRegion,
  useRecentSearches,
  type RecentSearch,
} from '../lib/storage'
import { summonerPath } from '../lib/profileAddress'

interface Props {
  size?: 'default' | 'large'
  /** Overrides the region remembered from the last search. */
  initialPlatform?: string
  autoFocus?: boolean
  /** Called once a search has navigated: the search dialog closes on it. */
  onNavigate?: () => void
}

interface Option {
  key: string
  platform: string
  platformLabel: string
  gameName: string
  tagLine: string
  iconUrl: string | null
  tier?: string | null
  division?: string | null
  leaguePoints?: number | null
}

// The server returns nothing below two folded characters, so the request is not
// worth sending. 150 ms is under the gap between keystrokes of a steady typist,
// so a whole name costs one request rather than one per letter.
const MIN_CHARS = 2
const DEBOUNCE_MS = 150

/** The name half of what was typed, folded the way the server folds it. */
function typedName(text: string): string {
  const hash = text.lastIndexOf('#')
  return foldRiotName(hash === -1 ? text : text.slice(0, hash))
}

function platformLabel(id: string): string {
  return PLATFORMS.find((p) => p.id === id)?.label ?? id.toUpperCase()
}

/**
 * What the list offers for the text in the field: this browser's recent
 * searches while it is empty, else the players we hold who fit what is typed.
 */
function optionsFor(
  text: string,
  long: boolean,
  recent: readonly RecentSearch[],
  answer: SuggestResponse | undefined,
): Option[] {
  if (!text) {
    return recent.map((r) => ({
      key: `recent:${r.platform}:${r.gameName}#${r.tagLine}`,
      platform: r.platform,
      platformLabel: platformLabel(r.platform),
      gameName: r.gameName,
      tagLine: r.tagLine,
      iconUrl: r.iconUrl,
    }))
  }
  if (!long) return []
  // An answer to an earlier text (the debounce has not fired, or the next
  // request is in flight) stays only where it still fits what is typed now,
  // or "hon" would go on offering HONEY BADGER under "honz" until the next
  // answer landed. An answer to exactly this text is taken as sent: the
  // server folds with Python's casefold, which differs from toLowerCase on
  // letters like "ß", and it is the one that decides what matches.
  const current = answer?.query === text
  const name = typedName(text)
  const hash = text.lastIndexOf('#')
  const tag = hash === -1 ? '' : text.slice(hash + 1).trim().toLowerCase()
  const players = (answer?.players ?? []).filter(
    (p) =>
      current ||
      (foldRiotName(p.game_name).startsWith(name) &&
        p.tag_line.toLowerCase().startsWith(tag)),
  )
  return players.map((p) => ({
    key: `known:${p.platform}:${p.riot_id}`,
    platform: p.platform,
    platformLabel: p.platform_label,
    gameName: p.game_name,
    tagLine: p.tag_line,
    iconUrl: p.profile_icon_url,
    tier: p.tier,
    division: p.division,
    leaguePoints: p.league_points,
  }))
}

/**
 * Riot ID search.
 *
 * Riot IDs are always Name#TAG now, so the field asks for exactly that and says
 * so, rather than accepting a bare name and failing at the API. The tag is the
 * part people forget, so the error names it directly.
 *
 * While typing it offers players we already hold, and on an empty field the
 * profiles this browser opened recently. The list opens when somebody types,
 * clicks the field or presses the down arrow, never on focus alone: the home
 * page focuses this field on load, and a list dropping over the page before
 * anyone has touched it would be in the way.
 */
export default function SearchBar({ size = 'default', initialPlatform, autoFocus = false, onNavigate }: Props) {
  const navigate = useNavigate()
  const id = useId()
  // The region is what was picked here, else the page's, else the one this
  // browser remembers (read hydration-safely, see useLastRegion), else EUW.
  const [chosen, setChosen] = useState<string | null>(null)
  const remembered = useLastRegion()
  const platform = chosen || initialPlatform || remembered || 'euw1'
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  // The open state and the highlight (held by key: suggestions arrive after a
  // keystroke, and an index would move onto whichever row landed there).
  const combo = useCombobox()
  const recent = useRecentSearches()
  const rowRef = useRef<HTMLDivElement>(null)

  const text = value.trim()
  const settled = useDebounced(text, DEBOUNCE_MS)
  const long = typedName(text).length >= MIN_CHARS
  const suggestions = useQuery({
    queryKey: ['suggest', settled, platform],
    queryFn: ({ signal }) => api.suggest(settled, platform, signal),
    enabled: combo.open && typedName(settled).length >= MIN_CHARS,
    staleTime: 5 * 60_000,
    // The previous list stays up while the next one loads, so the dropdown
    // does not collapse and reopen on every letter.
    placeholderData: keepPreviousData,
    retry: false,
  })

  const options = optionsFor(text, long, recent, suggestions.data)

  // Said only once the answer is in for exactly what is in the field, so it
  // never flashes while a request is still on its way.
  const nothingKnown =
    long && suggestions.data?.query === text && options.length === 0
  const list = combo.bind(options, pick)
  const showList = combo.open && (options.length > 0 || nothingKnown)

  const large = size === 'large'

  function go(target: string, name: string, tag: string) {
    rememberRegion(target)
    navigate(summonerPath(target, name, tag))
    onNavigate?.()
  }

  function pick(option: Option) {
    setChosen(option.platform)
    // Filled in, as a picked suggestion should be: if the account has since
    // been renamed, the ID is still there to correct.
    setValue(`${option.gameName}#${option.tagLine}`)
    combo.close()
    setError(null)
    go(option.platform, option.gameName, option.tagLine)
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (showList && list.active) {
      pick(list.active)
      return
    }
    const parsed = parseRiotId(value)
    if (!parsed) {
      setError(
        value.trim()
          ? 'Add the tag after a #, for example Caps#EUW.'
          : 'Enter a Riot ID, like Caps#EUW.',
      )
      return
    }
    setError(null)
    combo.close()
    go(platform, parsed.name, parsed.tag)
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    // The arrows and Escape belong to the list; Enter submits the form, which
    // takes the highlighted suggestion when there is one.
    list.onKeyDown(event)
  }

  return (
    <form onSubmit={onSubmit} className="relative w-full">
      {/* The list is a popover anchored to the field row and portalled to the
          body. Drawn in place, it was clipped by whatever held the field: the
          home hero hides its overflow for the splash art, and cut the list
          off at its bottom edge after three rows (seen 2026-09-23). */}
      <AnchoredList
        open={showList}
        onDismiss={combo.close}
        anchorRef={rowRef}
        anchor={
          <div
            ref={rowRef}
            className={`flex items-stretch overflow-hidden frame transition-colors focus-within:border-gold ${
              large ? 'h-14' : 'h-10'
            }`}
          >
            {/* The divider and ground sit on the wrapper: the select itself is
                bare, or it would draw a second border inside this one. */}
            <span className="flex items-stretch border-r border-line bg-raised">
              <SelectField
                ariaLabel="Region"
                bare
                value={platform}
                onValueChange={(v) => {
                  setChosen(v)
                  rememberRegion(v)
                }}
                className="h-full"
                triggerClassName={`pl-3 font-display font-600 tracking-wide text-ink-dim hover:text-ink ${
                  large ? 'text-sm' : 'text-xs'
                }`}
                options={PLATFORMS.map((p) => ({ value: p.id, label: p.label }))}
              />
            </span>

            <label className="sr-only" htmlFor={`${id}-riot-id`}>
              Riot ID
            </label>
            <input
              id={`${id}-riot-id`}
              value={value}
              autoFocus={autoFocus}
              {...list.inputProps(showList)}
              onChange={(e) => {
                setValue(e.target.value)
                combo.setOpen(true)
                combo.setActiveKey(null)
                if (error) setError(null)
              }}
              onKeyDown={onKeyDown}
              onMouseDown={() => combo.setOpen(true)}
              onBlur={combo.close}
              placeholder="Caps#EUW"
              spellCheck={false}
              autoComplete="off"
              className={`min-w-0 flex-1 bg-transparent px-4 text-ink placeholder:text-ink-faint ${
                large ? 'text-lg' : 'text-sm'
              }`}
            />

            <button
              type="submit"
              className={`bg-accent px-5 font-display font-700 uppercase tracking-[0.12em] text-deep transition-colors hover:bg-accent-bright ${
                large ? 'text-sm' : 'text-xs'
              }`}
            >
              Search
            </button>
          </div>
        }
      >
          {!text && (
            <p id={`${combo.listId}-label`} className="px-3 pb-1 pt-2 text-xs text-ink-faint">
              Recent
            </p>
          )}
          <ul
            id={combo.listId}
            role="listbox"
            {...(text
              ? { 'aria-label': 'Players Riftline has seen' }
              : { 'aria-labelledby': `${combo.listId}-label` })}
          >
            {options.map((o, i) => (
              <li
                key={o.key}
                {...list.optionProps(o, i)}
                className={`flex cursor-pointer items-center gap-2.5 px-3 py-2 ${
                  i === list.activeIndex ? 'bg-raised' : ''
                } ${large ? 'text-[15px]' : 'text-sm'}`}
              >
                {o.iconUrl ? (
                  <img src={o.iconUrl} alt="" className="size-7 shrink-0 rounded-sm" loading="lazy" decoding="async" />
                ) : (
                  <span aria-hidden className="size-7 shrink-0 rounded-sm bg-raised" />
                )}
                <span className="min-w-0 flex-1 truncate">
                  <span className="text-ink">{o.gameName}</span>
                  <span className="text-ink-faint">#{o.tagLine}</span>
                </span>
                {o.tier && (
                  <RankBadge tier={o.tier} division={o.division} leaguePoints={o.leaguePoints} />
                )}
                <span className="w-9 shrink-0 text-right font-display text-xs font-600 text-ink-dim">
                  {o.platformLabel}
                </span>
              </li>
            ))}
          </ul>
          {text && (
            <p className="border-t border-line-soft px-3 py-2 text-xs leading-snug text-ink-faint">
              {nothingKnown
                ? 'No player we have seen starts with that. Search the full Name#TAG to look anyone up.'
                : 'Players Riftline has seen. For anyone else, search the full Name#TAG.'}
            </p>
          )}
      </AnchoredList>

      {error && (
        <p role="alert" className="mt-2 text-sm text-loss">
          {error}
        </p>
      )}
    </form>
  )
}
