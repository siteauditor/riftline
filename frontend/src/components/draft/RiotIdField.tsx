import { useId, useState } from 'react'

import SelectField from '../SelectField'
import { PLATFORMS, type DraftPersonalisation } from '../../lib/api'
import { parseRiotId, plausibleRiotId } from '../../lib/format'
import { rememberRiotId, useLastRiotId } from '../../lib/storage'

function platformLabel(id: string | null | undefined): string {
  return PLATFORMS.find((p) => p.id === id)?.label ?? (id ?? '').toUpperCase()
}

/**
 * What the last answer says about the mastery weighting, in a sentence.
 *
 * Each status names its cause, because "not personalised" alone left a
 * mistyped Riot ID looking exactly like one that worked.
 */
function statusLine(status: DraftPersonalisation | undefined, comfort: number): string {
  if (comfort <= 0) return 'Mastery is off, so the list ignores what you play.'
  if (!status || status.status === 'off') {
    return 'Optional. Weighs the list toward champions you already play.'
  }
  const who = status.riot_id ?? 'This Riot ID'
  const where = platformLabel(status.platform)
  switch (status.status) {
    case 'used':
      return `Weighing by ${who}'s mastery on ${where}: ${status.champions} champions.`
    case 'stale':
      return `Riot did not answer in time, so this uses the mastery stored for ${who}.`
    case 'not_found':
      return `No account ${who} on ${where}. Check the name and the tag.`
    case 'busy':
      return 'Riot is busy right now, so mastery is left out of this list.'
    case 'no_mastery':
      return `${who} has no champion mastery on ${where}.`
  }
}

/**
 * The Riot ID the draft weighs mastery by.
 *
 * Saved, and sent, only once it is committed: on leaving the field or pressing
 * Enter. Sent on every pause in typing, "Nobody#ZZ9" typed at a normal pace was
 * three account lookups for accounts that do not exist (measured 2026-09-24),
 * each spending the Riot key. The saved value lives in this browser, never in
 * the link, and is read hydration-safely.
 */
export default function RiotIdField({
  platform,
  onPlatformChange,
  status,
  comfort,
}: {
  platform: string
  onPlatformChange: (platform: string) => void
  status: DraftPersonalisation | undefined
  comfort: number
}) {
  const id = useId()
  const saved = useLastRiotId()
  // What is being typed, until it is committed; the saved value otherwise.
  const [typed, setTyped] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const value = typed ?? saved ?? ''

  function commit() {
    if (typed === null) return
    const text = typed.trim()
    const parsed = parseRiotId(text)
    if (text && (!parsed || !plausibleRiotId(parsed))) {
      setProblem('Add the tag after a #, for example Caps#EUW.')
      return
    }
    rememberRiotId(text)
    setTyped(null)
    setProblem(null)
  }

  return (
    <div>
      <label htmlFor={`${id}-riot-id`} className="mb-1 block text-xs text-ink-faint">
        Your Riot ID (optional, weighs your mastery)
      </label>
      <div className="flex gap-1">
        <SelectField
          ariaLabel="Region"
          value={platform}
          onValueChange={onPlatformChange}
          triggerClassName="h-10 shrink-0"
          options={PLATFORMS.map((p) => ({ value: p.id, label: p.label }))}
        />
        <input
          id={`${id}-riot-id`}
          value={value}
          onChange={(e) => {
            setTyped(e.target.value)
            setProblem(null)
          }}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit()
          }}
          placeholder="Caps#EUW"
          spellCheck={false}
          autoComplete="off"
          aria-describedby={`${id}-status`}
          className="control h-10 min-w-0 flex-1 px-3 text-sm placeholder:text-ink-faint"
        />
      </div>
      <p
        id={`${id}-status`}
        role="status"
        className={`mt-1 text-[11px] leading-snug ${problem ? 'text-loss' : 'text-ink-faint'}`}
      >
        {problem ?? statusLine(status, comfort)} Remembered on this device, never in the link.
      </p>
    </div>
  )
}
