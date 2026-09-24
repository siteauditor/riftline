import { devices, expect, test, type Locator, type Page } from '@playwright/test'

import type { Analytics, MatchSummary } from '../src/lib/api'
import { emptyAnalytics, filledAnalytics, fullGame, game } from '../src/test/fixtures/profile'

/**
 * What must hold on any corpus, including the empty one CI runs with: the
 * prerendered pages hydrate without a hydration error, the controls are
 * real controls, the search navigates, and the search dialog opens from
 * the keyboard. Numbers are never asserted; those are the API's tests.
 *
 * Every test waits for hydration first. A prerendered page is complete HTML
 * before any script runs, so a test that clicked at once would be clicking
 * dead markup: the search form would submit natively and a select would be
 * a button that does nothing. The app marks the document once it has taken
 * over (`data-hydrated`, App.tsx).
 */

function watchForErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  return errors
}

async function open(page: Page, path: string) {
  const errors = watchForErrors(page)
  await page.goto(path)
  await page.locator('html[data-hydrated]').waitFor({ timeout: 15_000 })
  return errors
}

// In the built bundle React reports a mismatch as a minified error code:
// 418 is text, 425 is a tree, 423 a recoverable error during hydration.
const hydrationErrors = (errors: string[]) =>
  errors.filter((e) => /hydrat|Minified React error #4(18|23|25)/i.test(e))

test('the home page is prerendered and a Riot ID search navigates', async ({ page }) => {
  const errors = await open(page, '/')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page).toHaveTitle(/Riftline/)
  const riotId = page.getByRole('combobox', { name: 'Riot ID' })
  await riotId.fill('Caps#EUW')
  await riotId.press('Enter')
  await expect(page).toHaveURL(CAPS_PAGE)
  expect(hydrationErrors(errors)).toEqual([])
})

test('the tier list is prerendered and hydrates cleanly', async ({ page }) => {
  const errors = await open(page, '/tierlist')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Champion tier list/)
  await expect(page).toHaveTitle(/Champion tier list/)
  expect(hydrationErrors(errors)).toEqual([])
})

test('a leaderboard filter is a working select', async ({ page }) => {
  // The leaderboard's options come from the API's static lists, so the
  // controls are there on an empty corpus too.
  const errors = await open(page, '/leaderboards')
  const queue = page.getByRole('combobox', { name: 'Queue' })
  await expect(queue).toHaveText(/Solo\/Duo/)
  await queue.click()
  await page.getByRole('option', { name: /Flex/ }).click()
  await expect(queue).toHaveText(/Flex/)
  await expect(page).toHaveURL(/queue=440/)
  expect(hydrationErrors(errors)).toEqual([])
})

test('a champion page has real tabs that move the URL', async ({ page }) => {
  const errors = await open(page, '/champions/aatrox')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Aatrox/)
  const runes = page.getByRole('tab', { name: 'Runes' })
  await runes.click()
  await expect(runes).toHaveAttribute('data-state', 'active')
  await expect(page).toHaveURL(/tab=runes/)
  expect(hydrationErrors(errors)).toEqual([])
})

