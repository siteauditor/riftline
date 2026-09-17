import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { PLATFORMS } from '../lib/api'
import { parseRiotId } from '../lib/format'

interface Props {
  size?: 'default' | 'large'
  initialPlatform?: string
  autoFocus?: boolean
}

/**
 * Riot ID search.
 *
 * Riot IDs are always Name#TAG now, so the field asks for exactly that and says
 * so, rather than accepting a bare name and failing at the API. The tag is the
 * part people forget, so the error names it directly.
 */
export default function SearchBar({
  size = 'default',
  initialPlatform = 'euw1',
  autoFocus = false,
}: Props) {
  const navigate = useNavigate()
  const [platform, setPlatform] = useState(initialPlatform)
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)

  const large = size === 'large'

  function onSubmit(event: FormEvent) {
    event.preventDefault()
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
    navigate(
      `/summoner/${platform}/${encodeURIComponent(parsed.name)}/${encodeURIComponent(parsed.tag)}`,
    )
  }

  return (
    <form onSubmit={onSubmit} className="w-full">
      <div
        className={`flex items-stretch overflow-hidden rounded-sm border border-line bg-panel transition-colors focus-within:border-gold ${
          large ? 'h-14' : 'h-10'
        }`}
      >
        <label className="sr-only" htmlFor="platform">
          Region
        </label>
        {/* The divider and ground sit on the wrapper: the select itself has to
            stay boxless or it draws a second border inside this one. */}
        <span className="flex items-stretch border-r border-line bg-raised">
          <select
            id="platform"
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
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

        <label className="sr-only" htmlFor="riot-id">
          Riot ID
        </label>
        <input
          id="riot-id"
          value={value}
          autoFocus={autoFocus}
          onChange={(e) => {
            setValue(e.target.value)
            if (error) setError(null)
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
          className={`bg-gold px-5 font-display font-700 text-deep transition-colors hover:bg-gold-bright ${
            large ? 'text-sm' : 'text-xs'
          }`}
        >
          Search
        </button>
      </div>

      {error && (
        <p role="alert" className="mt-2 text-sm text-loss">
          {error}
        </p>
      )}
    </form>
  )
}
