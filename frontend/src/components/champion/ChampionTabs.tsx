import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

import { TAB_GROUPS, TAB_LABEL, type ChampionTab } from './tabs'

/**
 * The champion page's sections. Radix Tabs for the roles and the keyboard:
 * the arrow keys move between tabs and the row is one tab stop. The panels
 * are not Radix's, because the active tab lives in the URL (`?tab=`) and the
 * page renders the one section the URL names.
 */
export default function ChampionTabs({
  active,
  onChange,
}: {
  active: ChampionTab
  onChange: (tab: ChampionTab) => void
}) {
  return (
    <Tabs value={active} onValueChange={(tab) => onChange(tab as ChampionTab)} className="mt-6">
      <TabsList aria-label="Champion sections" className="gap-x-8 gap-y-2">
        {TAB_GROUPS.map((group) => (
          // Its label inline before its tabs. On a phone the label had a row
          // of its own, which left the tab list 173 px tall and past the
          // first screen of an 839 px phone.
          <div key={group.label} className="flex flex-wrap items-end gap-x-1">
            <span className="eyebrow mb-2.5 mr-2">{group.label}</span>
            {group.tabs.map((tab) => (
              // A fixed id, so the panel (the page's own, not Radix's) can
              // be labelled by the tab that opened it.
              <TabsTrigger key={tab} value={tab} id={`champion-tab-${tab}`} aria-controls="champion-tabpanel">
                {TAB_LABEL[tab]}
              </TabsTrigger>
            ))}
          </div>
        ))}
      </TabsList>
    </Tabs>
  )
}
