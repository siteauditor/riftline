import { act, fireEvent, render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import ChampionPicker from './ChampionPicker'

const champion = (id: number, name: string, key: string) => ({
  id,
  name,
  key,
  slug: key.toLowerCase(),
  icon_url: null,
  title: null,
  tags: [],
  splash_url: null,
  art_url: null,
  tile_url: null,
})

const CHAMPIONS = {
  version: 'test',
  champions: [
    champion(103, 'Ahri', 'Ahri'),
    champion(166, 'Akshan', 'Akshan'),
    champion(145, "Kai'Sa", 'Kaisa'),
    champion(254, 'Vi', 'Vi'),
    champion(234, 'Viego', 'Viego'),
  ],
}

function renderPicker(onPick: (id: number) => void, unavailable = new Map<number, string>()) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
  client.setQueryData(['champions'], CHAMPIONS)
  const view = render(
    <QueryClientProvider client={client}>
      <ChampionPicker label="Enemy team" placeholder="Add an enemy" inputId="picker" onPick={onPick} unavailable={unavailable} />
    </QueryClientProvider>,
  )
  const input = view.getByRole('combobox') as HTMLInputElement
  return { input }
}

const options = () => [...document.querySelectorAll('[role=option]')] as HTMLElement[]
const type = (input: HTMLInputElement, text: string) => act(() => fireEvent.change(input, { target: { value: text } }))
const press = (input: HTMLInputElement, key: string) => act(() => fireEvent.keyDown(input, { key }))

describe('ChampionPicker', () => {
  beforeAll(() => {
    // Radix positions the list with a ResizeObserver, which jsdom lacks.
    globalThis.ResizeObserver ??= class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('takes the highlighted match with the arrows and Enter', async () => {
    const onPick = vi.fn()
    const { input } = renderPicker(onPick)
    await type(input, 'kaisa')
    await press(input, 'ArrowDown')
    expect(input.getAttribute('aria-activedescendant')).toBe(options()[0].id)
    await press(input, 'Enter')
    expect(onPick).toHaveBeenCalledWith(145)
    expect(input.value).toBe('')
  })

  it('takes the best match for what is typed when nothing is highlighted, and nothing for an empty field', async () => {
    const onPick = vi.fn()
    const { input } = renderPicker(onPick)
    await press(input, 'Enter')
    expect(onPick).not.toHaveBeenCalled()
    await type(input, 'vi')
    await press(input, 'Enter')
    expect(onPick).toHaveBeenCalledWith(254)
  })

  it('shows a champion already on the board, greyed, and never takes it', async () => {
    const onPick = vi.fn()
    const { input } = renderPicker(onPick, new Map([[103, 'on your team']]))
    await type(input, 'a')
    const ahri = options().find((o) => o.textContent?.includes('Ahri'))!
    expect(ahri.getAttribute('aria-disabled')).toBe('true')
    expect(ahri.textContent).toContain('on your team')
    // The arrows step over it to the next champion.
    await press(input, 'ArrowDown')
    expect(input.getAttribute('aria-activedescendant')).not.toBe(ahri.id)
    await type(input, 'ahri')
    await press(input, 'Enter')
    expect(onPick).not.toHaveBeenCalled()
  })

  it('says so when nothing matches', async () => {
    const { input } = renderPicker(vi.fn())
    await type(input, 'zzzz')
    expect(document.body.textContent).toContain('No champion matches')
  })
})