test('Ctrl+K opens the search dialog anywhere and Escape closes it', async ({ page }) => {
  await open(page, '/method/score')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Riftline score/)
  await page.keyboard.press('Control+k')
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('combobox', { name: 'Riot ID' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
})

// Five recent searches, the rows the list shows on an empty field without any
// data from the API: enough rows that a list cut off at the edge of whatever
// holds the field (the home hero did, 2026-09-23) loses some of them.
const RECENT = [
  { platform: 'sg2', gameName: 'Rhasta', tagLine: '0403' },
  { platform: 'euw1', gameName: 'Effortless', tagLine: 'Kind' },
  { platform: 'sg2', gameName: 'Adamavar2020', tagLine: '12345' },
  { platform: 'kr', gameName: 'Hide on bush', tagLine: 'KR1' },
  { platform: 'euw1', gameName: 'Caps', tagLine: 'EUW' },
].map((r, i) => ({ ...r, iconUrl: null, at: 1_790_000_000_000 - i }))

// Riot spells the account "Cäps", and a profile moves to the player's own
// spelling once Riot has answered for it, so the page is at either address
// depending on whether that answer has come. Asserting the typed spelling
// alone failed whenever the answer was quick (the search dialog's test,
// 2026-09-24).
const CAPS_PAGE = /\/summoner\/euw1\/C(a|%C3%A4)ps\/EUW$/

async function remember(page: Page, region?: string) {
  await page.addInitScript(
    ({ recent, region }) => {
      localStorage.setItem('riftline.recent', JSON.stringify(recent))
      if (region) localStorage.setItem('riftline.region', region)
    },
    { recent: RECENT, region },
  )
}

/**
 * Whether nothing is drawn over the middle of the element: the point hits
 * the element itself. A row clipped by an ancestor, painted under the next
 * section, or left without pointer events fails this, which is exactly what
 * a user sees as a list they cannot read or click.
 */
function onTop(locator: Locator): Promise<boolean> {
  return locator.evaluate((el) => {
    const r = el.getBoundingClientRect()
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
    return hit !== null && el.contains(hit)
  })
}

/**
 * Whether the element's ground has no transparency. A list over a page is
 * read against its own ground only: at 94% the fields under the lists showed
 * through them.
 */
function opaque(locator: Locator): Promise<boolean> {
  return locator.evaluate((el) => !/\/|rgba/.test(getComputedStyle(el).backgroundColor))
}

test('the search list is drawn whole, over the section below the hero', async ({ page }) => {
  await remember(page)
  await open(page, '/')
  const riotId = page.getByRole('combobox', { name: 'Riot ID' })
  await riotId.click()
  const options = page.getByRole('listbox').getByRole('option')
  await expect(options).toHaveCount(RECENT.length)
  expect(await opaque(page.locator('[data-slot=popover-content]'))).toBe(true)
  for (const option of await options.all()) {
    await expect.poll(() => onTop(option)).toBe(true)
  }
  // The field keeps focus while the list is open, and Escape closes it.
  await expect(riotId).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('listbox')).toBeHidden()
})

test('a remembered region survives hydration and is the one searched', async ({ page }) => {
  // The prerendered HTML says EUW; this browser remembers KR. The region
  // once went blank right after hydration and the search went to
  // /summoner//Faker/KR1.
  await remember(page, 'kr')
  const errors = await open(page, '/')
  await expect(page.getByRole('combobox', { name: 'Region' })).toHaveText('KR')
  const riotId = page.getByRole('combobox', { name: 'Riot ID' })
  await riotId.fill('Faker#KR1')
  await riotId.press('Enter')
  await expect(page).toHaveURL(/\/summoner\/kr\/Faker\/KR1$/)
  expect(hydrationErrors(errors)).toEqual([])
})

test('the search dialog shows its list above the dialog and picks from it', async ({ page }) => {
  await remember(page)
  await open(page, '/method/score')
  await page.keyboard.press('Control+k')
  const dialog = page.getByRole('dialog')
  const riotId = dialog.getByRole('combobox', { name: 'Riot ID' })
  await expect(riotId).toBeFocused()
  await riotId.press('ArrowDown')
  const last = page.getByRole('listbox').getByRole('option').last()
  await expect.poll(() => onTop(last)).toBe(true)
  await last.click()
  await expect(page).toHaveURL(CAPS_PAGE)
  await expect(dialog).toBeHidden()
})

test('the draft picker lists champions over the fields below it and adds one', async ({ page }) => {
  await open(page, '/draft')
  // The board is built from the corpus, and on an empty one (CI's) the page
  // says so instead of drawing it: the picker is checked wherever there is
  // a board, locally and against production.
  const ally = page.getByPlaceholder('Add an ally')
  const empty = page.getByText('No matches ingested yet')
  await expect(ally.or(empty)).toBeVisible()
  test.skip(await empty.isVisible(), 'The draft board needs a corpus of matches.')
  await ally.click()
  const list = page.locator('[data-slot=popover-content]')
  await expect(list).toBeVisible()
  expect(await opaque(list)).toBe(true)
  const first = list.getByRole('option').first()
  await expect.poll(() => onTop(first)).toBe(true)
  const name = (await first.textContent())!.trim()
  await first.click()
  await expect(list).toBeHidden()
  await expect(page.getByRole('button', { name: `Remove ${name}` })).toBeVisible()
})

