import { PLATFORMS, type ChampionInfo, type ItemDetail } from './api'
import { canonicalUrl, ORIGIN, SITE_NAME, type PageHead } from './head'
import { positionLabel, tierLabel } from './format'
import { championPath } from './searchParams'

const regionLabel = (platform: string) =>
  PLATFORMS.find((p) => p.id === platform)?.label ?? platform.toUpperCase()

/**
 * What each kind of page says about itself, in one place.
 *
 * Titles read like the query someone would type, with the patch when the page
 * is about one, and every description is a sentence a person could read in a
 * result list rather than a list of keywords. Canonical paths never carry a
 * query string: a filtered tier list is a view of `/tierlist`, not a page.
 */

const titled = (text: string) => `${text} | ${SITE_NAME}`

export function breadcrumbs(items: { name: string; path: string }[]): Record<string, unknown> {
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items.map((item, i) => ({
      '@type': 'ListItem',
      position: i + 1,
      name: item.name,
      item: canonicalUrl(item.path),
    })),
  }
}

const ORGANISATION = {
  '@type': 'Organization',
  name: SITE_NAME,
  url: ORIGIN,
}

export function article(head: { title: string; description: string; path: string }, modified?: string | null): Record<string, unknown> {
  return {
    '@context': 'https://schema.org',
    '@type': 'Article',
    headline: head.title,
    description: head.description,
    mainEntityOfPage: canonicalUrl(head.path),
    // Recommended for Article; without it the Rich Results Test reports a
    // non-critical issue on every explainer.
    image: [`${ORIGIN}/og-default.png`],
    author: ORGANISATION,
    publisher: ORGANISATION,
    ...(modified ? { dateModified: modified } : {}),
  }
}

