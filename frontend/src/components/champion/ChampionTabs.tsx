import { TAB_GROUPS, TAB_LABEL, type ChampionTab } from './tabs'

export default function ChampionTabs({
  active,
  onChange,
}: {
  active: ChampionTab
  onChange: (tab: ChampionTab) => void
}) {
  return (
    <nav
      aria-label="Champion sections"
      className="mt-6 flex flex-wrap items-end gap-x-8 gap-y-2 border-b border-line-soft"
    >
      {TAB_GROUPS.map((group) => (
        // One group never splits across two lines: the phone gets a row per
        // group, each still reading as one set.
        <div key={group.label} className="flex flex-wrap items-end gap-x-1">
          <span className="eyebrow mb-2.5 mr-2 w-full sm:w-auto">{group.label}</span>
          {group.tabs.map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => onChange(tab)}
              aria-pressed={active === tab}
              className={`-mb-px border-b-2 px-3 py-2 font-display text-sm font-600 transition-colors ${
                active === tab
                  ? 'border-gold text-gold-bright'
                  : 'border-transparent text-ink-dim hover:text-ink'
              }`}
            >
              {TAB_LABEL[tab]}
            </button>
          ))}
        </div>
      ))}
    </nav>
  )
}