test('the draft picker works from the keyboard and keeps a champion in one place', async ({ page }) => {
  await open(page, '/draft')
  const ally = page.getByRole('combobox', { name: 'Your team' })
  const empty = page.getByText('No matches ingested yet')
  await expect(ally.or(empty)).toBeVisible()
  test.skip(await empty.isVisible(), 'The draft board needs a corpus of matches.')
  // "kaisa" found nothing before names were folded (2026-09-24).
  await ally.fill('kaisa')
  await ally.press('ArrowDown')
  await ally.press('Enter')
  await expect(page.getByRole('button', { name: "Remove Kai'Sa" })).toBeVisible()
  const enemy = page.getByRole('combobox', { name: 'Enemy team' })
  await enemy.fill('kai')
  const enemyList = page.getByRole('listbox', { name: 'Enemy team' })
  await expect(enemyList.getByRole('option', { name: /Kai'Sa/ })).toHaveAttribute('aria-disabled', 'true')
})

test('a link with a query string hydrates the page it was prerendered as', async ({ page }) => {
  // nginx serves the file prerendered for the bare path whatever the query
  // string, and every one of these threw React error #418 on production
  // (2026-09-24). They render on an empty corpus too, so CI checks them.
  for (const path of ['/leaderboards?queue=440', '/tierlist?position=TOP', '/champions/aatrox?tab=runes']) {
    const errors = await open(page, path)
    expect(hydrationErrors(errors), path).toEqual([])
  }
})

test('the draft hydrates with a remembered region and Riot ID and a board in the link', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('riftline.region', 'kr')
    localStorage.setItem('riftline.riotId', 'Faker#KR1')
  })
  // comfort=0: mastery off, so the page never asks Riot about the Riot ID.
  const errors = await open(page, '/draft?role=TOP&comfort=0')
  expect(hydrationErrors(errors)).toEqual([])
  const top = page.getByRole('button', { name: 'Top', exact: true })
  const empty = page.getByText('No matches ingested yet')
  await expect(top.or(empty)).toBeVisible()
  test.skip(await empty.isVisible(), 'The draft board needs a corpus of matches.')
  await expect(top).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByPlaceholder('Caps#EUW').last()).toHaveValue('Faker#KR1')
})

test('removing the lane opponent takes them off the board, not only the mark', async ({ page }) => {
  const errors = await open(page, '/draft?enemies=157,64&lane=157')
  const yasuo = page.getByRole('button', { name: /^(Remove )?Yasuo$/ })
  const empty = page.getByText('No matches ingested yet')
  await expect(yasuo.or(empty)).toBeVisible()
  test.skip(await empty.isVisible(), 'The draft board needs a corpus of matches.')
  await yasuo.click()
  await expect(page).toHaveURL(/enemies=64(&|$)/)
  await expect(page).not.toHaveURL(/157/)
  expect(hydrationErrors(errors)).toEqual([])
})

test('a side leaning one damage type says so, and the picks that even it out say how much', async ({ page }) => {
  // Darius, Lee Sin and Jinx: a side that deals mostly physical damage.
  const errors = await open(page, '/draft?role=MIDDLE&allies=122,64,222')
  const leaning = page.getByText(/Mostly physical: picks that deal mostly magic are marked/)
  const empty = page.getByText('No matches ingested yet')
  await expect(leaning.or(empty)).toBeVisible()
  test.skip(await empty.isVisible(), 'The draft board needs a corpus of matches.')
  await expect(page.getByText(/brings magic damage/).first()).toBeVisible()
  expect(hydrationErrors(errors)).toEqual([])
})

test('a champion checked by hand is pinned above the list with its place', async ({ page }) => {
  await open(page, '/draft')
  const check = page.getByRole('combobox', { name: 'Check a champion' })
  const empty = page.getByText('No matches ingested yet')
  await expect(check.or(empty)).toBeVisible()
  test.skip(await empty.isVisible(), 'The draft board needs a corpus of matches.')
  await check.fill('ahri')
  await check.press('Enter')
  await expect(page).toHaveURL(/check=103/)
  const checked = page.getByRole('region', { name: 'Champions you checked' })
  await expect(checked.getByText('Ahri', { exact: true })).toBeVisible()
  await checked.getByRole('button', { name: 'Stop checking Ahri' }).click()
  await expect(page).not.toHaveURL(/check=/)
})

test('the tier list says how many picks its games tell apart from even', async ({ page }) => {
  const errors = await open(page, '/tierlist')
  const line = page.getByText(/the games (show|do not yet show)/)
  const empty = page.getByText('No ranked games yet')
  await expect(line.or(empty)).toBeVisible()
  test.skip(await empty.isVisible(), 'The tier list needs a corpus of matches.')
  await expect(page.getByRole('columnheader', { name: 'Tier' })).toBeVisible()
  expect(hydrationErrors(errors)).toEqual([])
})