export const heads = {
  home(): PageHead {
    return {
      title: 'Riftline: League of Legends stats with the working shown',
      description:
        'Look up any player: rank, match history, a performance score per game with published weights, ' +
        'the moments that decided each game, a champion tier list and an item guide.',
      path: '/',
      jsonLd: {
        '@context': 'https://schema.org',
        '@type': 'WebSite',
        name: SITE_NAME,
        url: ORIGIN,
        potentialAction: {
          '@type': 'SearchAction',
          target: { '@type': 'EntryPoint', urlTemplate: `${ORIGIN}/?q={search_term_string}` },
          'query-input': 'required name=search_term_string',
        },
      },
    }
  },

  tierlist(patch?: string | null, queueLabel = 'ranked solo'): PageHead {
    const when = patch ? `patch ${patch}` : 'the current patch'
    return {
      title: titled(`Champion tier list, ${when}`),
      description:
        `Every champion ranked by role on ${when} in ${queueLabel}, ordered by the low end of the win ` +
        'rate each sample supports rather than raw win rate, with pick and ban rates and gold at 14.',
      path: '/tierlist',
    }
  },

  /**
   * `rolePage` is set on a role's own page (`/champions/pantheon/support`),
   * which is its own canonical. The main role's path is not: it shows what
   * the bare path shows, so it points there and the bare path is the one
   * indexed.
   */
  champion(
    info: ChampionInfo,
    patch?: string | null,
    position?: string | null,
    games?: number | null,
    rolePage = false,
  ): PageHead {
    const role = position ? positionLabel(position).toLowerCase() : null
    const when = patch ? `, patch ${patch}` : ''
    const sample = games ? ` from ${games.toLocaleString('en-US')} ranked games` : ''
    const bare = championPath(info)
    const path = rolePage && position ? championPath(info, position) : bare
    return {
      title: titled(`${info.name}${role ? ` ${role}` : ''} build, runes and win rate${when}`),
      description:
        `${info.name}${info.title ? `, ${info.title}` : ''}${rolePage && role ? `, in the ${role} role` : ''}: ` +
        `win rate, pick rate, the builds, runes and skill order that won${sample}, lane matchups and ` +
        `counters, and how ${info.name}'s games are usually decided.`,
      path,
      image: info.splash_url ?? info.art_url ?? null,
      jsonLd: breadcrumbs([
        { name: 'Champions', path: '/champions' },
        { name: info.name, path: bare },
        ...(path !== bare && role ? [{ name: positionLabel(position ?? ''), path }] : []),
      ]),
    }
  },

  champions(patch?: string | null): PageHead {
    return {
      title: titled('Champions: every build, rune page and role'),
      description:
        `Every League of Legends champion, A to Z, with the roles each is played in${patch ? ` on patch ${patch}` : ''} ` +
        'and a page for each role: its builds, runes, skill order, lane matchups and win rate.',
      path: '/champions',
    }
  },

  items(patch?: string | null): PageHead {
    return {
      title: titled('Item guide: what is bought, when, and what it does for the win rate'),
      description:
        `Every Summoner's Rift item${patch ? ` on patch ${patch}` : ''}: how often it is bought, at what minute, ` +
        'how it compares with the other items in its slot, and which champions build it.',
      path: '/items',
    }
  },

  item(item: ItemDetail, patch?: string | null): PageHead {
    const path = `/items/${item.slug ?? item.id}`
    return {
      title: titled(`${item.name}: win rate, build timing and who buys it${patch ? `, patch ${patch}` : ''}`),
      // Riot's plaintext ends in a full stop on some items and not others,
      // so the one we add would double it ("...for a short time.. How often").
      description:
        `${item.name}${item.plaintext ? `: ${item.plaintext.replace(/[.\s]+$/, '')}` : ''}. ` +
        'How often it is bought, when, what it does against the other items in its slot, ' +
        'and the champions that build it most.',
      path,
      image: item.icon_url ?? null,
      jsonLd: breadcrumbs([
        { name: 'Items', path: '/items' },
        { name: item.name, path },
      ]),
    }
  },

  method(): PageHead {
    const head = {
      title: titled('How our numbers are made'),
      description:
        'The Riftline score, the win-chance model, the death review and the lane labels: how each is ' +
        'computed, what it was measured against, and how well it holds up, with the figures in public.',
      path: '/method',
    }
    return {
      ...head,
      jsonLd: {
        '@context': 'https://schema.org',
        '@type': 'Dataset',
        name: 'Riftline score audit',
        description:
          'How well the Riftline per-game performance score tracks wins, per role: winners and losers means, ' +
          'AUC, win rate by score decile, and fitted against published weights.',
        url: canonicalUrl('/method/score'),
        creator: ORGANISATION,
        license: 'https://creativecommons.org/licenses/by/4.0/',
      },
    }
  },

  explainer(
    slug: 'score' | 'win-chance' | 'death-review' | 'lane-labels',
    modified?: string | null,
  ): PageHead {
    const copy = {
      score: {
        title: 'The Riftline score: how a game is scored from 0 to 10',
        description:
          'Seven components, each a percentile against the same role, combined with published weights. ' +
          'What each measures, why the weights are hand-set, when the score is withheld, and how well it tracks wins.',
      },
      'win-chance': {
        title: 'The win-chance model: each side’s chance to win, minute by minute',
        description:
          'A logistic regression on the game state, blue minus red, fitted nightly on our ranked games and ' +
          'graded on games it had not seen. Its accuracy, its calibration, what one Baron is worth, and what it cannot see.',
      },
      'death-review': {
        title: 'The death review: traded deaths, converted takedowns and what each cost',
        description:
          'Every death is traded or not, every takedown converted or not, and each carries the win chance it ' +
          'moved. The rules, the research behind them, what our games show, and how a profile is placed against its role.',
      },
      'lane-labels': {
        title: 'Lane labels: won, even and lost lanes at 14 minutes',
        description:
          'A lane’s share of the pair’s gold, experience and CS at 14 minutes, placed against the same role: ' +
          'the closest third are even, the widest tenth won or lost big. How it is measured and where it fails.',
      },
    }[slug]
    const path = `/method/${slug}`
    const head = { title: titled(copy.title), description: copy.description, path }
    return {
      ...head,
      type: 'article',
      jsonLd: [
        article(head, modified),
        breadcrumbs([
          { name: 'Method', path: '/method' },
          { name: copy.title, path },
        ]),
      ],
    }
  },

  draft(): PageHead {
    return {
      title: titled('Draft assistant: picks that fit the team and beat the enemy'),
      description:
        'Enter the picks and bans as they come and see which champions the stored games favour in the open role: ' +
        'against the enemy team, beside your own, and by how much the sample supports it.',
      path: '/draft',
    }
  },

  leaderboards(region: string, tier: string, division: string | null, queueLabel: string): PageHead {
    return {
      title: titled(`${region} ${tierLabel(tier, division)} ladder, ${queueLabel}`),
      description:
        `The ${region} ${tierLabel(tier, division)} ladder in ${queueLabel}: every player with their LP, ` +
        'wins and losses, named as we find them, with a link to each profile.',
      path: '/leaderboards',
    }
  },

  groups(): PageHead {
    return {
      title: titled('Groups: your team or friends, ranked side by side'),
      description:
        'Put up to 20 players in one table with their rank, record, score, lanes and the games they played ' +
        'together. No account: a view link for anyone and an edit link for whoever manages it.',
      path: '/groups',
    }
  },

  group(name: string, slug: string): PageHead {
    return {
      title: titled(name),
      description: `${name}: a group of players compared side by side on Riftline.`,
      path: `/g/${slug}`,
      noindex: true,
    }
  },

  /** `brief` is the page's own first sentence (rank and record), when the
   *  profile has loaded; the generic description stands in until then. */
  profile(riotId: string, platform: string, rank?: string | null, brief?: string): PageHead {
    const [name, tag] = riotId.split('#')
    const platformLabel = regionLabel(platform)
    const path = `/summoner/${platform}/${encodeURIComponent(name ?? '')}/${encodeURIComponent(tag ?? '')}`
    return {
      title: titled(`${riotId}${rank ? `, ${rank}` : ''}, ${platformLabel} stats`),
      description:
        brief ??
        `${riotId} on ${platformLabel}: rank, match history with a performance score for every game, ` +
          'champions, mastery, and how their lanes and deaths compare with the same role.',
      path,
    }
  },

  profileTab(riotId: string, platform: string, tab: 'champions' | 'mastery' | 'live'): PageHead {
    const [name, tag] = riotId.split('#')
    const platformLabel = regionLabel(platform)
    const base = `/summoner/${platform}/${encodeURIComponent(name ?? '')}/${encodeURIComponent(tag ?? '')}`
    const copy = {
      champions: {
        title: `${riotId}: champions played`,
        description: `Every champion ${riotId} has played in the games Riftline holds, with games, win rate, KDA and score per champion.`,
      },
      mastery: {
        title: `${riotId}: champion mastery`,
        description: `${riotId}'s champion mastery on ${platformLabel}: levels, points and the champions they play most.`,
      },
      live: {
        title: `${riotId}: live game`,
        description: `Whether ${riotId} is in a game right now on ${platformLabel}, and who they are playing with and against.`,
      },
    }[tab]
    return { title: titled(copy.title), description: copy.description, path: `${base}/${tab}`, noindex: tab === 'live' }
  },

  match(matchId: string, summary?: string | null): PageHead {
    return {
      title: titled(summary ? `${summary}` : `Match ${matchId}`),
      description:
        summary
          ? `${summary}: the win chance minute by minute, the moments that decided it, and every player's deaths and takedowns weighed.`
          : 'A stored League of Legends game: the scoreboard, the win chance over time and the moments that decided it.',
      path: `/match/${matchId}`,
    }
  },

  notFound(): PageHead {
    return {
      title: titled('Page not found'),
      description: 'There is no page at this address.',
      path: '/404',
      noindex: true,
    }
  },
}
