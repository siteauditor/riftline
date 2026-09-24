import SelectField from '../SelectField'
import { Chip, ChipGroup } from '@/components/ui/chips'
import type { Analytics, QueueScope } from '../../lib/api'
import { SCOPES } from '../../lib/profileScope'

// The champion filter's "any" choice needs a word: Radix refuses an empty item value.
const ALL_CHAMPIONS = 'all'

/**
 * The queues and the champion a profile's games are filtered by, in one row.
 *
 * Chips from md, where all seven fit beside the champion. Below it they
 * wrapped to three lines on a 412px phone and pushed the first game down, so a
 * phone gets the same choices as a select.
 */
export default function QueueFilter({
  scope,
  onScope,
  champion,
  championName,
  onChampion,
  analytics,
}: {
  scope: QueueScope
  onScope: (scope: QueueScope) => void
  champion: number | null
  /** The filtered champion's name, for a link that names one with no stored games. */
  championName: string
  onChampion: (champion: number | null) => void
  analytics: Analytics | undefined
}) {
  const played = analytics?.champions ?? []
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
      <ChipGroup label="Queue" className="hidden md:flex">
        {SCOPES.map((s) => (
          <Chip key={s.id} active={scope === s.id} onClick={() => onScope(s.id)}>
            {s.label}
          </Chip>
        ))}
      </ChipGroup>
      <SelectField
        label="Queue"
        labelClassName="max-sm:sr-only"
        className="md:hidden"
        value={scope}
        onValueChange={(v) => onScope(SCOPES.find((s) => s.id === v)?.id ?? scope)}
        options={SCOPES.map((s) => ({ value: s.id, label: s.label }))}
      />
      <SelectField
        label="Champion"
        labelClassName="max-sm:sr-only"
        className="ml-auto"
        value={champion ? String(champion) : ALL_CHAMPIONS}
        onValueChange={(v) => onChampion(v === ALL_CHAMPIONS ? null : Number(v))}
        triggerClassName="max-w-[11rem]"
        options={[
          { value: ALL_CHAMPIONS, label: 'All champions' },
          // A link can name a champion with no stored games yet.
          ...(champion && !played.some((c) => c.champion.id === champion)
            ? [{ value: String(champion), label: championName }]
            : []),
          ...played.map((c) => ({
            value: String(c.champion.id),
            label: `${c.champion.name} (${c.games})`,
          })),
        ]}
      />
    </div>
  )
}
