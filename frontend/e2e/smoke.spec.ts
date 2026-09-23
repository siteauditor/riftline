import { expect, test, type Locator, type Page } from '@playwright/test'

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
  await expect(page).toHaveURL(/\/summoner\/euw1\/Caps\/EUW$/)
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
  await expect(page).toHaveURL(/\/summoner\/euw1\/Caps\/EUW$/)
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
  const first = list.getByRole('button').first()
  await expect.poll(() => onTop(first)).toBe(true)
  const name = (await first.textContent())!.trim()
  await first.click()
  await expect(list).toBeHidden()
  await expect(page.getByRole('button', { name: new RegExp(`^${name}`) })).toBeVisible()
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

test('an unknown path is the app saying not found, not a blank shell', async ({ page }) => {
  await open(page, '/no-such-page')
  await expect(page.getByText('404')).toBeVisible()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
})
