import { useId, useMemo, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { keepPreviousData, useQuery } from '@tanstack/react-query'

import RankBadge from './RankBadge'
import { api, PLATFORMS } from '../lib/api'
import { parseRiotId } from '../lib/format'
import { useDebounced } from '../lib/useDebounced'
import {
  foldRiotName,
  lastRegion,
  rememberRegion,
  useRecentSearches,
} from '../lib/storage'

interface Props {
  size?: 'default' | 'large'
  /** Overrides the region remembered from the last search. */
  initialPlatform?: string
  autoFocus?: boolean
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
export default function SearchBar({ size = 'default', initialPlatform, autoFocus = false }: Props) {
  const navigate = useNavigate()
  const id = useId()
  const listId = `${id}-list`
  const [platform, setPlatform] = useState(() => initialPlatform ?? lastRegion() ?? 'euw1')
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  // A key rather than an index: suggestions arrive after a keystroke, and an
  // index would silently move the highlight onto whichever row landed there.
  const [activeKey, setActiveKey] = useState<string | null>(null)
  const recent = useRecentSearches()

  const text = value.trim()
  const settled = useDebounced(text, DEBOUNCE_MS)
  const long = typedName(text).length >= MIN_CHARS
  const suggestions = useQuery({
    queryKey: ['suggest', settled, platform],
    queryFn: ({ signal }) => api.suggest(settled, platform, signal),
    enabled: open && typedName(settled).length >= MIN_CHARS,
    staleTime: 5 * 60_000,
    // The previous list stays up while the next one loads, so the dropdown
    // does not collapse and reopen on every letter.
    placeholderData: keepPreviousData,
    retry: false,
  })

  const options: Option[] = useMemo(() => {
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
    const current = suggestions.data?.query === text
    const name = typedName(text)
    const hash = text.lastIndexOf('#')
    const tag = hash === -1 ? '' : text.slice(hash + 1).trim().toLowerCase()
    const players = (suggestions.data?.players ?? []).filter(
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
  }, [text, long, recent, suggestions.data])

  // Said only once the answer is in for exactly what is in the field, so it
  // never flashes while a request is still on its way.
  const nothingKnown =
    long && suggestions.data?.query === text && options.length === 0
  const showList = open && (options.length > 0 || nothingKnown)
  const activeIndex = options.findIndex((o) => o.key === activeKey)

  const large = size === 'large'

  function go(target: string, name: string, tag: string) {
    rememberRegion(target)
    navigate(`/summoner/${target}/${encodeURIComponent(name)}/${encodeURIComponent(tag)}`)
  }

  function pick(option: Option) {
    setPlatform(option.platform)
    // Filled in, as a picked suggestion should be: if the account has since
    // been renamed, the ID is still there to correct.
    setValue(`${option.gameName}#${option.tagLine}`)
    setOpen(false)
    setActiveKey(null)
    setError(null)
    go(option.platform, option.gameName, option.tagLine)
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (showList && activeIndex >= 0) {
      pick(options[activeIndex])
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
    setOpen(false)
    go(platform, parsed.name, parsed.tag)
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    // Enter and the arrows belong to the input method while a Korean or
    // Japanese name is still being composed.
    if (event.nativeEvent.isComposing) return
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      if (!open) {
        setOpen(true)
        return
      }
      if (!options.length) return
      const next =
        event.key === 'ArrowDown'
          ? (activeIndex + 1) % options.length
          : activeIndex <= 0
            ? options.length - 1
            : activeIndex - 1
      setActiveKey(options[next].key)
    } else if (event.key === 'Escape' && open) {
      event.preventDefault()
      setOpen(false)
      setActiveKey(null)
    }
  }

  return (
    <form onSubmit={onSubmit} className="relative w-full">
      <div
        className={`flex items-stretch overflow-hidden frame transition-colors focus-within:border-gold ${
          large ? 'h-14' : 'h-10'
        }`}
      >
        <label className="sr-only" htmlFor={`${id}-platform`}>
          Region
        </label>
        {/* The divider and ground sit on the wrapper: the select itself has to
            stay boxless or it draws a second border inside this one. */}
        <span className="flex items-stretch border-r border-line bg-raised">
          <select
            id={`${id}-platform`}
            value={platform}
            onChange={(e) => {
              setPlatform(e.target.value)
              rememberRegion(e.target.value)
            }}
            className={`control-bare pl-3 font-display font-600 tracking-wide text-ink-dim hover:text-ink ${
              large ? 'text-sm' : 'text-xs'
            }`}
          >
            {PLATFORMS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </span>

        <label className="sr-only" htmlFor={`${id}-riot-id`}>
          Riot ID
        </label>
        <input
          id={`${id}-riot-id`}
          value={value}
          autoFocus={autoFocus}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={showList}
          aria-controls={listId}
          aria-activedescendant={
            showList && activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined
          }
          onChange={(e) => {
            setValue(e.target.value)
            setOpen(true)
            setActiveKey(null)
            if (error) setError(null)
          }}
          onKeyDown={onKeyDown}
          onMouseDown={() => setOpen(true)}
          onBlur={() => {
            setOpen(false)
            setActiveKey(null)
          }}
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

      {showList && (
        <div className="absolute inset-x-0 top-full z-50 mt-1 overflow-hidden frame shadow-[0_16px_40px_-12px_rgb(0_0_0/0.7)]">
          {!text && (
            <p id={`${listId}-label`} className="px-3 pb-1 pt-2 text-xs text-ink-faint">
              Recent
            </p>
          )}
          <ul
            id={listId}
            role="listbox"
            {...(text
              ? { 'aria-label': 'Players Riftline has seen' }
              : { 'aria-labelledby': `${listId}-label` })}
          >
            {options.map((o, i) => (
              <li
                key={o.key}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === activeIndex}
                // Keeps focus in the field, so the blur that closes the list
                // does not land before the click that picks from it.
                onMouseDown={(e) => e.preventDefault()}
                onMouseMove={() => o.key !== activeKey && setActiveKey(o.key)}
                onClick={() => pick(o)}
                className={`flex cursor-pointer items-center gap-2.5 px-3 py-2 ${
                  i === activeIndex ? 'bg-raised' : ''
                } ${large ? 'text-[15px]' : 'text-sm'}`}
              >
                {o.iconUrl ? (
                  <img src={o.iconUrl} alt="" className="size-7 shrink-0 rounded-sm" />
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
        </div>
      )}

      {error && (
        <p role="alert" className="mt-2 text-sm text-loss">
          {error}
        </p>
      )}
    </form>
  )
}