test('a champion link to a role without games shows the main role and says so', async ({ page }) => {
  const errors = await open(page, '/champions/ahri?position=JUNGLE')
  // An older link's role moves into the path, where a role now lives.
  await expect(page).toHaveURL(/\/champions\/ahri\/jungle$/)
  const notice = page.getByRole('status').filter({ hasText: 'has no jungle games' })
  const story = page.getByRole('tab', { name: 'Story', selected: true })
  await expect(notice.or(story)).toBeVisible()
  test.skip(await story.isVisible(), 'The champion numbers need a corpus of matches.')
  const roles = page.getByRole('group', { name: 'Role' })
  await expect(roles.getByRole('link', { name: /^Mid/ })).toHaveAttribute('aria-current', 'page')
  expect(hydrationErrors(errors)).toEqual([])
})

test('an older link with the role in its query string moves the role into the path', async ({ page }) => {
  const errors = await open(page, '/champions/ahri?position=UTILITY&tab=story')
  await expect(page).toHaveURL(/\/champions\/ahri\/support\?tab=story$/)
  await expect(page.getByRole('tab', { name: 'Story', selected: true })).toBeVisible()
  expect(hydrationErrors(errors)).toEqual([])
})

test('a role has its own page, and the main role points at the bare path', async ({ page, request }) => {
  const manifest = await (await request.get('/api/meta/pages')).json()
  const roles: { path: string; indexable: boolean }[] = manifest.pages.filter(
    (p: { kind: string }) => p.kind === 'champion_role',
  )
  const own = roles.find((p) => p.indexable)
  test.skip(!own, 'Role pages need a corpus of matches.')
  const path = own!.path
  const html = await (await request.get(path)).text()
  expect(html).toContain(`rel="canonical" href="https://www.rhasta.space${path}"`)
  expect(html).not.toContain('name="robots"')
  const main = roles.find((p) => !p.indexable)
  if (main) {
    const bare = main.path.split('/').slice(0, 3).join('/')
    const mainHtml = await (await request.get(main.path)).text()
    expect(mainHtml).toContain(`rel="canonical" href="https://www.rhasta.space${bare}"`)
    expect(mainHtml).toContain('content="noindex, follow"')
  }
  const errors = await open(page, path)
  const current = page.getByRole('group', { name: 'Role' }).locator('a[aria-current="page"]')
  await expect(current).toHaveCount(1)
  await expect(page).toHaveURL(new RegExp(`${path}$`))
  expect(hydrationErrors(errors)).toEqual([])
})

