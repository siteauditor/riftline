import { describe, expect, it } from 'vitest'

import type { ChampionStatic } from './api'
import { searchChampions } from './championSearch'

const champion = (id: number, name: string, key: string): ChampionStatic =>
  ({
    id,
    name,
    key,
    slug: key === 'MonkeyKing' ? 'wukong' : key.toLowerCase(),
    icon_url: null,
    title: null,
    tags: [],
    splash_url: null,
    art_url: null,
    tile_url: null,
  }) as ChampionStatic

const CHAMPIONS = [
  champion(34, 'Anivia', 'Anivia'),
  champion(145, "Kai'Sa", 'Kaisa'),
  champion(31, "Cho'Gath", 'Chogath'),
  champion(36, 'Dr. Mundo', 'DrMundo'),
  champion(897, "K'Sante", 'KSante'),
  champion(96, "Kog'Maw", 'KogMaw'),
  champion(161, "Vel'Koz", 'Velkoz'),
  champion(21, 'Miss Fortune', 'MissFortune'),
  champion(4, 'Twisted Fate', 'TwistedFate'),
  champion(59, 'Jarvan IV', 'JarvanIV'),
  champion(254, 'Vi', 'Vi'),
  champion(234, 'Viego', 'Viego'),
  champion(112, 'Viktor', 'Viktor'),
  champion(360, 'Samira', 'Samira'),
  champion(20, 'Nunu & Willump', 'Nunu'),
  champion(62, 'Wukong', 'MonkeyKing'),
  champion(11, 'Master Yi', 'MasterYi'),
]

const first = (text: string) => searchChampions(CHAMPIONS, text)[0]?.name

describe('searchChampions', () => {
  it.each([
    ['kaisa', "Kai'Sa"],
    ['chogath', "Cho'Gath"],
    ['drmundo', 'Dr. Mundo'],
    ['mundo', 'Dr. Mundo'],
    ['ksante', "K'Sante"],
    ['kogmaw', "Kog'Maw"],
    ['velkoz', "Vel'Koz"],
    ['mf', 'Miss Fortune'],
    ['tf', 'Twisted Fate'],
    ['j4', 'Jarvan IV'],
    ['fate', 'Twisted Fate'],
    ['willump', 'Nunu & Willump'],
    ['monkeyking', 'Wukong'],
    ['yi', 'Master Yi'],
    ['KAI SA', "Kai'Sa"],
  ])('finds %s as %s', (text, name) => {
    expect(first(text)).toBe(name)
  })

  it('puts Vi first for "vi", not the first name containing the letters', () => {
    expect(searchChampions(CHAMPIONS, 'vi').map((c) => c.name).slice(0, 3)).toEqual(['Vi', 'Viego', 'Viktor'])
  })

  it('does not let a letter pair inside a name outrank one that starts with it', () => {
    const names = searchChampions(CHAMPIONS, 'sa').map((c) => c.name)
    expect(names[0]).toBe('Samira')
    expect(names.indexOf("Kai'Sa")).toBeGreaterThan(names.indexOf('Samira'))
  })

  it('lists everyone alphabetically for an empty query and nobody for nonsense', () => {
    expect(searchChampions(CHAMPIONS, '  ')).toHaveLength(CHAMPIONS.length)
    expect(searchChampions(CHAMPIONS, '')[0].name).toBe('Anivia')
    expect(searchChampions(CHAMPIONS, 'zzzz')).toEqual([])
  })
})
