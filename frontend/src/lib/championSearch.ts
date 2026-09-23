import type { ChampionStatic } from './api'
import { foldName } from './searchParams'

/**
 * Finding a champion by what somebody types in champion select.
 *
 * The picker matched a plain substring of the name, so "kaisa", "chogath",
 * "drmundo", "ksante", "kogmaw", "velkoz", "mf" and "tf" found nothing, and
 * "vi" with Enter added Anivia, the first name containing those letters
 * (measured 2026-09-24). Names are folded (case, accents and punctuation off,
 * so Kai'Sa is "kaisa"), matched against the name, the slug and Riot's own key
 * as well, and ranked so an exact or leading match always comes first.
 */

// Only the nicknames no prefix reaches. The rest (xin, kha, heimer, naut, trist,
// yi, mundo, lee) already match the start of the name or of one of its words.
const NICKNAMES: Record<string, string> = {
  mf: 'missfortune',
  tf: 'twistedfate',
  j4: 'jarvaniv',
  asol: 'aurelionsol',
  tk: 'tahmkench',
  gp: 'gangplank',
  lb: 'leblanc',
  ww: 'warwick',
}

/**
 * The words of a name, folded. Split on spaces, full stops and ampersands but
 * not apostrophes: Kai'Sa is one word, so "sa" does not match it as a word, and
 * "mundo" does match Dr. Mundo.
 */
function words(name: string): string[] {
  return name.split(/[\s.&]+/).map(foldName).filter(Boolean)
}

/** Lower is better; null is no match. */
function rank(champion: ChampionStatic, query: string): number | null {
  const name = foldName(champion.name)
  const keys = [name, champion.slug ?? '', foldName(champion.key ?? '')].filter(Boolean)
  if (keys.includes(query) || NICKNAMES[query] === champion.slug) return 0
  if (keys.some((k) => k.startsWith(query))) return 1
  if (words(champion.name).some((w) => w.startsWith(query))) return 2
  if (Object.entries(NICKNAMES).some(([nick, slug]) => slug === champion.slug && nick.startsWith(query))) {
    return 3
  }
  if (name.includes(query)) return 4
  return null
}

/**
 * Champions matching `text`, best first, then alphabetical. An empty query is
 * every champion, alphabetical.
 */
export function searchChampions(champions: readonly ChampionStatic[], text: string): ChampionStatic[] {
  const query = foldName(text)
  const byName = (a: ChampionStatic, b: ChampionStatic) => a.name.localeCompare(b.name, 'en')
  if (!query) return [...champions].sort(byName)
  const ranked: { champion: ChampionStatic; rank: number }[] = []
  for (const champion of champions) {
    const r = rank(champion, query)
    if (r !== null) ranked.push({ champion, rank: r })
  }
  ranked.sort((a, b) => a.rank - b.rank || byName(a.champion, b.champion))
  return ranked.map((r) => r.champion)
}
