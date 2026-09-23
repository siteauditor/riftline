// Generated from openapi.json by scripts/api-types.mjs (`pnpm api:types`). Do not edit.

export interface paths {
    "/api/summoner/{platform}/{game_name}/{tag_line}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Profile
         * @description Profile header: level, icon, every ranked queue and the ladder position.
         */
        get: operations["get_profile_api_summoner__platform___game_name___tag_line__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/summoner/{platform}/{game_name}/{tag_line}/rank-history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Rank History
         * @description Every rank reading we took for this player, oldest first.
         *
         *     Riot keeps no history, so this starts on the day we first read the rank and
         *     has a point only where the rank changed. ``tracking_since`` says when that
         *     was, so an empty or short graph reads as young, not as inactive.
         */
        get: operations["get_rank_history_api_summoner__platform___game_name___tag_line__rank_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/summoner/{platform}/{game_name}/{tag_line}/matches": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Matches
         * @description Match history.
         *
         *     Cold pages are slow by design: each new match is one request against a
         *     budget of 100 per two minutes. Already-seen matches are served from storage.
         *     With `champion` or `source=stored`, the page is stored games only and
         *     makes no Riot call at all.
         */
        get: operations["get_matches_api_summoner__platform___game_name___tag_line__matches_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/summoner/{platform}/{game_name}/{tag_line}/mastery": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Mastery
         * @description Full champion mastery table: one call to Riot, every champion the player has touched.
         */
        get: operations["get_mastery_api_summoner__platform___game_name___tag_line__mastery_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/summoner/{platform}/{game_name}/{tag_line}/analytics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Analytics
         * @description Play style: role share, champion class mix, and when this player plays.
         *
         *     Reads **stored matches only**, so it costs nothing beyond resolving the Riot
         *     ID (and with ``source=stored``, not even that) and can never be blocked by a
         *     rate limit. It therefore describes the games we have fetched rather than a
         *     whole season, which the ``basis`` field says outright instead of letting
         *     the number imply more than it means.
         */
        get: operations["get_analytics_api_summoner__platform___game_name___tag_line__analytics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/summoner/{platform}/{game_name}/{tag_line}/live": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Live Game
         * @description The game this player is in right now, if any.
         *
         *     Answers 200 with ``in_game: false`` when they are not playing. That is the
         *     common case and it is not an error: a 404 here would render as "no player
         *     found", which is false -- the player exists, the game does not.
         *
         *     Roughly a third of any lobby has opted out of third-party visibility, so
         *     expect participants in the ``hidden`` state with no name and no rank. See
         *     ``app/services/live.py`` for why that is reported rather than papered over.
         */
        get: operations["get_live_game_api_summoner__platform___game_name___tag_line__live_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/summoner/{platform}/{game_name}/{tag_line}/live/result/{match_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Live Result
         * @description Has the game that just ended reached storage yet?
         *
         *     The only Riot call the live page spends beyond the lookup itself, so it sits
         *     behind four gates, three of them free: the id has to look like a match id,
         *     storage is checked first, a cooldown holds the second tab off, and a cap
         *     stops a match id that is never going to publish from costing anything more.
         *
         *     Under the summoner path deliberately. A bare ``/api/matches/{id}/resolve``
         *     would be a generic "make the server fetch any match from Riot" door open to
         *     anyone; here it needs a resolvable Riot ID, which the live poll just looked
         *     up and which is cached for a day, and every fetch is tied to an account.
         */
        get: operations["get_live_result_api_summoner__platform___game_name___tag_line__live_result__match_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/static/version": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Version */
        get: operations["get_version_api_static_version_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/static/champions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Champions
         * @description Every champion, with the icon URL already resolved.
         */
        get: operations["get_champions_api_static_champions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/static/queues": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Queues
         * @description Queues worth offering as a filter, in the order players expect them.
         */
        get: operations["get_queues_api_static_queues_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/meta/corpus": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Corpus
         * @description What data has actually been aggregated. Useful before trusting a tier list.
         */
        get: operations["get_corpus_api_meta_corpus_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/meta/champions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Champion Meta */
        get: operations["get_champion_meta_api_meta_champions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/meta/pages": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Pages */
        get: operations["get_pages_api_meta_pages_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/method": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Method */
        get: operations["get_method_api_method_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/champions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Champion Index
         * @description Every champion, with the roles it is played in on the default patch.
         */
        get: operations["get_champion_index_api_champions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/champions/{champion}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Champion */
        get: operations["get_champion_api_champions__champion__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/champions/{champion_ref}/profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Champion Profile
         * @description Story, ratings, base stats, abilities and skins. No Riot call, and one
         *     indexed read for the skin counts.
         *
         *     Answers for every champion Data Dragon knows, games or not.
         */
        get: operations["get_champion_profile_api_champions__champion_ref__profile_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/champions/{champion}/players": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Champion Players
         * @description The players who do best on this champion, by average Riftline score.
         *
         *     Counts every Summoner's Rift game we hold rather than the page's patch
         *     slice: who is good on a champion is not a patch question, and the slice
         *     costs a third of the sample (399 qualifying pairs on 16.18 against 621
         *     overall, measured 2026-09-21). Remakes are left out, as they are
         *     everywhere else.
         */
        get: operations["get_champion_players_api_champions__champion__players_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/draft/suggest": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Suggest
         * @description Rank the champions worth picking, with the reasoning attached.
         */
        post: operations["suggest_api_draft_suggest_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/leaderboard/slices": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Slices
         * @description What can be asked for. Apex tiers take no division.
         */
        get: operations["get_slices_api_leaderboard_slices_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/leaderboard/{platform}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Leaderboard
         * @description One page of a ranked ladder, from a cached snapshot.
         *
         *     The snapshot refreshes itself when stale. If that refresh fails and we
         *     already hold a snapshot, the stale one is served rather than failing the
         *     page: a ladder that is fifteen minutes old is worth far more than an error.
         */
        get: operations["get_leaderboard_api_leaderboard__platform__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/matches/{match_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Match
         * @description The full scoreboard for a match we already hold.
         */
        get: operations["get_match_api_matches__match_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/matches/{match_id}/story": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Story
         * @description Each team's chance to win over the game, the moments that decided it,
         *     and every player's deaths and takedowns weighed.
         *
         *     Fetches the game's timeline from Riot if we do not hold it: one call, once.
         */
        get: operations["get_story_api_matches__match_id__story_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/players/suggest": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Suggest Players
         * @description Riot IDs we already hold that start with what was typed.
         */
        get: operations["suggest_players_api_players_suggest_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/highlights/best-games": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Best Games
         * @description The highest Riftline score in each role over the last few days.
         */
        get: operations["get_best_games_api_highlights_best_games_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/skins/top": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Top Skins */
        get: operations["get_top_skins_api_skins_top_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/items": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Items
         * @description Every item the guide lists, in sections.
         */
        get: operations["list_items_api_items_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/items/{item}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Item */
        get: operations["get_item_api_items__item__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/groups": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create */
        post: operations["create_api_groups_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/groups/{slug}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Group
         * @description The table and "played together", from storage only.
         */
        get: operations["get_group_api_groups__slug__get"];
        put?: never;
        post?: never;
        /** Delete */
        delete: operations["delete_api_groups__slug__delete"];
        options?: never;
        head?: never;
        /** Rename */
        patch: operations["rename_api_groups__slug__patch"];
        trace?: never;
    };
    "/api/groups/{slug}/warm": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Warm
         * @description One bounded pass of fetching what the group's players still lack.
         */
        post: operations["warm_api_groups__slug__warm_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/groups/{slug}/key": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * New Edit Key
         * @description A new edit key. The old one, and every edit link carrying it, stops working.
         */
        post: operations["new_edit_key_api_groups__slug__key_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/groups/{slug}/members": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Add */
        post: operations["add_api_groups__slug__members_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/groups/{slug}/members/{puuid}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Remove */
        delete: operations["remove_api_groups__slug__members__puuid__delete"];
        options?: never;
        head?: never;
        /** Label */
        patch: operations["label_api_groups__slug__members__puuid__patch"];
        trace?: never;
    };
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health */
        get: operations["health_api_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AbilityOut */
        AbilityOut: {
            /** Slot */
            slot: string;
            /** Name */
            name: string;
            /** Description */
            description: string;
            /** Icon Url */
            icon_url: string | null;
            /** Cooldown */
            cooldown: string | null;
            /** Cost */
            cost: string | null;
            /** Range */
            range: string | null;
        };
        /**
         * AnalyticsResponse
         * @description Play style over the matches we hold.
         *
         *     ``basis`` is not decoration. This reads stored matches only, so it describes
         *     the games that have been fetched, not a whole season. Saying so is the
         *     difference between a useful summary and a wrong one.
         */
        AnalyticsResponse: {
            /** Puuid */
            puuid: string;
            /**
             * Basis
             * @default stored_matches
             */
            basis: string;
            /**
             * Games Analysed
             * @default 0
             */
            games_analysed: number;
            /** Roles */
            roles: components["schemas"]["RoleShare"][];
            /** Classes */
            classes: components["schemas"]["ClassShare"][];
            /** Activity Utc */
            activity_utc: number[];
            /** Champions */
            champions: components["schemas"]["ChampionPlayed"][];
            totals: components["schemas"]["PlayStyleTotals"];
            /** Score Profile */
            score_profile: components["schemas"]["RoleScoreProfileOut"][];
            /** Review */
            review: components["schemas"]["RoleReviewOut"][];
            /** Lanes */
            lanes: components["schemas"]["LaneRecordOut"][];
        };
        /** AuditDecileOut */
        AuditDecileOut: {
            /** Low */
            low: number;
            /** High */
            high: number;
            /** Win Rate */
            win_rate: number;
            /** Games */
            games: number;
        };
        /** AuditFittedOut */
        AuditFittedOut: {
            /** Per Ten Points */
            per_ten_points: {
                [key: string]: number;
            };
            /** Normalised */
            normalised: {
                [key: string]: number;
            };
        };
        /** AuditOverallOut */
        AuditOverallOut: {
            /** Winners Mean */
            winners_mean: number | null;
            /** Losers Mean */
            losers_mean: number | null;
            /** Auc */
            auc: number | null;
            /** Top On Winning Team */
            top_on_winning_team: number | null;
            /** Bottom On Losing Team */
            bottom_on_losing_team: number | null;
        };
        /** AuditRoleOut */
        AuditRoleOut: {
            /** Position */
            position: string;
            /** Players */
            players: number;
            /** Winners Mean */
            winners_mean: number;
            /** Losers Mean */
            losers_mean: number;
            /** Auc */
            auc: number | null;
            /** Deciles */
            deciles: components["schemas"]["AuditDecileOut"][];
            /** Components */
            components: {
                [key: string]: number | null;
            };
            /** Set Weights */
            set_weights: {
                [key: string]: number;
            };
            fitted: components["schemas"]["AuditFittedOut"];
            /** Correlation */
            correlation: {
                [key: string]: {
                    [key: string]: number;
                };
            };
        };
        /**
         * BadgeOut
         * @description A badge with the rule that earned it and this player's own figure.
         *
         *     The detail is composed per request rather than stored, so the wording can
         *     improve without rescoring the corpus, and a badge can never appear with an
         *     explanation that no longer matches the rule that awarded it.
         */
        BadgeOut: {
            /** Id */
            id: string;
            /** Label */
            label: string;
            /** Detail */
            detail: string;
        };
        /** BanCandidateOut */
        BanCandidateOut: {
            champion: components["schemas"]["ChampionRef"];
            /** Position */
            position: string;
            /** Games */
            games: number;
            /** Wins */
            wins: number;
            /** Win Rate */
            win_rate: number;
            /** Range Low */
            range_low: number;
            /** Range High */
            range_high: number;
            /** Evidence */
            evidence: components["schemas"]["EvidenceOut"][];
            /** Reasons */
            reasons: string[];
            /**
             * Base Win Rate
             * @default 0
             */
            base_win_rate: number;
            /**
             * Score
             * @default 0
             */
            score: number;
        };
        /** BaseStat */
        BaseStat: {
            /** Key */
            key: string;
            /** Label */
            label: string;
            /** Level1 */
            level1: number;
            /** Level18 */
            level18: number | null;
            /**
             * Growth Published
             * @default true
             */
            growth_published: boolean;
        };
        /** BestGameOut */
        BestGameOut: {
            /** Match Id */
            match_id: string;
            /** Platform */
            platform: string;
            /** Puuid */
            puuid: string;
            /** Game Name */
            game_name: string | null;
            /** Tag Line */
            tag_line: string | null;
            champion: components["schemas"]["TierListChampion"];
            /** Position */
            position: string;
            /** Score */
            score: number;
            /** Placement */
            placement: number | null;
            /** Kills */
            kills: number;
            /** Deaths */
            deaths: number;
            /** Assists */
            assists: number;
            /** Win */
            win: boolean;
            /** Badges */
            badges: components["schemas"]["BadgeOut"][];
            /** Game Creation */
            game_creation: number;
            /** Game Duration */
            game_duration: number;
        };
        /** BestGamesResponse */
        BestGamesResponse: {
            /** Queue Id */
            queue_id: number;
            /** Queue Name */
            queue_name: string;
            /** Days */
            days: number;
            /** Since */
            since: number;
            /** Scored Players */
            scored_players: number;
            /** Scored Games */
            scored_games: number;
            /** Games */
            games: components["schemas"]["BestGameOut"][];
        };
        /** BuildSection */
        BuildSection: {
            /**
             * Basis
             * @default final_inventory
             */
            basis: string;
            /** Complete */
            complete: components["schemas"]["FacetEntry"][];
            /** Items */
            items: components["schemas"]["FacetEntry"][];
            /** Boots */
            boots: components["schemas"]["FacetEntry"][];
            /** Path */
            path: components["schemas"]["FacetEntry"][];
        };
        /** ChampionDetail */
        ChampionDetail: {
            champion: components["schemas"]["ChampionInfo"];
            /** Patch */
            patch: string;
            /** Queue Id */
            queue_id: number;
            /** Position */
            position: string;
            /** Rank Bracket */
            rank_bracket: string;
            /** Sample Matches */
            sample_matches: number;
            /** Min Games */
            min_games: number;
            /** Fallback */
            fallback: ("role" | "patch") | null;
            /** Requested Position */
            requested_position: string | null;
            /** Requested Patch */
            requested_patch: string | null;
            lobby_ranks: components["schemas"]["LobbyRanksOut"] | null;
            /** Positions */
            positions: components["schemas"]["PositionShare"][];
            overview: components["schemas"]["ChampionOverview"];
            builds: components["schemas"]["BuildSection"];
            runes: components["schemas"]["RuneSection"];
            skills: components["schemas"]["SkillSection"];
            laning: components["schemas"]["LaningSection"];
            /** Spells */
            spells: components["schemas"]["FacetEntry"][];
            counters: components["schemas"]["CounterSection"];
            /** Synergies */
            synergies: components["schemas"]["PairEntry"][];
            pair_model: components["schemas"]["PairModelOut"];
        };
        /**
         * ChampionIndex
         * @description Every champion Data Dragon knows, A to Z, with where each is played.
         *
         *     For the index page: a champion under the tier list's floor, or new and
         *     without a game, was reachable only by searching for it.
         */
        ChampionIndex: {
            /** Patch */
            patch: string | null;
            /**
             * Queue Id
             * @default 420
             */
            queue_id: number;
            /**
             * Role Min Games
             * @default 20
             */
            role_min_games: number;
            /** Champions */
            champions: components["schemas"]["ChampionIndexEntry"][];
        };
        /** ChampionIndexEntry */
        ChampionIndexEntry: {
            champion: components["schemas"]["ChampionRef"];
            /** Positions */
            positions: components["schemas"]["PositionShare"][];
            /**
             * Games
             * @default 0
             */
            games: number;
        };
        /** ChampionInfo */
        ChampionInfo: {
            /** Id */
            id: number;
            /** Name */
            name: string;
            /** Icon Url */
            icon_url: string | null;
            /** Key */
            key: string | null;
            /** Title */
            title: string | null;
            /** Tags */
            tags: string[];
            /** Splash Url */
            splash_url: string | null;
            /** Art Url */
            art_url: string | null;
            /** Tile Url */
            tile_url: string | null;
            /** Slug */
            readonly slug: string | null;
        };
        /** ChampionMetaRow */
        ChampionMetaRow: {
            champion: components["schemas"]["TierListChampion"];
            /** Position */
            position: string;
            /** Games */
            games: number;
            /** Wins */
            wins: number;
            /** Win Rate */
            win_rate: number;
            /** Confidence Win Rate */
            confidence_win_rate: number;
            /**
             * Confidence High
             * @default 1
             */
            confidence_high: number;
            /** Pick Rate */
            pick_rate: number;
            /** Ban Rate */
            ban_rate: number;
            /** Tier */
            tier: string | null;
            /** Avg Kda */
            avg_kda: number;
            /** Avg Cs Per Min */
            avg_cs_per_min: number;
            /** Avg Damage */
            avg_damage: number;
            /** Avg Vision */
            avg_vision: number;
            /** Avg Gold Diff 14 */
            avg_gold_diff_14: number | null;
            /**
             * Timeline Games
             * @default 0
             */
            timeline_games: number;
            /** Previous Win Rate */
            previous_win_rate: number | null;
            /**
             * Previous Games
             * @default 0
             */
            previous_games: number;
            /**
             * Win Rate Moved
             * @default false
             */
            win_rate_moved: boolean;
        };
        /** ChampionOverview */
        ChampionOverview: {
            /** Games */
            games: number;
            /** Wins */
            wins: number;
            /** Win Rate */
            win_rate: number;
            /** Confidence Win Rate */
            confidence_win_rate: number;
            /**
             * Confidence High
             * @default 1
             */
            confidence_high: number;
            /** Pick Rate */
            pick_rate: number;
            /** Ban Rate */
            ban_rate: number;
            /** Tier */
            tier: string | null;
            /** Avg Kills */
            avg_kills: number;
            /** Avg Deaths */
            avg_deaths: number;
            /** Avg Assists */
            avg_assists: number;
            /** Avg Kda */
            avg_kda: number;
            /** Avg Cs Per Min */
            avg_cs_per_min: number;
            /** Avg Gold */
            avg_gold: number;
            /** Avg Damage */
            avg_damage: number;
            /** Avg Vision */
            avg_vision: number;
            previous: components["schemas"]["PatchChange"] | null;
        };
        /** ChampionPlayed */
        ChampionPlayed: {
            champion: components["schemas"]["ChampionRef"];
            /** Games */
            games: number;
            /** Wins */
            wins: number;
            /** Win Rate */
            win_rate: number;
            /** Kda */
            kda: number;
            /** Cs Per Min */
            cs_per_min: number;
            /**
             * Avg Kills
             * @default 0
             */
            avg_kills: number;
            /**
             * Avg Deaths
             * @default 0
             */
            avg_deaths: number;
            /**
             * Avg Assists
             * @default 0
             */
            avg_assists: number;
            /**
             * Damage Per Min
             * @default 0
             */
            damage_per_min: number;
            /** Main Position */
            main_position: string | null;
            /** Last Played */
            last_played: number | null;
            /**
             * Scored Games
             * @default 0
             */
            scored_games: number;
            /** Avg Score */
            avg_score: number | null;
            /**
             * Timeline Games
             * @default 0
             */
            timeline_games: number;
            /** Avg Gold Diff 14 */
            avg_gold_diff_14: number | null;
        };
        /** ChampionPlayer */
        ChampionPlayer: {
            /** Puuid */
            puuid: string;
            /** Game Name */
            game_name: string | null;
            /** Tag Line */
            tag_line: string | null;
            /** Platform */
            platform: string;
            /** Games */
            games: number;
            /** Wins */
            wins: number;
            /** Win Rate */
            win_rate: number;
            /** Avg Score */
            avg_score: number;
            /** Scored Games */
            scored_games: number;
            /**
             * Ranked Score
             * @default 0
             */
            ranked_score: number;
            /** Tier */
            tier: string | null;
            /** Division */
            division: string | null;
            /** League Points */
            league_points: number | null;
        };
        /** ChampionPlayers */
        ChampionPlayers: {
            /** Champion Id */
            champion_id: number;
            /**
             * Min Games
             * @default 5
             */
            min_games: number;
            /**
             * Min Scored
             * @default 3
             */
            min_scored: number;
            /**
             * Score Strength
             * @default 9
             */
            score_strength: number;
            /** Champion Score */
            champion_score: number | null;
            /**
             * Qualified
             * @default 0
             */
            qualified: number;
            /** Players */
            players: components["schemas"]["ChampionPlayer"][];
        };
        /**
         * ChampionProfile
         * @description Everything about a champion that is not a statistic.
         *
         *     Its own endpoint, not part of the detail above, because that one is a
         *     404 on any patch where the champion has no games (one champion on 16.17,
         *     and every new release on its first day). A story does not depend on a
         *     sample size.
         */
        ChampionProfile: {
            champion: components["schemas"]["ChampionInfo"];
            /**
             * Blurb
             * @default
             */
            blurb: string;
            /** Lore */
            lore: string | null;
            /** Resource */
            resource: string | null;
            /** Ratings */
            ratings: components["schemas"]["Rating"][];
            /** Stats */
            stats: components["schemas"]["BaseStat"][];
            /** Ally Tips */
            ally_tips: string[];
            /** Enemy Tips */
            enemy_tips: string[];
            passive: components["schemas"]["AbilityOut"] | null;
            /** Abilities */
            abilities: components["schemas"]["AbilityOut"][];
            /**
             * Detail Loaded
             * @default false
             */
            detail_loaded: boolean;
            /** Skins */
            skins: components["schemas"]["SkinOut"][];
            /**
             * Skin Sightings
             * @default 0
             */
            skin_sightings: number;
            /**
             * Skin Sightings Floor
             * @default 20
             */
            skin_sightings_floor: number;
        };
        /** ChampionRef */
        ChampionRef: {
            /** Id */
            id: number;
            /** Name */
            name: string;
            /** Icon Url */
            icon_url: string | null;
            /** Slug */
            readonly slug: string | null;
        };
        /**
         * ClassShare
         * @description Champion class mix, from Data Dragon tags.
         *
         *     A champion can carry several tags (Fighter *and* Tank), so shares are of
         *     total tag mentions and intentionally do not sum to the game count.
         */
        ClassShare: {
            /** Tag */
            tag: string;
            /** Games */
            games: number;
            /** Share */
            share: number;
        };
        /** ComponentAverageOut */
        ComponentAverageOut: {
            /** Id */
            id: string;
            /** Label */
            label: string;
            /** Measures */
            measures: string;
            /** Avg Percentile */
            avg_percentile: number;
        };
        /**
         * CorpusRecordOut
         * @description A record from the stored corpus. Always carries its size and its basis.
         *
         *     `basis` says which step of the lane fallback produced it: "role" for the
         *     champion's own record, "lane" for this patch's head to head, "lane_pooled"
         *     when the previous patch had to be pooled in, and "team" when the only rows
         *     we hold are of the two champions in the same game rather than the same lane.
         *     The page must label anything below "lane", because a team scope record shown
         *     as a lane record is a claim the data does not support.
         */
        CorpusRecordOut: {
            /** Games */
            games: number;
            /** Wins */
            wins: number;
            /** Win Rate */
            win_rate: number;
            /** Gold Diff 14 */
            gold_diff_14: number | null;
            /**
             * Timeline Games
             * @default 0
             */
            timeline_games: number;
            /**
             * Basis
             * @default lane
             * @enum {string}
             */
            basis: "role" | "lane" | "lane_pooled" | "team";
            /** Patches */
            patches: string[];
        };
        /** CorpusResponse */
        CorpusResponse: {
            /** Slices */
            slices: components["schemas"]["CorpusSliceOut"][];
            /** Brackets */
            brackets: string[];
            /** Total Matches */
            total_matches: number;
            /** Latest Game At */
            latest_game_at: number | null;
            /** Latest Ingest At */
            latest_ingest_at: number | null;
        };
        /** CorpusSliceOut */
        CorpusSliceOut: {
            /** Patch */
            patch: string;
            /** Queue Id */
            queue_id: number;
            /** Matches */
            matches: number;
        };
        /** CounterSection */
        CounterSection: {
            /** Lane */
            lane: components["schemas"]["PairEntry"][];
            /** Team */
            team: components["schemas"]["PairEntry"][];
        };
        /** CrossValidationOut */
        CrossValidationOut: {
            /** Folds */
            folds: number | null;
            overall: components["schemas"]["CvOverallOut"] | null;
            /** Phases */
            phases: components["schemas"]["CvPhaseOut"][];
            /** Reliability */
            reliability: components["schemas"]["ReliabilityBinOut"][];
            /** Ece */
            ece: number | null;
            /** Blue Win Rate */
            blue_win_rate: number | null;
        };
        /** CurvePoint */
        CurvePoint: {
            /** Ms */
            ms: number;
            /** Blue */
            blue: number;
            /**
             * Frame
             * @default false
             */
            frame: boolean;
        };
        /** CvOverallOut */
        CvOverallOut: {
            /** Rows */
            rows: number;
            /** Accuracy */
            accuracy: number;
            /** Brier */
            brier: number;
            /** Log Loss */
            log_loss: number;
            /** Baseline Brier */
            baseline_brier: number;
            /** Skill */
            skill: number;
        };
        /** CvPhaseOut */
        CvPhaseOut: {
            /** Label */
            label: string;
            /** Rows */
            rows: number;
            /** Accuracy */
            accuracy: number;
            /** Brier */
            brier: number;
            /** Log Loss */
            log_loss: number;
        };
        /**
         * DamageMixOut
         * @description One side's damage, from each of its champions' usual games.
         *
         *     Summed over the champions' average damage, so each counts by how much it
         *     deals. Shown, not scored.
         */
        DamageMixOut: {
            shares: components["schemas"]["DamageShareOut"] | null;
            /**
             * Measured
             * @default 0
             */
            measured: number;
            /** Missing */
            missing: components["schemas"]["ChampionRef"][];
            /** Leaning */
            leaning: ("physical" | "magic" | "true") | null;
        };
        /**
         * DamageShareOut
         * @description Fractions of damage to champions by type, summing to 1.
         */
        DamageShareOut: {
            /** Physical */
            physical: number;
            /** Magic */
            magic: number;
            /** True */
            true: number;
        };
        /** DeathOut */
        DeathOut: {
            /** Ms */
            ms: number;
            killer: components["schemas"]["StoryPlayerRef"] | null;
            /**
             * Assisters
             * @default 0
             */
            assisters: number;
            /**
             * X
             * @default 0
             */
            x: number;
            /**
             * Y
             * @default 0
             */
            y: number;
            /** Traded */
            traded: boolean;
            /** Cost */
            cost: number | null;
        };
        /**
         * DraftModelOut
         * @description The constants behind the ranking, so the page can state them.
         */
        DraftModelOut: {
            /** Comfort Weight */
            comfort_weight: number;
            /** Comfort Max Bonus */
            comfort_max_bonus: number;
            /** Lane Strength */
            lane_strength: number;
            /** Team Strength */
            team_strength: number;
            /** Ally Strength */
            ally_strength: number;
            /** Context Lift Cap */
            context_lift_cap: number;
            /** Lane Shrinkage */
            lane_shrinkage: number;
            /** Team Shrinkage */
            team_shrinkage: number;
            /** Ally Shrinkage */
            ally_shrinkage: number;
        };
        /** DraftRequest */
        DraftRequest: {
            /**
             * Position
             * @description The role you are picking for, in any case.
             * @enum {string}
             */
            position: "TOP" | "JUNGLE" | "MIDDLE" | "BOTTOM" | "UTILITY";
            /**
             * Allies
             * @description Champion ids already on your team.
             */
            allies?: number[];
            /** Enemies */
            enemies?: number[];
            /** Bans */
            bans?: number[];
            /**
             * Enemy Laner
             * @description The enemy champion in your lane, one of `enemies`.
             */
            enemy_laner?: number | null;
            /** Patch */
            patch?: string | null;
            /**
             * Queue Id
             * @default 420
             * @enum {integer}
             */
            queue_id?: 420 | 440;
            /**
             * Rank Bracket
             * @description Crawl provenance, not a measured rank.
             * @default ALL
             */
            rank_bracket?: string;
            /**
             * Min Games
             * @default 20
             */
            min_games?: number;
            /** Platform */
            platform?: string | null;
            /** Game Name */
            game_name?: string | null;
            /** Tag Line */
            tag_line?: string | null;
            /**
             * Comfort Weight
             * @default 0.15
             */
            comfort_weight?: number;
            /**
             * Infer Lane
             * @default true
             */
            infer_lane?: boolean;
            /** Include */
            include?: number[];
        };
        /** DraftResponse */
        DraftResponse: {
            /** Patch */
            patch: string;
            /** Patches */
            patches: string[];
            /** Position */
            position: string;
            enemy_laner: components["schemas"]["ChampionRef"] | null;
            /** Allies */
            allies: components["schemas"]["ChampionRef"][];
            /** Enemies */
            enemies: components["schemas"]["ChampionRef"][];
            /**
             * Personalised
             * @default false
             */
            personalised: boolean;
            personalisation: components["schemas"]["PersonalisationOut"];
            /** Suggestions */
            suggestions: components["schemas"]["SuggestionOut"][];
            /** Pinned */
            pinned: components["schemas"]["SuggestionOut"][];
            lane_opponent: components["schemas"]["LaneOpponentOut"] | null;
            /**
             * Blind
             * @default true
             */
            blind: boolean;
            duo: components["schemas"]["ChampionRef"] | null;
            /** Enemy Roles */
            enemy_roles: components["schemas"]["RoleGuessOut"][];
            /** Ally Roles */
            ally_roles: components["schemas"]["RoleGuessOut"][];
            role_clash: components["schemas"]["RoleClashOut"] | null;
            lobby_ranks: components["schemas"]["LobbyRanksOut"] | null;
            team_damage: components["schemas"]["TeamDamageOut"];
            /**
             * Bans Read The Draft
             * @default false
             */
            bans_read_the_draft: boolean;
            /** Ban Candidates */
            ban_candidates: components["schemas"]["BanCandidateOut"][];
            model: components["schemas"]["DraftModelOut"];
            /** Empty Reason */
            empty_reason: "min_games" | null;
            /**
             * Most Games
             * @default 0
             */
            most_games: number;
            /** Warnings */
            warnings: string[];
        };
        /**
         * EvidenceOut
         * @description One record about a pick, with the sample it rests on and how it was read.
         */
        EvidenceOut: {
            /**
             * Kind
             * @enum {string}
             */
            kind: "lane" | "enemy" | "ally";
            champion: components["schemas"]["ChampionRef"];
            /** Games */
            games: number;
            /** Wins */
            wins: number;
            /** Win Rate */
            win_rate: number;
            /** Own Rate */
            own_rate: number;
            /** Lift */
            lift: number;
            /**
             * Call
             * @enum {string}
             */
            call: "favoured" | "unfavoured" | "level";
            /** Scored */
            scored: boolean;
            /** Patches */
            patches: string[];
            /** Gold Diff 14 */
            gold_diff_14: number | null;
            /** Laning Score */
            laning_score: number | null;
            /**
             * Timeline Games
             * @default 0
             */
            timeline_games: number;
            /**
             * Weight
             * @default 1
             */
            weight: number;
            /**
             * Credible Lift
             * @default 0
             */
            credible_lift: number;
        };
        /**
         * FacetEntry
         * @description One thing a champion took, with how often and how it went.
         */
        FacetEntry: {
            /** Ids */
            ids: number[];
            /** Games */
            games: number;
            /** Wins */
            wins: number;
            /** Win Rate */
            win_rate: number;
            /** Pick Rate */
            pick_rate: number;
            /**
             * Range Low
             * @default 0
             */
            range_low: number;
            /**
             * Range High
             * @default 1
             */
            range_high: number;
            /** Slot Delta */
            slot_delta: number | null;
            /**
             * Slot Buyers
             * @default 0
             */
            slot_buyers: number;
            /** Items */
            items: components["schemas"]["ItemRef"][];
            /** Spells */
            spells: components["schemas"]["SpellRef"][];
            /** Runes */
            runes: components["schemas"]["RuneRef"][];
        };
        /** GameStoryResponse */
        GameStoryResponse: {
            /** Match Id */
            match_id: string;
            /** Available */
            available: boolean;
            /**
             * Pending
             * @default false
             */
            pending: boolean;
            /** Retry After */
            retry_after: number | null;
            /** Reason */
            reason: string | null;
            /** Queue Id */
            queue_id: number | null;
            /**
             * Duration Ms
             * @default 0
             */
            duration_ms: number;
            /** Blue Won */
            blue_won: boolean | null;
            /** Curve */
            curve: components["schemas"]["CurvePoint"][];
            /** Moments */
            moments: components["schemas"]["MomentOut"][];
            /** Players */
            players: components["schemas"]["PlayerStoryOut"][];
            model: components["schemas"]["StoryModelOut"] | null;
            /** Map Url */
            map_url: string | null;
        };
        /** GroupChampionOut */
        GroupChampionOut: {
            champion: components["schemas"]["ChampionRef"];
            /** Games */
            games: number;
            /** Wins */
            wins: number;
            /** Win Rate */
            win_rate: number;
            /** Kda */
            kda: number;
        };
        /** GroupCreateRequest */
        GroupCreateRequest: {
            /** Name */
            name: string;
        };
        /** GroupCreatedResponse */
        GroupCreatedResponse: {
            /** Slug */
            slug: string;
            /** Name */
            name: string;
            /** Key */
            key: string;
        };
        /**
         * GroupHistoryOut
         * @description How much of this player's history is stored, and whether more is coming.
         */
        GroupHistoryOut: {
            /**
             * Stored
             * @default 0
             */
            stored: number;
            /** Oldest */
            oldest: number | null;
            /**
             * Read
             * @default 0
             */
            read: number;
            /**
             * Exhausted
             * @default false
             */
            exhausted: boolean;
            /**
             * Pending
             * @default true
             */
            pending: boolean;
        };
        /** GroupKeyResponse */
        GroupKeyResponse: {
            /** Key */
            key: string;
        };
        /** GroupMemberAddRequest */
        GroupMemberAddRequest: {
            /** Riot Id */
            riot_id: string;
            /** Platform */
            platform: string;
            /** Label */
            label?: string | null;
        };
        /** GroupMemberAddedResponse */
        GroupMemberAddedResponse: {
            /** Puuid */
            puuid: string;
            /** Riot Id */
            riot_id: string;
            /** Platform */
            platform: string;
            /** Platform Label */
            platform_label: string;
        };
        /** GroupMemberLabelRequest */
        GroupMemberLabelRequest: {
            /** Label */
            label?: string | null;
        };
        /** GroupMemberOut */
        GroupMemberOut: {
            /** Puuid */
            puuid: string;
            /** Riot Id */
            riot_id: string;
            /** Game Name */
            game_name: string | null;
            /** Tag Line */
            tag_line: string | null;
            /** Platform */
            platform: string;
            /** Platform Label */
            platform_label: string;
            /** Profile Icon Url */
            profile_icon_url: string | null;
            /** Summoner Level */
            summoner_level: number | null;
            /** Label */
            label: string | null;
            /** Added At */
            added_at: number | null;
            /** Ranks */
            ranks: components["schemas"]["RankInfo"][];
            /** Rank Read At */
            rank_read_at: number | null;
            /**
             * Games
             * @default 0
             */
            games: number;
            /**
             * Wins
             * @default 0
             */
            wins: number;
            /** Withheld */
            withheld: string | null;
            /** Win Rate */
            win_rate: number | null;
            /** Kda */
            kda: number | null;
            /** Avg Kills */
            avg_kills: number | null;
            /** Avg Deaths */
            avg_deaths: number | null;
            /** Avg Assists */
            avg_assists: number | null;
            /** Cs Per Min */
            cs_per_min: number | null;
            /** Damage Per Min */
            damage_per_min: number | null;
            /** Vision Per Min */
            vision_per_min: number | null;
            /** Avg Minutes */
            avg_minutes: number | null;
            /** Main Position */
            main_position: string | null;
            /** Positions */
            positions: components["schemas"]["RoleShare"][];
            /** Champions */
            champions: components["schemas"]["GroupChampionOut"][];
            /** Recent */
            recent: boolean[];
            /**
             * Scored Games
             * @default 0
             */
            scored_games: number;
            /** Avg Score */
            avg_score: number | null;
            /** Score Profile */
            score_profile: components["schemas"]["RoleScoreProfileOut"][];
            /** Review */
            review: components["schemas"]["RoleReviewOut"][];
            /** Lanes */
            lanes: components["schemas"]["LaneRecordOut"][];
            history: components["schemas"]["GroupHistoryOut"];
        };
        /** GroupPairOut */
        GroupPairOut: {
            /** A */
            a: string;
            /** B */
            b: string;
            /** Games */
            games: number;
            /** Wins */
            wins: number;
            /** Win Rate */
            win_rate: number;
        };
        /** GroupQueueOut */
        GroupQueueOut: {
            /** Key */
            key: string;
            /** Label */
            label: string;
        };
        /** GroupRenameRequest */
        GroupRenameRequest: {
            /** Name */
            name: string;
        };
        /** GroupResponse */
        GroupResponse: {
            /** Slug */
            slug: string;
            /** Name */
            name: string;
            /** Created At */
            created_at: number | null;
            /** Updated At */
            updated_at: number | null;
            /**
             * Can Edit
             * @default false
             */
            can_edit: boolean;
            /** Max Members */
            max_members: number;
            /** History Cap */
            history_cap: number;
            /** Min Games */
            min_games: number;
            /** Queue */
            queue: string;
            /** Queues */
            queues: components["schemas"]["GroupQueueOut"][];
            /**
             * Scored Mode
             * @default true
             */
            scored_mode: boolean;
            /** Members */
            members: components["schemas"]["GroupMemberOut"][];
            together: components["schemas"]["GroupTogetherOut"];
            /**
             * Pending
             * @default 0
             */
            pending: number;
            /**
             * Fetching
             * @default true
             */
            fetching: boolean;
        };
        /**
         * GroupTogetherOut
         * @description Stored games where two or more of the group played on the same side.
         */
        GroupTogetherOut: {
            /**
             * Games
             * @default 0
             */
            games: number;
            /**
             * Wins
             * @default 0
             */
            wins: number;
            /** Min Pair Games */
            min_pair_games: number;
            /** Pairs */
            pairs: components["schemas"]["GroupPairOut"][];
            /** Recent */
            recent: components["schemas"]["TogetherGameOut"][];
        };
        /**
         * GroupWarmResponse
         * @description One bounded pass of fetching a group's missing games from Riot.
         */
        GroupWarmResponse: {
            /**
             * Pending
             * @default 0
             */
            pending: number;
            /**
             * Fetching
             * @default true
             */
            fetching: boolean;
            /**
             * Key Busy
             * @default false
             */
            key_busy: boolean;
            /** Retry After */
            retry_after: number | null;
            /**
             * Calls
             * @default 0
             */
            calls: number;
            /**
             * Games
             * @default 0
             */
            games: number;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HealthResponse */
        HealthResponse: {
            /** Status */
            status: string;
            /** Riot Key Configured */
            riot_key_configured: boolean;
            /** Static Data Version */
            static_data_version: string | null;
            rate_limit: components["schemas"]["RateLimitOut"];
            /**
             * Spectator Enabled
             * @default true
             */
            spectator_enabled: boolean;
        };
        /**
         * IdleSummaryOut
         * @description What we hold for a player who is not in a game.
         *
         *     Measured on 2026-09-21: 31 live lookups against production, covering the
         *     active EUW and NA challengers and everyone in that week's best games, found
         *     nobody in a game. This is the live page's normal state, so it carries
         *     something rather than an empty box.
         *
         *     ``last_game`` is the newest game **Riftline has stored**, which is not the
         *     newest game they played: the corpus is crawled, and for a player with five
         *     or more stored games the newest one is a median of four days old (p90
         *     seven). Anything rendering this has to word it that way.
         */
        IdleSummaryOut: {
            /** Stored Games */
            stored_games: number;
            last_game: components["schemas"]["LastStoredGameOut"] | null;
            /**
             * Basis
             * @default stored_matches
             */
            basis: string;
        };
        /** ItemChampionOut */
        ItemChampionOut: {
            champion: components["schemas"]["ChampionRef"];
            /** Buyers */
            buyers: number;
            /** Share */
            share: number;
            /** Win Rate */
            win_rate: number;
            /** Delta */
            delta: number | null;
            /** Minute */
            minute: number | null;
            /** Usual Slot */
            usual_slot: number | null;
        };
        /** ItemDetail */
        ItemDetail: {
            /** Id */
            id: number;
            /** Name */
            name: string;
            /** Icon Url */
            icon_url: string | null;
            /**
             * Plaintext
             * @default
             */
            plaintext: string;
            /** Cost */
            cost: number;
            /** Combine Cost */
            combine_cost: number;
            /** Sell */
            sell: number;
            /** Purchasable */
            purchasable: boolean;
            /** Tags */
            tags: string[];
            /** Group */
            group: string | null;
            /** Group Label */
            group_label: string | null;
            /** On Rift */
            on_rift: boolean;
            /** Stats */
            stats: components["schemas"]["StatLine"][];
            /** Effects */
            effects: components["schemas"]["ItemEffectOut"][];
            /** Builds From */
            builds_from: components["schemas"]["ItemRefOut"][];
            /** Builds Into */
            builds_into: components["schemas"]["ItemRefOut"][];
            grows_from: components["schemas"]["ItemRefOut"] | null;
            /** Grows Into */
            grows_into: components["schemas"]["ItemRefOut"][];
            figures: components["schemas"]["ItemFigures"] | null;
            /** Figures Note */
            figures_note: string | null;
            /** Slug */
            readonly slug: string | null;
        };
        /** ItemEffectOut */
        ItemEffectOut: {
            /** Kind */
            kind: string;
            /** Name */
            name: string | null;
            /** Text */
            text: string;
        };
        /** ItemFigures */
        ItemFigures: {
            /** Patch */
            patch: string;
            /** Queue Id */
            queue_id: number;
            /** Rank Bracket */
            rank_bracket: string;
            /** Players */
            players: number;
            /** Holders */
            holders: number;
            /** Held Share */
            held_share: number;
            /** Ordered Players */
            ordered_players: number;
            /** Buyers */
            buyers: number;
            /** Bought Share */
            bought_share: number;
            /** Buyer Win Rate */
            buyer_win_rate: number | null;
            /**
             * Timed
             * @default 0
             */
            timed: number;
            /** Minute P25 */
            minute_p25: number | null;
            /** Minute P50 */
            minute_p50: number | null;
            /** Minute P75 */
            minute_p75: number | null;
            /** Slots */
            slots: components["schemas"]["ItemSlotOut"][];
            /** Delta */
            delta: number | null;
            /**
             * Delta Games
             * @default 0
             */
            delta_games: number;
            /**
             * Slot Min Games
             * @default 30
             */
            slot_min_games: number;
            /**
             * Champion Min Buyers
             * @default 20
             */
            champion_min_buyers: number;
            /** Champions */
            champions: components["schemas"]["ItemChampionOut"][];
        };
        /** ItemList */
        ItemList: {
            /** Version */
            version: string | null;
            /** Patch */
            patch: string | null;
            /** Sections */
            sections: components["schemas"]["ItemSection"][];
        };
        /** ItemRef */
        ItemRef: {
            /** Id */
            id: number;
            /** Name */
            name: string | null;
            /** Icon Url */
            icon_url: string | null;
            /** Slug */
            readonly slug: string | null;
        };
        /** ItemRefOut */
        ItemRefOut: {
            /** Id */
            id: number;
            /** Name */
            name: string;
            /** Icon Url */
            icon_url: string | null;
            /**
             * Cost
             * @default 0
             */
            cost: number;
            /** Slug */
            readonly slug: string | null;
        };
        /** ItemSection */
        ItemSection: {
            /** Key */
            key: string;
            /** Label */
            label: string;
            /** Items */
            items: components["schemas"]["ItemSummary"][];
        };
        /** ItemSlotOut */
        ItemSlotOut: {
            /** Slot */
            slot: number;
            /** Games */
            games: number;
            /** Share */
            share: number;
            /** Win Rate */
            win_rate: number;
            /** Delta */
            delta: number | null;
        };
        /** ItemSummary */
        ItemSummary: {
            /** Id */
            id: number;
            /** Name */
            name: string;
            /** Icon Url */
            icon_url: string | null;
            /** Cost */
            cost: number;
            /**
             * Plaintext
             * @default
             */
            plaintext: string;
            /** Tags */
            tags: string[];
            /** Stats */
            stats: components["schemas"]["StatLine"][];
            /** Bought Share */
            bought_share: number | null;
            /** Slug */
            readonly slug: string | null;
        };
        /**
         * LadderPositionOut
         * @description Where the player stands on the stored solo ladder of their home shard.
         */
        LadderPositionOut: {
            /** Tier */
            tier: string;
            /** Tier Position */
            tier_position: number;
            /** Position */
            position: number | null;
            /** Platform */
            platform: string;
            /** Platform Label */
            platform_label: string;
            /** As Of */
            as_of: number;
        };
        /** LaneMethod */
        LaneMethod: {
            /** Even Below */
            even_below: number;
            /** Big From */
            big_from: number;
            /** Labels */
            labels: {
                [key: string]: string;
            };
            /** Min Games */
            min_games: number;
        };
        /** LaneOpponentOut */
        LaneOpponentOut: {
            champion: components["schemas"]["ChampionRef"];
            /**
             * Source
             * @enum {string}
             */
            source: "marked" | "inferred";
            /** Probability */
            probability: number;
        };
        /**
         * LaneRecordOut
         * @description How this player's lanes went, per role, over games with a timeline.
         */
        LaneRecordOut: {
            /** Position */
            position: string;
            /** Games */
            games: number;
            /**
             * Won Big
             * @default 0
             */
            won_big: number;
            /**
             * Won
             * @default 0
             */
            won: number;
            /**
             * Even
             * @default 0
             */
            even: number;
            /**
             * Lost
             * @default 0
             */
            lost: number;
            /**
             * Lost Big
             * @default 0
             */
            lost_big: number;
        };
        /**
         * LaningOut
         * @description A champion's own laning figures in the role, over its games with timelines.
         */
        LaningOut: {
            /** Gold Diff 14 */
            gold_diff_14: number | null;
            /** Cs Diff 14 */
            cs_diff_14: number | null;
            /** Laning Score */
            laning_score: number | null;
            /** Timeline Games */
            timeline_games: number;
        };
        /**
         * LaningSection
         * @description How the laning phase goes, measured at minute 14.
         *
         *     ``games`` is not the champion's game count: it is how many of those games
         *     had a timeline. On a partly backfilled corpus that gap is the difference
         *     between an average and a claim. The averages are null under ``min_games``
         *     of them, as the tier list's gold column and the draft's laning figures are.
         */
        LaningSection: {
            /**
             * Games
             * @default 0
             */
            games: number;
            /**
             * Min Games
             * @default 10
             */
            min_games: number;
            /** Avg Score */
            avg_score: number | null;
            /** Avg Gold Diff */
            avg_gold_diff: number | null;
            /** Avg Cs Diff */
            avg_cs_diff: number | null;
        };
        /**
         * LastStoredGameOut
         * @description The newest game we hold for a player, for the page they see when they are
         *     not playing.
         */
        LastStoredGameOut: {
            /** Match Id */
            match_id: string;
            /** Queue Id */
            queue_id: number;
            /** Queue Name */
            queue_name: string;
            champion: components["schemas"]["ChampionRef"];
            /** Position */
            position: string | null;
            /** Win */
            win: boolean;
            /** Kills */
            kills: number;
            /** Deaths */
            deaths: number;
            /** Assists */
            assists: number;
            /** Game Creation */
            game_creation: number;
            /** Game Duration */
            game_duration: number;
            /** Performance Score */
            performance_score: number | null;
        };
        /** LeaderboardResponse */
        LeaderboardResponse: {
            /** Platform */
            platform: string;
            /** Platform Label */
            platform_label: string;
            /** Queue Id */
            queue_id: number;
            /** Queue Label */
            queue_label: string;
            /** Tier */
            tier: string;
            /** Division */
            division: string | null;
            /** Page */
            page: number;
            /** Per Page */
            per_page: number;
            /** Total */
            total: number;
            /** Total On Ladder */
            total_on_ladder: number | null;
            /**
             * Truncated
             * @default false
             */
            truncated: boolean;
            /**
             * Has More
             * @default false
             */
            has_more: boolean;
            /**
             * Named On Page
             * @default 0
             */
            named_on_page: number;
            /**
             * Names Held Back
             * @default false
             */
            names_held_back: boolean;
            /** Names Retry After */
            names_retry_after: number | null;
            /** Fetched At */
            fetched_at: number | null;
            /** Rows */
            rows: components["schemas"]["LeaderboardRow"][];
        };
        /** LeaderboardRow */
        LeaderboardRow: {
            /** Position */
            position: number;
            /** Puuid */
            puuid: string;
            /** Riot Id */
            riot_id: string | null;
            /**
             * No Riot Id
             * @default false
             */
            no_riot_id: boolean;
            /** Tier */
            tier: string;
            /** Division */
            division: string | null;
            /**
             * League Points
             * @default 0
             */
            league_points: number;
            /**
             * Wins
             * @default 0
             */
            wins: number;
            /**
             * Losses
             * @default 0
             */
            losses: number;
            /**
             * Games
             * @default 0
             */
            games: number;
            /**
             * Win Rate
             * @default 0
             */
            win_rate: number;
            /**
             * Hot Streak
             * @default false
             */
            hot_streak: boolean;
            /**
             * Veteran
             * @default false
             */
            veteran: boolean;
            /**
             * Fresh Blood
             * @default false
             */
            fresh_blood: boolean;
            /**
             * Inactive
             * @default false
             */
            inactive: boolean;
            /**
             * Numeric Rank
             * @default 0
             */
            numeric_rank: number;
        };
        /** LeaderboardSlices */
        LeaderboardSlices: {
            /** Platforms */
            platforms: components["schemas"]["PlatformOptionOut"][];
            /** Queues */
            queues: components["schemas"]["QueueOptionOut"][];
            /** Tiers */
            tiers: string[];
            /** Divisions */
            divisions: string[];
            /** Apex Tiers */
            apex_tiers: string[];
        };
        /** LiveBanOut */
        LiveBanOut: {
            champion: components["schemas"]["ChampionRef"];
            /** Team Id */
            team_id: number;
            /** Ban Rate */
            ban_rate: number | null;
            /**
             * Ban Rate Games
             * @default 0
             */
            ban_rate_games: number;
        };
        /** LiveGameOut */
        LiveGameOut: {
            /** Game Id */
            game_id: number;
            /** Platform Id */
            platform_id: string;
            /** Match Id */
            match_id: string;
            /** Queue Id */
            queue_id: number;
            /** Queue Name */
            queue_name: string;
            /** Game Mode */
            game_mode: string | null;
            /** Map Id */
            map_id: number | null;
            /** Phase */
            phase: string;
            /** Game Start Time */
            game_start_time: number;
            /** Game Length */
            game_length: number;
            /** Observed At */
            observed_at: number;
            /** Banned Champions */
            banned_champions: components["schemas"]["ChampionRef"][];
            /** Bans */
            bans: components["schemas"]["LiveBanOut"][];
            /** Participants */
            participants: components["schemas"]["LiveParticipantOut"][];
            lobby_rank: components["schemas"]["LobbyRankOut"] | null;
            /**
             * You Identified
             * @default true
             */
            you_identified: boolean;
            /**
             * Positions Inferred
             * @default false
             */
            positions_inferred: boolean;
            position_model: components["schemas"]["PositionModelOut"] | null;
            /** Corpus Patch */
            corpus_patch: string | null;
            /** Corpus Patches */
            corpus_patches: string[];
            /**
             * Record Basis
             * @default all_queues
             */
            record_basis: string;
            /** Record Queue Id */
            record_queue_id: number | null;
            sides: components["schemas"]["LobbyCompareOut"] | null;
            /** Same Team Pairs */
            same_team_pairs: components["schemas"]["SameTeamPairOut"][];
        };
        /** LiveGameResponse */
        LiveGameResponse: {
            /** Puuid */
            puuid: string;
            /** Platform */
            platform: string;
            /**
             * In Game
             * @default false
             */
            in_game: boolean;
            game: components["schemas"]["LiveGameOut"] | null;
            idle: components["schemas"]["IdleSummaryOut"] | null;
            /** Checked At */
            checked_at: number;
        };
        /** LiveMasteryOut */
        LiveMasteryOut: {
            /** Level */
            level: number;
            /** Points */
            points: number;
            /** Last Play Time */
            last_play_time: number | null;
        };
        /**
         * LiveParticipantOut
         * @description One player in a live game.
         *
         *     ``state`` carries the honesty. ``hidden`` means Riot returned no account id
         *     for them because they opted out of third-party visibility, so there is no
         *     name, no rank and no profile to link to. ``unknown`` means we could not
         *     complete the rank lookup in time, which is a different thing from
         *     ``unranked``.
         */
        LiveParticipantOut: {
            /**
             * State
             * @enum {string}
             */
            state: "ranked" | "unranked" | "hidden" | "bot" | "unknown";
            /** Puuid */
            puuid: string | null;
            /** Riot Id */
            riot_id: string | null;
            champion: components["schemas"]["ChampionRef"];
            /** Team Id */
            team_id: number;
            /** Spells */
            spells: components["schemas"]["SpellRef"][];
            keystone: components["schemas"]["RuneRef"] | null;
            secondary_tree: components["schemas"]["RuneRef"] | null;
            /** Profile Icon Url */
            profile_icon_url: string | null;
            rank: components["schemas"]["RankInfo"] | null;
            /** Skin Tile Url */
            skin_tile_url: string | null;
            /** Position */
            position: string | null;
            /** Position Confidence */
            position_confidence: number | null;
            /** Position Basis */
            position_basis: string | null;
            mastery: components["schemas"]["LiveMasteryOut"] | null;
            /**
             * Mastery Known
             * @default false
             */
            mastery_known: boolean;
            champion_record: components["schemas"]["CorpusRecordOut"] | null;
            lane_record: components["schemas"]["CorpusRecordOut"] | null;
            /**
             * Stored Games
             * @default 0
             */
            stored_games: number;
            record: components["schemas"]["PlayerRecordOut"] | null;
            shared_games: components["schemas"]["SharedGamesOut"] | null;
        };
        /**
         * LobbyCompareOut
         * @description The two sides beside each other.
         *
         *     Carries no win probability and no verdict, deliberately. The site holds no
         *     model that predicts a game, so a percentage here would be the only number on
         *     the page with nothing behind it, and about a third of a lobby hides its
         *     identity, which is not a third missing at random.
         */
        LobbyCompareOut: {
            /** Sides */
            sides: components["schemas"]["SideReadOut"][];
            /** You Team Id */
            you_team_id: number | null;
            /**
             * Lanes With Record
             * @default 0
             */
            lanes_with_record: number;
            /**
             * Lanes Level
             * @default 0
             */
            lanes_level: number;
            /**
             * Lanes Total
             * @default 0
             */
            lanes_total: number;
            /**
             * Min Ranked Per Side
             * @default 3
             */
            min_ranked_per_side: number;
        };
        /** LobbyRankBucket */
        LobbyRankBucket: {
            /** Tier */
            tier: string;
            /** Games */
            games: number;
        };
        /**
         * LobbyRankOut
         * @description A lobby's median rank, always shipping its own sample size.
         *
         *     Around a third of a live lobby hides its identity, and that is not missing
         *     at random, so the counts are not optional detail: a number without them
         *     would be claiming a census it never took. Below the floor the rank is
         *     withheld outright rather than shown greyed out.
         *
         *     ``extra="forbid"`` because this model is built by splatting a dataclass
         *     (``LobbyRankOut(**asdict(...))``). With the default behaviour a field
         *     renamed on one side is silently dropped and the other side quietly takes its
         *     default: renaming `average_points` to `median_points` served `null` beside a
         *     populated `tier`, and the UI reported "not enough identified players" for a
         *     lobby of eight. Forbidding extras turns that into an error at the boundary.
         */
        LobbyRankOut: {
            /** Median Points */
            median_points: number | null;
            /** Tier */
            tier: string | null;
            /** Division */
            division: string | null;
            /** League Points */
            league_points: number | null;
            /**
             * Ranked
             * @default 0
             */
            ranked: number;
            /**
             * Unranked
             * @default 0
             */
            unranked: number;
            /**
             * Hidden
             * @default 0
             */
            hidden: number;
            /**
             * Bots
             * @default 0
             */
            bots: number;
            /**
             * Unknown
             * @default 0
             */
            unknown: number;
            /** Queue Type */
            queue_type: string;
            /**
             * Queue Matches Game
             * @default true
             */
            queue_matches_game: boolean;
        };
        /**
         * LobbyRanksOut
         * @description How the games behind this slice were ranked, by measured lobby median.
         */
        LobbyRanksOut: {
            /** Total */
            total: number;
            /** Measured */
            measured: number;
            /** Buckets */
            buckets: components["schemas"]["LobbyRankBucket"][];
            /** As Of */
            as_of: number | null;
        };
        /** MasteryEntry */
        MasteryEntry: {
            champion: components["schemas"]["ChampionRef"];
            /** Level */
            level: number;
            /** Points */
            points: number;
            /**
             * Points Since Last Level
             * @default 0
             */
            points_since_last_level: number;
            /**
             * Points Until Next Level
             * @default 0
             */
            points_until_next_level: number;
            /**
             * Progress To Next
             * @default 0
             */
            progress_to_next: number;
            /** Last Play Time */
            last_play_time: number | null;
            /**
             * Tokens Earned
             * @default 0
             */
            tokens_earned: number;
            /** Season Milestone */
            season_milestone: number | null;
            /** Milestone Grades */
            milestone_grades: string[] | null;
            /** Tags */
            tags: string[];
            /**
             * Champion Known
             * @default true
             */
            champion_known: boolean;
        };
        /**
         * MasteryResponse
         * @description Every champion this account has touched, newest Riot reading first.
         *
         *     `champions_owned_ratio` and a `levels` histogram used to ride along here.
         *     Both are gone: the ratio divided by our static roster and so exceeded 1.0
         *     for as long as Data Dragon lagged a champion release, and the histogram was
         *     34 buckets of an unbounded scale that nothing read. The page holds the
         *     roster already and counts what it needs from `entries`.
         */
        MasteryResponse: {
            /** Puuid */
            puuid: string;
            /**
             * Total Points
             * @default 0
             */
            total_points: number;
            /**
             * Total Champions Played
             * @default 0
             */
            total_champions_played: number;
            /** Platform */
            platform: string | null;
            /** Fetched At */
            fetched_at: number | null;
            /** Entries */
            entries: components["schemas"]["MasteryEntry"][];
        };
        /** MatchDetailResponse */
        MatchDetailResponse: {
            /** Match Id */
            match_id: string;
            /** Queue Id */
            queue_id: number;
            /** Queue Name */
            queue_name: string;
            /** Patch */
            patch: string | null;
            /** Game Creation */
            game_creation: number;
            /** Game Duration */
            game_duration: number;
            /**
             * Is Remake
             * @default false
             */
            is_remake: boolean;
            /** Platform */
            platform: string | null;
            /** Score Withheld */
            score_withheld: string | null;
            /** Teams */
            teams: components["schemas"]["ScoreboardPlayer"][][];
            /** Objectives */
            objectives: components["schemas"]["TeamObjectives"][];
            model: components["schemas"]["ScoreModelOut"] | null;
        };
        /** MatchHistoryResponse */
        MatchHistoryResponse: {
            /** Puuid */
            puuid: string;
            /** Matches */
            matches: components["schemas"]["MatchSummary"][];
            /** Start */
            start: number;
            /** Count */
            count: number;
            /**
             * Has More
             * @default false
             */
            has_more: boolean;
            /**
             * Source
             * @default riot
             */
            source: string;
            /** Stored Total */
            stored_total: number | null;
        };
        /**
         * MatchResolveResponse
         * @description Whether a finished live game has reached storage yet.
         *
         *     Always 200, never a 404. The match will exist: the question is answerable
         *     and the answer is "not yet". A 404 here would render as "no such match",
         *     which is a different and false claim, the same reason the live endpoint
         *     answers 200 with ``in_game: false``.
         */
        MatchResolveResponse: {
            /** Match Id */
            match_id: string;
            /** Status */
            status: string;
            /**
             * Attempted
             * @default false
             */
            attempted: boolean;
            /** Retry After */
            retry_after: number | null;
            /** Game Creation */
            game_creation: number | null;
            /** Game Duration */
            game_duration: number | null;
            /** Win */
            win: boolean | null;
            /** Score */
            score: number | null;
            /** Placement */
            placement: number | null;
            /** Hint */
            hint: string | null;
        };
        /**
         * MatchSummary
         * @description One row of match history, from the searched player's point of view.
         */
        MatchSummary: {
            /** Match Id */
            match_id: string;
            /** Queue Id */
            queue_id: number;
            /** Queue Name */
            queue_name: string;
            /** Patch */
            patch: string | null;
            /** Game Creation */
            game_creation: number;
            /** Game Duration */
            game_duration: number;
            /**
             * Is Remake
             * @default false
             */
            is_remake: boolean;
            /** Win */
            win: boolean;
            champion: components["schemas"]["ChampionRef"];
            /**
             * Champ Level
             * @default 0
             */
            champ_level: number;
            /** Position */
            position: string | null;
            /**
             * Kills
             * @default 0
             */
            kills: number;
            /**
             * Deaths
             * @default 0
             */
            deaths: number;
            /**
             * Assists
             * @default 0
             */
            assists: number;
            /**
             * Kda
             * @default 0
             */
            kda: number;
            /**
             * Kill Participation
             * @default 0
             */
            kill_participation: number;
            /**
             * Cs
             * @default 0
             */
            cs: number;
            /**
             * Cs Per Min
             * @default 0
             */
            cs_per_min: number;
            /**
             * Gold Earned
             * @default 0
             */
            gold_earned: number;
            /**
             * Vision Score
             * @default 0
             */
            vision_score: number;
            /**
             * Damage To Champions
             * @default 0
             */
            damage_to_champions: number;
            /**
             * Damage Per Min
             * @default 0
             */
            damage_per_min: number;
            /** Items */
            items: components["schemas"]["ItemRef"][];
            trinket: components["schemas"]["ItemRef"] | null;
            /** Spells */
            spells: components["schemas"]["SpellRef"][];
            keystone: components["schemas"]["RuneRef"] | null;
            secondary_tree: components["schemas"]["RuneRef"] | null;
            /** Multi Kill */
            multi_kill: string | null;
            /** Laning Score */
            laning_score: number | null;
            laning_opponent: components["schemas"]["ChampionRef"] | null;
            /** Laning Label */
            laning_label: ("won_big" | "won" | "even" | "lost" | "lost_big") | null;
            /** Gold Diff 14 */
            gold_diff_14: number | null;
            /** Cs Diff 14 */
            cs_diff_14: number | null;
            /** Lobby Rank Points */
            lobby_rank_points: number | null;
            /** Lobby Rank Tier */
            lobby_rank_tier: string | null;
            /** Lobby Rank Division */
            lobby_rank_division: string | null;
            /** Lobby Ranked Players */
            lobby_ranked_players: number | null;
            /** Lobby Players Total */
            lobby_players_total: number | null;
            /** Lobby Rank Measured At */
            lobby_rank_measured_at: number | null;
            /**
             * Lobby Queue Matches Game
             * @default true
             */
            lobby_queue_matches_game: boolean;
            /** Score */
            score: number | null;
            /** Placement */
            placement: number | null;
            /** Badges */
            badges: components["schemas"]["BadgeOut"][];
            /** Score Components */
            score_components: components["schemas"]["ScoreComponentOut"][];
            /** Score Sample */
            score_sample: number | null;
            /** Teams */
            teams: components["schemas"]["ParticipantBrief"][][];
        };
        /** MetaResponse */
        MetaResponse: {
            /** Patch */
            patch: string;
            /** Queue Id */
            queue_id: number;
            /** Position */
            position: string | null;
            /**
             * Rank Bracket
             * @default ALL
             */
            rank_bracket: string;
            /** Sample Matches */
            sample_matches: number;
            /** Min Games */
            min_games: number;
            /** Rows */
            rows: components["schemas"]["ChampionMetaRow"][];
            lobby_ranks: components["schemas"]["LobbyRanksOut"] | null;
            /** Previous Patch */
            previous_patch: string | null;
            /**
             * Tier Min Games
             * @default 20
             */
            tier_min_games: number;
            /**
             * Separated Above
             * @default 0
             */
            separated_above: number;
            /**
             * Separated Below
             * @default 0
             */
            separated_below: number;
            /** Empty Reason */
            empty_reason: "min_games" | null;
            /**
             * Most Games
             * @default 0
             */
            most_games: number;
        };
        /** MethodResponse */
        MethodResponse: {
            score: components["schemas"]["ScoreMethod"];
            win_model: components["schemas"]["WinModelMethod"] | null;
            review: components["schemas"]["ReviewMethod"];
            lanes: components["schemas"]["LaneMethod"];
        };
        /** MomentOut */
        MomentOut: {
            /** Start Ms */
            start_ms: number;
            /** End Ms */
            end_ms: number;
            /** Swing */
            swing: number;
            /** Team */
            team: number;
            /** Text */
            text: string;
        };
        /** PageOut */
        PageOut: {
            /** Path */
            path: string;
            /** Kind */
            kind: string;
            /** Indexable */
            indexable: boolean;
            /** Lastmod */
            lastmod: number | null;
            /**
             * Required
             * @default false
             */
            required: boolean;
            /** Reason */
            reason: string | null;
        };
        /**
         * PagesResponse
         * @description The prerenderer's manifest: every page, and which may be indexed.
         */
        PagesResponse: {
            /** Origin */
            origin: string;
            /** Index Patch */
            index_patch: string | null;
            /** Pages */
            pages: components["schemas"]["PageOut"][];
        };
        /**
         * PairEntry
         * @description One record against an opponent or beside an ally, read as the draft reads it.
         *
         *     Over the patch shown and the close one before it, each patch against the
         *     champion's own rate on that patch. Ranked by the raw record, the hardest
         *     five lanes on each of the 31 busiest local pages were all level by this
         *     reading, and 22 of 155 sat at or above the champion's own rate
         *     (2026-09-24).
         */
        PairEntry: {
            champion: components["schemas"]["ChampionRef"];
            /** Games */
            games: number;
            /** Wins */
            wins: number;
            /** Win Rate */
            win_rate: number;
            /**
             * Own Rate
             * @default 0
             */
            own_rate: number;
            /**
             * Lift
             * @default 0
             */
            lift: number;
            /**
             * Call
             * @default level
             * @enum {string}
             */
            call: "favoured" | "unfavoured" | "level";
            /** Patches */
            patches: string[];
            /** Confidence Win Rate */
            confidence_win_rate: number;
            /**
             * Confidence High
             * @default 1
             */
            confidence_high: number;
            /** Position */
            position: string | null;
            /** Avg Laning Score */
            avg_laning_score: number | null;
            /** Avg Gold Diff 14 */
            avg_gold_diff_14: number | null;
            /**
             * Timeline Games
             * @default 0
             */
            timeline_games: number;
        };
        /**
         * PairModelOut
         * @description The prior each kind of record is read with, in games, so the page can say
         *     it: a record of that many games counts for half.
         */
        PairModelOut: {
            /**
             * Lane Strength
             * @default 100
             */
            lane_strength: number;
            /**
             * Team Strength
             * @default 500
             */
            team_strength: number;
            /**
             * Ally Strength
             * @default 500
             */
            ally_strength: number;
        };
        /** ParticipantBrief */
        ParticipantBrief: {
            /** Puuid */
            puuid: string;
            /** Riot Id */
            riot_id: string | null;
            champion: components["schemas"]["ChampionRef"];
            /** Team Id */
            team_id: number;
            /** Position */
            position: string | null;
            /**
             * Kills
             * @default 0
             */
            kills: number;
            /**
             * Deaths
             * @default 0
             */
            deaths: number;
            /**
             * Assists
             * @default 0
             */
            assists: number;
            /**
             * Win
             * @default false
             */
            win: boolean;
            /** Score */
            score: number | null;
            /** Placement */
            placement: number | null;
            /** Badges */
            badges: components["schemas"]["BadgeOut"][];
        };
        /**
         * PatchChange
         * @description The same champion, role and bracket on the patch before.
         *
         *     Measured on 2026-09-21: of 760 champion and role rows held on both 16.17
         *     and 16.18, the win rate moved 20 points or more on 293, and 2 of those
         *     moves survive a test for chance. So a change is published only where the
         *     two 95% Wilson intervals stop overlapping, and ``*_moved`` says when that
         *     is. Pick rate stands on the whole slice, so 32 of its moves survive.
         */
        PatchChange: {
            /** Patch */
            patch: string;
            /** Games */
            games: number;
            /** Win Rate */
            win_rate: number;
            /** Pick Rate */
            pick_rate: number;
            /**
             * Win Rate Moved
             * @default false
             */
            win_rate_moved: boolean;
            /**
             * Pick Rate Moved
             * @default false
             */
            pick_rate_moved: boolean;
        };
        /**
         * PersonalisationOut
         * @description Whether the list was weighted by a player's mastery, and if not, why.
         *
         *     ``off``: no Riot ID, or the mastery weight is off. ``used``: fresh mastery.
         *     ``stale``: Riot did not answer in time, so the mastery stored from an earlier
         *     lookup was used. ``not_found``: no such account (or a Riot ID that cannot
         *     exist, which is not asked about). ``busy``: Riot did not answer and nothing
         *     is stored. ``no_mastery``: the account has no champion mastery.
         */
        PersonalisationOut: {
            /**
             * Status
             * @enum {string}
             */
            status: "off" | "used" | "stale" | "not_found" | "busy" | "no_mastery";
            /** Riot Id */
            riot_id: string | null;
            /** Platform */
            platform: string | null;
            /**
             * Champions
             * @default 0
             */
            champions: number;
        };
        /** PlatformOptionOut */
        PlatformOptionOut: {
            /** Id */
            id: string;
            /** Label */
            label: string;
        };
        /** PlayStyleTotals */
        PlayStyleTotals: {
            /**
             * Win Rate
             * @default 0
             */
            win_rate: number;
            /**
             * Kda
             * @default 0
             */
            kda: number;
            /**
             * Avg Kills
             * @default 0
             */
            avg_kills: number;
            /**
             * Avg Deaths
             * @default 0
             */
            avg_deaths: number;
            /**
             * Avg Assists
             * @default 0
             */
            avg_assists: number;
            /**
             * Cs Per Min
             * @default 0
             */
            cs_per_min: number;
            /**
             * Vision Per Game
             * @default 0
             */
            vision_per_game: number;
            /**
             * Damage Per Min
             * @default 0
             */
            damage_per_min: number;
        };
        /**
         * PlayedRecordOut
         * @description A player's own record from stored games, always with its size.
         */
        PlayedRecordOut: {
            /** Games */
            games: number;
            /** Wins */
            wins: number;
            /** Losses */
            losses: number;
            /** Win Rate */
            win_rate: number | null;
            /**
             * Scored Games
             * @default 0
             */
            scored_games: number;
            /** Avg Score */
            avg_score: number | null;
            /**
             * Score Enough
             * @default false
             */
            score_enough: boolean;
            /** Last Played */
            last_played: number | null;
            /** First Played */
            first_played: number | null;
        };
        /**
         * PlayerRecordOut
         * @description What Riftline holds about one player in a live lobby.
         *
         *     Withheld rather than zeroed: a player we hold too little for has no record
         *     at all and `stored_games` on the participant says how little. A record full
         *     of zeroes would render as somebody who loses every game.
         *
         *     These are the games **we have crawled**, not their season. The crawler walks
         *     outward from stored matches, so a player in a bracket we crawl has far more
         *     here than one outside it.
         */
        PlayerRecordOut: {
            overall: components["schemas"]["PlayedRecordOut"];
            on_champion: components["schemas"]["PlayedRecordOut"] | null;
            /** Main Position */
            main_position: string | null;
            /**
             * Main Position Games
             * @default 0
             */
            main_position_games: number;
            /**
             * Positioned Games
             * @default 0
             */
            positioned_games: number;
            /** On Main Position */
            on_main_position: boolean | null;
            /**
             * Min Games
             * @default 3
             */
            min_games: number;
            /**
             * Min Games For Win Rate
             * @default 10
             */
            min_games_for_win_rate: number;
        };
        /** PlayerStoryOut */
        PlayerStoryOut: {
            /** Participant Index */
            participant_index: number;
            /** Puuid */
            puuid: string;
            /** Team Id */
            team_id: number;
            /** Riot Id */
            riot_id: string | null;
            champion: components["schemas"]["ChampionRef"];
            /** Position */
            position: string | null;
            /**
             * Deaths
             * @default 0
             */
            deaths: number;
            /**
             * Untraded
             * @default 0
             */
            untraded: number;
            /** Win Lost */
            win_lost: number | null;
            /**
             * Takedowns
             * @default 0
             */
            takedowns: number;
            /**
             * Converted
             * @default 0
             */
            converted: number;
            /** Win Gained */
            win_gained: number | null;
            /**
             * Contests
             * @default 0
             */
            contests: number;
            /**
             * Contests Won
             * @default 0
             */
            contests_won: number;
            /** Death List */
            death_list: components["schemas"]["DeathOut"][];
            /** Takedown List */
            takedown_list: components["schemas"]["TakedownOut"][];
        };
        /** PlayerSuggestion */
        PlayerSuggestion: {
            /** Riot Id */
            riot_id: string;
            /** Game Name */
            game_name: string;
            /** Tag Line */
            tag_line: string;
            /** Platform */
            platform: string;
            /** Platform Label */
            platform_label: string;
            /** Profile Icon Url */
            profile_icon_url: string | null;
            /** Summoner Level */
            summoner_level: number | null;
            /** Tier */
            tier: string | null;
            /** Division */
            division: string | null;
            /** League Points */
            league_points: number | null;
        };
        /**
         * PositionModelOut
         * @description How far an inferred position can be trusted, measured, not asserted.
         */
        PositionModelOut: {
            /** Accuracy */
            accuracy: number;
            /** Players Tested */
            players_tested: number;
            /** Confident At */
            confident_at: number;
        };
        /** PositionShare */
        PositionShare: {
            /** Position */
            position: string;
            /** Games */
            games: number;
            /** Share */
            share: number;
            /** Win Rate */
            win_rate: number;
        };
        /** ProfileResponse */
        ProfileResponse: {
            /** Puuid */
            puuid: string;
            /** Game Name */
            game_name: string | null;
            /** Tag Line */
            tag_line: string | null;
            /** Riot Id */
            riot_id: string;
            /** Platform */
            platform: string;
            /** Platform Label */
            platform_label: string;
            /** Summoner Level */
            summoner_level: number | null;
            /** Profile Icon Url */
            profile_icon_url: string | null;
            /** Ranks */
            ranks: components["schemas"]["RankInfo"][];
            /** Plays On */
            plays_on: string | null;
            /** Plays On Label */
            plays_on_label: string | null;
            /**
             * Identity From Plays On
             * @default false
             */
            identity_from_plays_on: boolean;
            /** Updated At */
            updated_at: number | null;
            ladder: components["schemas"]["LadderPositionOut"] | null;
        };
        /**
         * PublishedComponentOut
         * @description One of the things the score is made of, as the method page lists them.
         */
        PublishedComponentOut: {
            /** Id */
            id: string;
            /** Label */
            label: string;
            /** Measures */
            measures: string;
        };
        /** QueueOptionOut */
        QueueOptionOut: {
            /** Id */
            id: number;
            /** Label */
            label: string;
        };
        /** RankHistoryResponse */
        RankHistoryResponse: {
            /** Queue Type */
            queue_type: string;
            /** Tracking Since */
            tracking_since: number | null;
            /** Points */
            points: components["schemas"]["RankPointOut"][];
        };
        /** RankInfo */
        RankInfo: {
            /** Queue */
            queue: string;
            /** Queue Label */
            queue_label: string;
            /** Tier */
            tier: string | null;
            /** Division */
            division: string | null;
            /**
             * League Points
             * @default 0
             */
            league_points: number;
            /**
             * Wins
             * @default 0
             */
            wins: number;
            /**
             * Losses
             * @default 0
             */
            losses: number;
            /**
             * Win Rate
             * @default 0
             */
            win_rate: number;
            /**
             * Games
             * @default 0
             */
            games: number;
            /**
             * Hot Streak
             * @default false
             */
            hot_streak: boolean;
            /**
             * Inactive
             * @default false
             */
            inactive: boolean;
            /**
             * Numeric Rank
             * @default 0
             */
            numeric_rank: number;
        };
        /** RankPointOut */
        RankPointOut: {
            /** At */
            at: number;
            /** Tier */
            tier: string | null;
            /** Division */
            division: string | null;
            /**
             * League Points
             * @default 0
             */
            league_points: number;
            /**
             * Wins
             * @default 0
             */
            wins: number;
            /**
             * Losses
             * @default 0
             */
            losses: number;
            /**
             * Numeric Rank
             * @default 0
             */
            numeric_rank: number;
        };
        /** RateLimitOut */
        RateLimitOut: {
            /** App */
            app: components["schemas"]["RateWindowOut"][];
            /**
             * Methods Tracked
             * @default 0
             */
            methods_tracked: number;
            /** Penalties */
            penalties: {
                [key: string]: number;
            };
        };
        /** RateWindowOut */
        RateWindowOut: {
            /** Used */
            used: number;
            /** Limit */
            limit: number;
            /** Period */
            period: number;
        };
        /** Rating */
        Rating: {
            /** Key */
            key: string;
            /** Label */
            label: string;
            /** Value */
            value: number;
        };
        /** ReliabilityBinOut */
        ReliabilityBinOut: {
            /** Low */
            low: number;
            /** High */
            high: number;
            /** Predicted */
            predicted: number;
            /** Observed */
            observed: number;
            /** Rows */
            rows: number;
        };
        /** ReviewMethod */
        ReviewMethod: {
            /** Trade Seconds */
            trade_seconds: number;
            /** Trade Kinds */
            trade_kinds: string[];
            /** Convert Kinds */
            convert_kinds: string[];
            /** Min Profile Games */
            min_profile_games: number;
            /** Metrics */
            metrics: components["schemas"]["ReviewMetricMethodOut"][];
            /**
             * Games
             * @default 0
             */
            games: number;
            /**
             * Deaths
             * @default 0
             */
            deaths: number;
            /**
             * Traded
             * @default 0
             */
            traded: number;
            /**
             * Takedowns
             * @default 0
             */
            takedowns: number;
            /**
             * Converted
             * @default 0
             */
            converted: number;
            /**
             * Contests
             * @default 0
             */
            contests: number;
            /**
             * Contests Won
             * @default 0
             */
            contests_won: number;
        };
        /** ReviewMetricMethodOut */
        ReviewMetricMethodOut: {
            /** Id */
            id: string;
            /** Label */
            label: string;
            /** Measures */
            measures: string;
            /** Lower Is Better */
            lower_is_better: boolean;
        };
        /** ReviewMetricOut */
        ReviewMetricOut: {
            /** Metric */
            metric: string;
            /** Label */
            label: string;
            /** Measures */
            measures: string;
            /** Value */
            value: number;
            /** Better Than */
            better_than: number | null;
            /**
             * Lower Is Better
             * @default false
             */
            lower_is_better: boolean;
            /**
             * Games
             * @default 0
             */
            games: number;
        };
        /**
         * RoleClashOut
         * @description An ally who mostly plays the role you are picking for.
         */
        RoleClashOut: {
            champion: components["schemas"]["ChampionRef"];
            /** Share */
            share: number;
        };
        /** RoleGuessOut */
        RoleGuessOut: {
            champion: components["schemas"]["ChampionRef"];
            /** Position */
            position: string;
            /** Probability */
            probability: number;
        };
        /** RoleReviewOut */
        RoleReviewOut: {
            /** Position */
            position: string;
            /** Games */
            games: number;
            /** Min Games */
            min_games: number;
            /** Withheld */
            withheld: string | null;
            /** Metrics */
            metrics: components["schemas"]["ReviewMetricOut"][];
            /**
             * Contests
             * @default 0
             */
            contests: number;
            /**
             * Contests Won
             * @default 0
             */
            contests_won: number;
        };
        /**
         * RoleScoreProfileOut
         * @description What this player's scored games in one role add up to.
         */
        RoleScoreProfileOut: {
            /** Position */
            position: string;
            /** Scored Games */
            scored_games: number;
            /** Enough */
            enough: boolean;
            /** Avg Score */
            avg_score: number;
            /** Avg Placement */
            avg_placement: number;
            /** Mvp */
            mvp: number;
            /** Ace */
            ace: number;
            /** Components */
            components: components["schemas"]["ComponentAverageOut"][];
            /** Sample */
            sample: number | null;
            /** Min Scored */
            min_scored: number;
        };
        /** RoleShare */
        RoleShare: {
            /** Position */
            position: string;
            /** Games */
            games: number;
            /** Share */
            share: number;
            /** Win Rate */
            win_rate: number;
        };
        /** RuneRef */
        RuneRef: {
            /** Id */
            id: number | null;
            /** Name */
            name: string | null;
            /** Icon Url */
            icon_url: string | null;
        };
        /** RuneSection */
        RuneSection: {
            /** Keystones */
            keystones: components["schemas"]["FacetEntry"][];
            /** Pages */
            pages: components["schemas"]["FacetEntry"][];
        };
        /**
         * SameTeamPairOut
         * @description Two players in this lobby who keep appearing on the same side.
         *
         *     Not called a duo, here or anywhere else on the wire. Two players in the same
         *     small ranked pool meet constantly without ever pressing invite, so this is a
         *     pattern in stored games and nothing more. Nothing is persisted: the pairing
         *     is computed per request and lives in this response.
         */
        SameTeamPairOut: {
            /** Puuid A */
            puuid_a: string;
            /** Puuid B */
            puuid_b: string;
            /** Games */
            games: number;
            /** Wins */
            wins: number;
            /** Last Played */
            last_played: number | null;
            /**
             * Basis
             * @default stored_matches
             */
            basis: string;
        };
        /**
         * ScoreAuditOut
         * @description The nightly audit of the score against wins, as `scripts.ingest audit`
         *     stores it. Typed here rather than passed through as a dict, so the page
         *     that reads it compiles against the same shape.
         */
        ScoreAuditOut: {
            /** Weights Version */
            weights_version: number;
            /** Queue Id */
            queue_id: number;
            /** Games */
            games: number;
            /** Players */
            players: number;
            overall: components["schemas"]["AuditOverallOut"];
            /** Roles */
            roles: components["schemas"]["AuditRoleOut"][];
        };
        /**
         * ScoreComponentOut
         * @description One of the seven things the Riftline score is made of.
         */
        ScoreComponentOut: {
            /** Id */
            id: string;
            /** Label */
            label: string;
            /** Measures */
            measures: string;
            /** Percentile */
            percentile: number;
            /** Weight */
            weight: number;
        };
        /** ScoreMethod */
        ScoreMethod: {
            /** Version */
            version: number;
            /** Components */
            components: components["schemas"]["PublishedComponentOut"][];
            /** Weights */
            weights: {
                [key: string]: {
                    [key: string]: number;
                };
            };
            /** Min Games */
            min_games: number;
            audit: components["schemas"]["ScoreAuditOut"] | null;
            /** Audited At */
            audited_at: string | null;
        };
        /**
         * ScoreModelOut
         * @description How the Riftline score is computed, published with every scoreboard.
         *
         *     itero exposes its draft model and it is the most trustworthy thing on their
         *     site. A rating that cannot be taken apart is a rating that has to be taken
         *     on faith, which is the opposite of what this whole project is for.
         */
        ScoreModelOut: {
            /** Version */
            version: number;
            /** Components */
            components: components["schemas"]["PublishedComponentOut"][];
            /** Weights */
            weights: {
                [key: string]: {
                    [key: string]: number;
                };
            };
            /** Samples */
            samples: {
                [key: string]: number;
            };
            /** Note */
            note: string;
        };
        /**
         * ScoreboardPlayer
         * @description One player on the expanded scoreboard.
         *
         *     Everything the row cannot fit. Served from its own endpoint rather than in
         *     the history payload: twenty matches times ten players times this many fields
         *     is a page nobody asked for on every scroll.
         */
        ScoreboardPlayer: {
            /** Puuid */
            puuid: string;
            /** Riot Id */
            riot_id: string | null;
            champion: components["schemas"]["ChampionRef"];
            /** Team Id */
            team_id: number;
            /** Position */
            position: string | null;
            /**
             * Win
             * @default false
             */
            win: boolean;
            /**
             * Champ Level
             * @default 0
             */
            champ_level: number;
            /** Laning Score */
            laning_score: number | null;
            /** Laning Label */
            laning_label: ("won_big" | "won" | "even" | "lost" | "lost_big") | null;
            /**
             * Kills
             * @default 0
             */
            kills: number;
            /**
             * Deaths
             * @default 0
             */
            deaths: number;
            /**
             * Assists
             * @default 0
             */
            assists: number;
            /**
             * Kill Participation
             * @default 0
             */
            kill_participation: number;
            /**
             * Cs
             * @default 0
             */
            cs: number;
            /**
             * Cs Per Min
             * @default 0
             */
            cs_per_min: number;
            /**
             * Gold Earned
             * @default 0
             */
            gold_earned: number;
            /**
             * Damage To Champions
             * @default 0
             */
            damage_to_champions: number;
            /**
             * Damage Taken
             * @default 0
             */
            damage_taken: number;
            /**
             * Vision Score
             * @default 0
             */
            vision_score: number;
            /** Wards Placed */
            wards_placed: number | null;
            /** Wards Killed */
            wards_killed: number | null;
            /** Control Wards */
            control_wards: number | null;
            /** Items */
            items: components["schemas"]["ItemRef"][];
            trinket: components["schemas"]["ItemRef"] | null;
            /** Spells */
            spells: components["schemas"]["SpellRef"][];
            keystone: components["schemas"]["RuneRef"] | null;
            /** Score */
            score: number | null;
            /** Placement */
            placement: number | null;
            /** Badges */
            badges: components["schemas"]["BadgeOut"][];
        };
        /**
         * SharedGamesOut
         * @description Earlier stored games a player and the searched player were both in.
         *
         *     Counts only, at every sample size. These are single digit numbers, so a
         *     percentage here would be a figure nobody should quote back. The wins are
         *     always the searched player's.
         *
         *     `basis` is "stored_matches" and it matters: the crawler walks outward from
         *     matches it already holds, so the people we hold games of are exactly the
         *     people who appear together in them. These figures are an upper bound on what
         *     a lobby outside the crawled bracket would show.
         */
        SharedGamesOut: {
            /** Games */
            games: number;
            /** Same Side */
            same_side: number;
            /** Same Side Wins */
            same_side_wins: number;
            /** Opposite Side */
            opposite_side: number;
            /** Opposite Side Wins */
            opposite_side_wins: number;
            /** Last Played */
            last_played: number | null;
            /**
             * Basis
             * @default stored_matches
             */
            basis: string;
        };
        /**
         * SideReadOut
         * @description One side of a live lobby, summed from what the lobby already shows.
         */
        SideReadOut: {
            /** Team Id */
            team_id: number;
            /** Median Points */
            median_points: number | null;
            /** Tier */
            tier: string | null;
            /** Division */
            division: string | null;
            /** League Points */
            league_points: number | null;
            /**
             * Ranked
             * @default 0
             */
            ranked: number;
            /**
             * Unranked
             * @default 0
             */
            unranked: number;
            /**
             * Hidden
             * @default 0
             */
            hidden: number;
            /**
             * Bots
             * @default 0
             */
            bots: number;
            /**
             * Unknown
             * @default 0
             */
            unknown: number;
            /** Tier Gap */
            tier_gap: number | null;
            /** Points Gap */
            points_gap: number | null;
            /**
             * Gap Basis
             * @default withheld
             */
            gap_basis: string;
            /**
             * Lanes Favoured
             * @default 0
             */
            lanes_favoured: number;
            /**
             * Off Champion
             * @default 0
             */
            off_champion: number;
            /**
             * Off Champion Known
             * @default 0
             */
            off_champion_known: number;
            /**
             * Off Role
             * @default 0
             */
            off_role: number;
            /**
             * Off Role Known
             * @default 0
             */
            off_role_known: number;
        };
        /** SkillSection */
        SkillSection: {
            /** Priority */
            priority: components["schemas"]["FacetEntry"][];
            /** Order */
            order: components["schemas"]["FacetEntry"][];
            /** First */
            first: components["schemas"]["FacetEntry"][];
        };
        /** SkinOut */
        SkinOut: {
            /** Id */
            id: number;
            /** Num */
            num: number;
            /** Name */
            name: string;
            /** Rarity */
            rarity: string | null;
            /**
             * Legacy
             * @default false
             */
            legacy: boolean;
            /** Line */
            line: string | null;
            /** Description */
            description: string | null;
            /**
             * Chromas
             * @default 0
             */
            chromas: number;
            /** Tile Url */
            tile_url: string | null;
            /** Splash Url */
            splash_url: string | null;
            /** Sightings */
            sightings: number | null;
        };
        /** SpellRef */
        SpellRef: {
            /** Id */
            id: number | null;
            /** Name */
            name: string | null;
            /** Icon Url */
            icon_url: string | null;
        };
        /** StatLine */
        StatLine: {
            /** Value */
            value: string;
            /** Label */
            label: string;
        };
        /** StoryModelOut */
        StoryModelOut: {
            /** Version */
            version: number;
            /** Published */
            published: boolean;
            /** Withheld */
            withheld: string | null;
            /**
             * Trained Games
             * @default 0
             */
            trained_games: number;
            /**
             * Trained Queue
             * @default 420
             */
            trained_queue: number;
            /** Accuracy */
            accuracy: number | null;
            /** Phases */
            phases: components["schemas"]["StoryPhaseOut"][];
        };
        /** StoryPhaseOut */
        StoryPhaseOut: {
            /** Label */
            label: string;
            /** Accuracy */
            accuracy: number;
        };
        /** StoryPlayerRef */
        StoryPlayerRef: {
            /** Participant Index */
            participant_index: number;
            champion: components["schemas"]["ChampionRef"];
        };
        /** SuggestResponse */
        SuggestResponse: {
            /** Query */
            query: string;
            /** Players */
            players: components["schemas"]["PlayerSuggestion"][];
        };
        /**
         * SuggestionDamageOut
         * @description A pick's own damage in the role, and your team's mix with it added.
         */
        SuggestionDamageOut: {
            own: components["schemas"]["DamageShareOut"];
            /** Games */
            games: number;
            team_after: components["schemas"]["DamageShareOut"] | null;
            /** Balances */
            balances: ("physical" | "magic" | "true") | null;
        };
        /** SuggestionOut */
        SuggestionOut: {
            champion: components["schemas"]["ChampionRef"];
            /** Games */
            games: number;
            /** Wins */
            wins: number;
            /** Win Rate */
            win_rate: number;
            /** Range Low */
            range_low: number;
            /** Range High */
            range_high: number;
            /** Expected */
            expected: number;
            /** Rank Score */
            rank_score: number;
            /**
             * Context Lift
             * @default 0
             */
            context_lift: number;
            /**
             * Mastery Points
             * @default 0
             */
            mastery_points: number;
            /** Last Played Days */
            last_played_days: number | null;
            /**
             * Comfort
             * @default 0
             */
            comfort: number;
            /**
             * Comfort Bonus
             * @default 0
             */
            comfort_bonus: number;
            /** Evidence */
            evidence: components["schemas"]["EvidenceOut"][];
            /** Reasons */
            reasons: string[];
            /** Rank */
            rank: number | null;
            /**
             * Below Min
             * @default false
             */
            below_min: boolean;
            /** Blind Risks */
            blind_risks: components["schemas"]["EvidenceOut"][];
            laning: components["schemas"]["LaningOut"] | null;
            damage: components["schemas"]["SuggestionDamageOut"] | null;
            /**
             * Score
             * @default 0
             */
            score: number;
            /**
             * Base Win Rate
             * @default 0
             */
            base_win_rate: number;
            /**
             * Adjusted Win Rate
             * @default 0
             */
            adjusted_win_rate: number;
            /** Matchup Win Rate */
            matchup_win_rate: number | null;
            /**
             * Matchup Games
             * @default 0
             */
            matchup_games: number;
        };
        /** TakedownOut */
        TakedownOut: {
            /** Ms */
            ms: number;
            victim: components["schemas"]["StoryPlayerRef"] | null;
            /** Killed */
            killed: boolean;
            /** Converted */
            converted: boolean;
            /** Gain */
            gain: number | null;
        };
        /** TeamDamageOut */
        TeamDamageOut: {
            /** Available */
            available: boolean;
            allies: components["schemas"]["DamageMixOut"] | null;
            enemies: components["schemas"]["DamageMixOut"] | null;
            /** Min Games */
            min_games: number;
            /** One Sided Share */
            one_sided_share: number;
        };
        /**
         * TeamObjectives
         * @description What one side did. Kills and gold are summed from its own players.
         *
         *     `objectives_known` is false when Riot's team objects do not line up with the
         *     sides on the scoreboard, which is the case in Arena. Then the structure and
         *     monster counts below are all zero because they are unknown, not because
         *     nothing was taken, and the UI omits them.
         */
        TeamObjectives: {
            /** Team Id */
            team_id: number;
            /**
             * Win
             * @default false
             */
            win: boolean;
            /**
             * Kills
             * @default 0
             */
            kills: number;
            /**
             * Gold
             * @default 0
             */
            gold: number;
            /**
             * Objectives Known
             * @default true
             */
            objectives_known: boolean;
            /**
             * Baron
             * @default 0
             */
            baron: number;
            /**
             * Dragon
             * @default 0
             */
            dragon: number;
            /**
             * Herald
             * @default 0
             */
            herald: number;
            /**
             * Tower
             * @default 0
             */
            tower: number;
            /**
             * Inhibitor
             * @default 0
             */
            inhibitor: number;
            /** Bans */
            bans: components["schemas"]["ChampionRef"][];
        };
        /**
         * TierListChampion
         * @description A champion in the tier list, carrying square key art.
         *
         *     Kept off the base ``ChampionRef`` on purpose: that type appears ten times
         *     per match row, so putting art on it would add two hundred unused URLs to
         *     every page of match history.
         */
        TierListChampion: {
            /** Id */
            id: number;
            /** Name */
            name: string;
            /** Icon Url */
            icon_url: string | null;
            /** Tile Url */
            tile_url: string | null;
            /** Slug */
            readonly slug: string | null;
        };
        /** TogetherGameOut */
        TogetherGameOut: {
            /** Match Id */
            match_id: string;
            /** Queue Id */
            queue_id: number;
            /** Queue Name */
            queue_name: string;
            /** Game Creation */
            game_creation: number;
            /** Game Duration */
            game_duration: number;
            /** Win */
            win: boolean;
            /** Players */
            players: components["schemas"]["TogetherPlayerOut"][];
        };
        /** TogetherPlayerOut */
        TogetherPlayerOut: {
            /** Puuid */
            puuid: string;
            champion: components["schemas"]["ChampionRef"];
            /** Position */
            position: string | null;
            /** Kills */
            kills: number;
            /** Deaths */
            deaths: number;
            /** Assists */
            assists: number;
        };
        /** TopSkin */
        TopSkin: {
            champion: components["schemas"]["ChampionRef"];
            /** Num */
            num: number;
            /** Name */
            name: string;
            /** Tile Url */
            tile_url: string | null;
            /** Sightings */
            sightings: number;
            /** Champion Sightings */
            champion_sightings: number;
        };
        /** TopSkins */
        TopSkins: {
            /**
             * Total
             * @default 0
             */
            total: number;
            /**
             * Min Sightings
             * @default 5
             */
            min_sightings: number;
            /**
             * Min Skins
             * @default 3
             */
            min_skins: number;
            /** Skins */
            skins: components["schemas"]["TopSkin"][];
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /** WinEffectOut */
        WinEffectOut: {
            /** Feature */
            feature: string;
            /** Label */
            label: string;
            /** Unit */
            unit: string;
            /** Points */
            points: {
                [key: string]: number | null;
            };
        };
        /** WinFeatureOut */
        WinFeatureOut: {
            /** Id */
            id: string;
            /** Label */
            label: string;
            /** Unit */
            unit: string;
        };
        /** WinGateOut */
        WinGateOut: {
            /** Min Games */
            min_games: number | null;
            /** Min Skill */
            min_skill: number | null;
            /** Max Ece */
            max_ece: number | null;
        };
        /** WinModelMethod */
        WinModelMethod: {
            /** Version */
            version: number;
            /** Published */
            published: boolean;
            /** Withheld */
            withheld: string | null;
            /**
             * Trained Games
             * @default 0
             */
            trained_games: number;
            /**
             * Trained Rows
             * @default 0
             */
            trained_rows: number;
            /** Patches */
            patches: string[];
            /** Queue Id */
            queue_id: number;
            /** Applies To */
            applies_to: number[];
            /** Features */
            features: components["schemas"]["WinFeatureOut"][];
            /** Effects */
            effects: components["schemas"]["WinEffectOut"][];
            cv: components["schemas"]["CrossValidationOut"];
            gate: components["schemas"]["WinGateOut"];
            /** Trained At */
            trained_at: string | null;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    get_profile_api_summoner__platform___game_name___tag_line__get: {
        parameters: {
            query?: {
                /** @description Re-fetch from Riot, once the cached answer is at least a minute old. */
                refresh?: boolean;
                /** @description live (default) asks Riot where the cache is stale; stored reads storage only. */
                source?: string;
            };
            header?: never;
            path: {
                platform: string;
                game_name: string;
                tag_line: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProfileResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_rank_history_api_summoner__platform___game_name___tag_line__rank_history_get: {
        parameters: {
            query?: {
                /** @description RANKED_SOLO_5x5 or RANKED_FLEX_SR. */
                queue?: string;
            };
            header?: never;
            path: {
                platform: string;
                game_name: string;
                tag_line: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RankHistoryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_matches_api_summoner__platform___game_name___tag_line__matches_get: {
        parameters: {
            query?: {
                start?: number;
                count?: number;
                /** @description Riot queue id, e.g. 420 for Solo/Duo. */
                queue?: number | null;
                /** @description Champion id. Read from stored games: Riot cannot filter by it. */
                champion?: number | null;
                /** @description live (default) asks Riot where the cache is stale; stored reads storage only. */
                source?: string;
            };
            header?: never;
            path: {
                platform: string;
                game_name: string;
                tag_line: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MatchHistoryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_mastery_api_summoner__platform___game_name___tag_line__mastery_get: {
        parameters: {
            query?: {
                refresh?: boolean;
            };
            header?: never;
            path: {
                platform: string;
                game_name: string;
                tag_line: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MasteryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_analytics_api_summoner__platform___game_name___tag_line__analytics_get: {
        parameters: {
            query?: {
                /** @description Riot queue id, e.g. 420. */
                queue?: number | null;
                /** @description Stored games to analyse. */
                limit?: number;
                /** @description live (default) asks Riot where the cache is stale; stored reads storage only. */
                source?: string;
            };
            header?: never;
            path: {
                platform: string;
                game_name: string;
                tag_line: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AnalyticsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_live_game_api_summoner__platform___game_name___tag_line__live_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                platform: string;
                game_name: string;
                tag_line: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LiveGameResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_live_result_api_summoner__platform___game_name___tag_line__live_result__match_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                platform: string;
                game_name: string;
                tag_line: string;
                match_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MatchResolveResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_version_api_static_version_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    get_champions_api_static_champions_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    get_queues_api_static_queues_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    get_corpus_api_meta_corpus_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CorpusResponse"];
                };
            };
        };
    };
    get_champion_meta_api_meta_champions_get: {
        parameters: {
            query?: {
                /** @description Defaults to the newest patch held. */
                patch?: string | null;
                queue_id?: number;
                /** @description TOP, JUNGLE, MIDDLE, BOTTOM or UTILITY. */
                position?: string | null;
                /** @description Crawl provenance, e.g. CHALLENGER. Not a measured lobby rank. */
                bracket?: string;
                /** @description Drop champions below this sample size. */
                min_games?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetaResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_pages_api_meta_pages_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PagesResponse"];
                };
            };
        };
    };
    get_method_api_method_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MethodResponse"];
                };
            };
        };
    };
    get_champion_index_api_champions_get: {
        parameters: {
            query?: {
                queue_id?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChampionIndex"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_champion_api_champions__champion__get: {
        parameters: {
            query?: {
                /** @description Defaults to the newest patch held. */
                patch?: string | null;
                queue_id?: number;
                /** @description Defaults to the champion's main role. */
                position?: string | null;
                /** @description Crawl provenance, not a measured rank. */
                bracket?: string;
                min_games?: number;
            };
            header?: never;
            path: {
                champion: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChampionDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_champion_profile_api_champions__champion_ref__profile_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                champion_ref: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChampionProfile"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_champion_players_api_champions__champion__players_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                champion: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChampionPlayers"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    suggest_api_draft_suggest_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DraftRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DraftResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_slices_api_leaderboard_slices_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LeaderboardSlices"];
                };
            };
        };
    };
    get_leaderboard_api_leaderboard__platform__get: {
        parameters: {
            query?: {
                /** @description 420 solo/duo, 440 flex. */
                queue_id?: number;
                tier?: string;
                /** @description Ignored for the apex tiers. */
                division?: string;
                page?: number;
                per_page?: number;
            };
            header?: never;
            path: {
                platform: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LeaderboardResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_match_api_matches__match_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Riot match id, which carries its own platform: EUW1_7986353741. */
                match_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MatchDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_story_api_matches__match_id__story_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Riot match id, which carries its own platform: EUW1_7986353741. */
                match_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GameStoryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    suggest_players_api_players_suggest_get: {
        parameters: {
            query?: {
                /** @description Name, or Name#TAG with a partial tag. */
                q?: string;
                /** @description Region to rank first, e.g. euw1. */
                platform?: string | null;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SuggestResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_best_games_api_highlights_best_games_get: {
        parameters: {
            query?: {
                days?: number;
                queue_id?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BestGamesResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_top_skins_api_skins_top_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TopSkins"];
                };
            };
        };
    };
    list_items_api_items_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ItemList"];
                };
            };
        };
    };
    get_item_api_items__item__get: {
        parameters: {
            query?: {
                /** @description Defaults to the newest patch held. */
                patch?: string | null;
                queue_id?: number;
                /** @description Crawl provenance, not a measured rank. */
                bracket?: string;
            };
            header?: never;
            path: {
                item: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ItemDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_api_groups_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GroupCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GroupCreatedResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_group_api_groups__slug__get: {
        parameters: {
            query?: {
                /** @description all, solo, flex, normal, swiftplay, aram, arena */
                queue?: string;
            };
            header?: {
                "X-Group-Key"?: string | null;
            };
            path: {
                slug: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GroupResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_api_groups__slug__delete: {
        parameters: {
            query?: never;
            header?: {
                "X-Group-Key"?: string | null;
            };
            path: {
                slug: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    rename_api_groups__slug__patch: {
        parameters: {
            query?: never;
            header?: {
                "X-Group-Key"?: string | null;
            };
            path: {
                slug: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GroupRenameRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    warm_api_groups__slug__warm_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                slug: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GroupWarmResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    new_edit_key_api_groups__slug__key_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Group-Key"?: string | null;
            };
            path: {
                slug: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GroupKeyResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_api_groups__slug__members_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Group-Key"?: string | null;
            };
            path: {
                slug: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GroupMemberAddRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GroupMemberAddedResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    remove_api_groups__slug__members__puuid__delete: {
        parameters: {
            query?: never;
            header?: {
                "X-Group-Key"?: string | null;
            };
            path: {
                slug: string;
                puuid: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    label_api_groups__slug__members__puuid__patch: {
        parameters: {
            query?: never;
            header?: {
                "X-Group-Key"?: string | null;
            };
            path: {
                slug: string;
                puuid: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GroupMemberLabelRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_api_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
        };
    };
}
