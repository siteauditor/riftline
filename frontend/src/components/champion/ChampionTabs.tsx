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
          // One group never splits across two lines: the phone gets a row per
          // group, each still reading as one set.
          <div key={group.label} className="flex flex-wrap items-end gap-x-1">
            <span className="eyebrow mb-2.5 mr-2 w-full sm:w-auto">{group.label}</span>
            {group.tabs.map((tab) => (
              <TabsTrigger key={tab} value={tab}>
                {TAB_LABEL[tab]}
              </TabsTrigger>
            ))}
          </div>
        ))}
      </TabsList>
    </Tabs>
  )
}
