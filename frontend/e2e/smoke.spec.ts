import { expect, test, type Page } from '@playwright/test'

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

test('an unknown path is the app saying not found, not a blank shell', async ({ page }) => {
  await open(page, '/no-such-page')
  await expect(page.getByText('404')).toBeVisible()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
})