test('the champion index lists every champion and finds one by name', async ({ page }) => {
  const errors = await open(page, '/champions')
  await expect(page.getByRole('heading', { level: 1, name: 'Champions' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Ahri', exact: true })).toBeVisible()
  await page.getByPlaceholder("Type a champion's name").fill('ahri')
  await expect(page.getByText(/^1 of \d+ shown$/)).toBeVisible()
  expect(hydrationErrors(errors)).toEqual([])
})

test('the runes tab names every rune it draws, stat shards included', async ({ page }) => {
  const corpus = await (await page.request.get('/api/meta/corpus')).json()
  test.skip(!corpus.total_matches, 'The champion numbers need a corpus of matches.')
  const errors = await open(page, '/champions/ahri?tab=runes')
  await expect(page.getByRole('heading', { name: 'Keystones' })).toBeVisible()
  const images = page.locator('#champion-tabpanel img')
  const alts = await images.evaluateAll((els) => els.map((el) => el.getAttribute('alt') ?? ''))
  expect(alts.length).toBeGreaterThan(0)
  expect(alts.filter((alt) => alt.trim() === '')).toEqual([])
  expect(hydrationErrors(errors)).toEqual([])
})

test('the tier list is one list, with its header art already in the served page', async ({ page, request }) => {
  const html = await (await request.get('/tierlist')).text()
  test.skip(html.includes('No ranked games yet'), 'The tier list needs a corpus of matches.')
  // The largest image, in the HTML rather than after hydration and a request.
  expect(html).toContain('splash-art/centered')
  const errors = await open(page, '/tierlist')
  const list = page.getByRole('table', { name: 'Champion tier list' })
  await expect(list).toHaveCount(1)
  const drawn = await list.getByRole('row').count()
  const more = page.getByRole('button', { name: /^Show all \d+ picks$/ })
  if (await more.isVisible()) {
    await more.click()
    expect(await list.getByRole('row').count()).toBeGreaterThan(drawn)
  }
  expect(hydrationErrors(errors)).toEqual([])
})

test.describe('on a phone', () => {
  // A Pixel 7's screen. The tabs sat 1,081 px down it and the header showed
  // 249 px of its 502 px of links (2026-09-24).
  test.use({ viewport: { width: 412, height: 839 } })

  test('a champion page shows its tabs on the first screen', async ({ page }) => {
    const errors = await open(page, '/champions/ahri')
    const box = await page.getByRole('tablist', { name: 'Champion sections' }).boundingBox()
    expect(box).not.toBeNull()
    expect(box!.y + box!.height).toBeLessThanOrEqual(839)
    expect(hydrationErrors(errors)).toEqual([])
  })

  test("the header's pages are one menu, named after the page on screen", async ({ page }) => {
    const errors = await open(page, '/tierlist')
    const header = page.getByRole('banner')
    await header.getByRole('button', { name: /now on Tier list/ }).click()
    await page.getByRole('menuitem', { name: 'Champions' }).click()
    await expect(page).toHaveURL(/\/champions$/)
    await expect(header.getByRole('button', { name: /now on Champions/ })).toBeVisible()
    expect(hydrationErrors(errors)).toEqual([])
  })
})

test('an unknown path is the app saying not found, not a blank shell', async ({ page }) => {
  await open(page, '/no-such-page')
  await expect(page.getByText('404')).toBeVisible()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
})


/**
 * The profile API, mocked for one made-up player who plays on EUW, so the
 * address rules run on any corpus and never reach Riot. `asked` records every
 * summoner request, to prove nothing is asked under an address being left.
 */
async function mockHomePlayer(
  page: Page,
  asked: string[],
  games: MatchSummary[] = [],
  analytics: Analytics = emptyAnalytics,
) {
  const profile = (platform: string, label: string) => ({
    puuid: 'mover', game_name: 'Mover', tag_line: 'EUW', riot_id: 'Mover#EUW',
    platform, platform_label: label,
    shard: platform === 'euw1' ? 'home' : 'absent',
    home_platform: 'euw1', home_platform_label: 'EUW',
    summoner_level: 100, profile_icon_url: null, ranks: [],
    plays_on: platform === 'euw1' ? null : 'euw1',
    plays_on_label: platform === 'euw1' ? null : 'EUW',
    identity_from_plays_on: platform !== 'euw1',
    updated_at: null, ladder: null, source: 'live',
  })
  await page.route('**/api/summoner/**', async (route) => {
    const url = new URL(route.request().url())
    asked.push(url.pathname + url.search)
    const [, , , shard, , , rest] = url.pathname.split('/')
    // The API answers an alias as the shard it names.
    const platform = shard === 'euw' ? 'euw1' : shard
    const json =
      rest === 'matches'
        ? { puuid: 'mover', matches: games, start: 0, count: 20, has_more: false, source: 'riot', stored_total: null }
        : rest === 'analytics'
          ? { ...analytics, puuid: 'mover', game_name: 'Mover', tag_line: 'EUW', platform: 'euw1' }
          : rest === undefined
            ? profile(platform, platform === 'na1' ? 'NA' : platform.toUpperCase())
            : null
    if (json === null) return route.fulfill({ status: 404, json: { detail: 'Not found.' } })
    return route.fulfill({ json })
  })
}

test('a profile opened on a shard the player has nothing on moves to their home, once', async ({ page }) => {
  const asked: string[] = []
  await mockHomePlayer(page, asked)
  const errors = await open(page, '/summoner/na1/Mover/EUW?queue=solo')
  await expect(page).toHaveURL(/\/summoner\/euw1\/Mover\/EUW\?queue=solo$/)
  await expect(page.getByText('Mover#EUW plays on EUW.')).toBeVisible()
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', /\/summoner\/euw1\/Mover\/EUW$/)
  // The games are asked once, at the address the page settled on.
  const histories = asked.filter((a) => a.includes('/matches'))
  expect(histories.every((a) => a.startsWith('/api/summoner/euw1/'))).toBe(true)
  expect(hydrationErrors(errors)).toEqual([])
})

test("an older link's queue id becomes the word the page now uses", async ({ page }) => {
  await mockHomePlayer(page, [])
  await open(page, '/summoner/euw1/Mover/EUW?queue=420')
  await expect(page).toHaveURL(/\/summoner\/euw1\/Mover\/EUW\?queue=solo$/)
  await expect(page.getByRole('button', { name: 'Solo/Duo', pressed: true })).toBeVisible()
})

test('an alias or another spelling of a profile moves to its canonical address', async ({ page }) => {
  await mockHomePlayer(page, [])
  await open(page, '/summoner/euw/mover/euw')
  await expect(page).toHaveURL(/\/summoner\/euw1\/Mover\/EUW$/)
  await expect(page.getByText('plays on EUW.')).toHaveCount(0)
})

test('a player with no ranked games is offered every queue, and the chips move the list with the numbers', async ({ page }) => {
  const asked: string[] = []
  await mockHomePlayer(page, asked)
  await open(page, '/summoner/euw1/Mover/EUW')
  await expect(page.getByText('No ranked games here')).toBeVisible()
  await page.getByRole('button', { name: 'Show all queues' }).click()
  await expect(page).toHaveURL(/\/summoner\/euw1\/Mover\/EUW\?queue=all$/)
  await expect(page.getByRole('button', { name: 'All', exact: true, pressed: true })).toBeVisible()
  // Ranked first, then every queue: the history and the numbers asked alike.
  expect(asked.some((a) => a.includes('/matches') && a.includes('scope=ranked'))).toBe(true)
  expect(asked.some((a) => a.includes('/analytics') && a.includes('scope=all'))).toBe(true)
})

// Games first: the first game is on the first screen at every width, and the
// rail beside the games does not stick. On a 412x839 phone the first game sat
// at 1,128px (2026-09-24).
// A device's browser type cannot be set in a describe group: the rest can.
const { defaultBrowserType: _browser, ...pixel7 } = devices['Pixel 7']

for (const [label, options] of [
  ['a 412x839 phone', pixel7],
  ['a 768x1024 tablet', { viewport: { width: 768, height: 1024 } }],
  ['a 1024x768 laptop', { viewport: { width: 1024, height: 768 } }],
  ['a 1440x900 desktop', { viewport: { width: 1440, height: 900 } }],
] as const) {
  test.describe(`on ${label}`, () => {
    test.use(options)

    test("a profile's first game is on the first screen, and the rail does not stick", async ({ page }) => {
      await mockHomePlayer(page, [], [game(1), game(2), game(3)])
      await open(page, '/summoner/euw1/Mover/EUW')
      const first = page.locator('main article').first()
      await expect(first).toBeVisible()
      const top = await first.evaluate((el) => el.getBoundingClientRect().top + window.scrollY)
      const screen = await page.evaluate(() => window.innerHeight)
      // The row's own opening lines, not only its edge, on the first screen.
      expect(top + 120).toBeLessThanOrEqual(screen)
      if (label.includes('phone')) expect(top).toBeLessThanOrEqual(560)
      await expect(page.locator('aside')).toHaveCSS('position', 'static')
    })
  })
}

test('a bar of the form strip opens its game', async ({ page }) => {
  await mockHomePlayer(page, [], [game(1), game(2), game(3)])
  await open(page, '/summoner/euw1/Mover/EUW')
  const bars = page.locator('section[aria-label="Recent form"] button[aria-controls]')
  await expect(bars).toHaveCount(3)
  // Oldest on the left: the first bar is the third game.
  await bars.first().click()
  const row = page.locator(`#game-${game(3).match_id}`)
  await expect(row.locator('button[aria-expanded]')).toHaveAttribute('aria-expanded', 'true')
  await expect(row.locator('button[aria-expanded]')).toBeFocused()
})

// About 65 hover-only titles on the profile said what a figure meant to a
// mouse and to nobody else (2026-09-24): each is now a hint, which the
// keyboard reaches too, or text on the page.
test("a profile's figures explain themselves to a keyboard, never in a hover-only title", async ({ page }) => {
  await mockHomePlayer(page, [], [fullGame(1), fullGame(2), fullGame(3)], filledAnalytics)
  await open(page, '/summoner/euw1/Mover/EUW')
  // The activity chart's busiest hours, in the viewer's own time.
  await expect(page.getByText(/^Busiest \d\d:00 to \d\d:00, \d+% of these games$/)).toBeVisible()
  await expect(page.locator('main [title]')).toHaveCount(0)
  // A strengths bar is a Tab stop, and says what it measures.
  await page.locator('aside li[tabindex="0"]').first().focus()
  await expect(page.getByRole('tooltip')).toContainText(
    /Damage to champions per minute|Vision score per minute|Kills and assists per death/,
  )
  // An item names itself on focus, as it did on hover. By name: the bar's
  // hint is still fading out while this one opens.
  await page.getByRole('link', { name: "Zhonya's Hourglass" }).first().focus()
  await expect(page.getByRole('tooltip', { name: "Zhonya's Hourglass" })).toHaveCount(1)
})
