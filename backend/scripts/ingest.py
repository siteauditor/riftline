"""Ingestion CLI.

    python -m scripts.ingest status
    python -m scripts.ingest crawl --target 500 --tier challenger
    python -m scripts.ingest timelines --target 500
    python -m scripts.ingest lobbyranks --target 2000
    python -m scripts.ingest ladders --platform euw1
    python -m scripts.ingest score
    python -m scripts.ingest aggregate
    python -m scripts.ingest aggregate --patch 15.18 --queue 420
    python -m scripts.ingest reextract
    python -m scripts.ingest winmodel
    python -m scripts.ingest reviews
    python -m scripts.ingest audit
    python -m scripts.ingest groups --calls 2000
    python -m scripts.ingest homes --dry-run
    python -m scripts.ingest names --players 300

``crawl`` is resumable: stop it whenever and it picks the frontier back up. On a
development key expect roughly 3,000 matches an hour, and remember the key
itself expires after 24.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.config import get_settings
from app.db.base import SessionLocal, init_db
from app.riot.client import RiotClient
from app.riot.errors import RiotUnauthorized
from app.riot.limiter import RateLimiter
from app.services.aggregate import (
    ALL_BRACKETS,
    available_brackets,
    available_slices,
    rebuild_champion_stats,
    rebuild_facet_stats,
    rebuild_item_stats,
    rebuild_matchup_stats,
    rebuild_synergy_stats,
)
from app.services.audit import store_audit
from app.services.groups import delete_empty_groups, warm_all_groups
from app.services.homes import repair_homes
from app.services.ingest import (
    Ingestor,
    LobbyRankBackfill,
    TimelineBackfill,
    corpus_summary,
)
from app.services.ladders import APEX_TIERS as LADDER_APEX_TIERS
from app.services.ladders import DIVISIONS as LADDER_DIVISIONS
from app.services.ladders import LadderService
from app.services.lanes import rebuild_lane_distributions
from app.services.names import confirm_names
from app.services.reviews import rebuild_reviews
from app.services.scores import ScoreService
from app.services.static_data import static_data
from app.services.timelines import EXTRACT_VERSION, backfill_buy_times, backfill_extracts
from app.services.winchance import train as train_win_model

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ingest")


def make_client(settings) -> RiotClient:
    return RiotClient(
        settings.riot_api_key,
        limiter=RateLimiter(settings.parsed_rate_limits),
        timeout=settings.riot_timeout_seconds,
        max_retries=settings.riot_max_retries,
    )


async def cmd_status() -> int:
    await init_db()
    async with SessionLocal() as session:
        summary = await corpus_summary(session)

    print(f"\nMatches stored:      {summary['matches']:,}")
    print(f"Participant rows:    {summary['participants']:,}")

    held, left = summary["timelines"], summary["timelines_outstanding"]
    # One decimal, because rounding 99.6% to "100%" beside "6 have no timeline"
    # reads as a contradiction.
    share = ""
    if held + left:
        pct = held / (held + left) * 100
        share = "  (100% of matches)" if not left else f"  ({pct:.1f}% of matches)"
    print(f"Timelines stored:    {held:,}{share}")
    if left:
        print(
            f"  {left:,} match(es) have no timeline, so their laning scores, skill\n"
            "  order and build paths are blank. Run: python -m scripts.ingest timelines"
        )

    scores = summary["scores"]
    if scores["participants"]:
        print(
            f"Riftline scores:     {scores['scored']:,}"
            f"  ({scores['percent']:.1f}% of participants)"
        )
        if scores["withheld_matches"]:
            print(
                f"  {scores['withheld_matches']:,} lobby(ies) withheld: not ten"
                " players with lane roles, a remake, or a queue the corpus"
                " cannot carry"
            )
        if not scores["distributions"]:
            print("  no distributions measured yet. Run: python -m scripts.ingest score")

    if not summary["slices"]:
        print("\nNothing ingested yet. Run: python -m scripts.ingest crawl\n")
        return 0

    print("\nBy patch and queue:")
    print(f"  {'patch':<10} {'queue':<8} {'matches':>10}")
    for s in summary["slices"][:20]:
        print(f"  {s['patch'] or '?':<10} {s['queue_id']:<8} {s['matches']:>10,}")
    print()
    return 0


async def cmd_crawl(args) -> int:
    settings = get_settings()
    if not settings.has_key:
        log.error("RIOT_API_KEY is not set. Put your key in backend/.env first.")
        return 2

    await init_db()
    await static_data.ensure_loaded()

    client = make_client(settings)
    try:
        async with SessionLocal() as session:
            ingestor = Ingestor(
                session,
                client,
                settings,
                platform=args.platform,
                queue=args.queue,
                seed_tier=args.tier,
            )
            log.info(
                "crawling %s queue %s, target %d new matches (Ctrl-C to stop; progress is saved)",
                args.platform, args.queue, args.target,
            )
            try:
                await ingestor.crawl(
                    target_matches=args.target,
                    matches_per_player=args.per_player,
                    seed_tier=args.tier,
                )
            except KeyboardInterrupt:
                log.info("interrupted: %s", ingestor.stats.line())
    except RiotUnauthorized as exc:
        log.error("%s", exc.message)
        return 2
    finally:
        await client.aclose()
    return 0


async def cmd_timelines(args) -> int:
    settings = get_settings()
    if not settings.has_key:
        log.error("RIOT_API_KEY is not set. Put your key in backend/.env first.")
        return 2

    await init_db()
    client = make_client(settings)
    try:
        async with SessionLocal() as session:
            backfill = TimelineBackfill(session, client, settings)
            log.info(
                "fetching up to %d timelines (Ctrl-C to stop; progress is the data itself)",
                args.target,
            )
            try:
                await backfill.run(target=args.target, batch=args.batch, patch=args.patch)
            except KeyboardInterrupt:
                log.info("interrupted: %s", backfill.stats.line())
            left = await backfill.remaining(args.patch)
            print()
            print(
                f"{backfill.stats.matches_new} timelines stored, "
                f"{left:,} still outstanding"
            )
            if backfill.stats.matches_new:
                print("run `python -m scripts.ingest aggregate` to fold them into the rollups")
    except RiotUnauthorized as exc:
        log.error("%s", exc.message)
        return 2
    finally:
        await client.aclose()
    return 0


async def cmd_lobby_ranks(args) -> int:
    settings = get_settings()
    if not settings.has_key:
        log.error("RIOT_API_KEY is not set. Put your key in backend/.env first.")
        return 2

    await init_db()
    client = make_client(settings)
    try:
        async with SessionLocal() as session:
            backfill = LobbyRankBackfill(session, client, settings)
            log.info(
                "measuring up to %d lobbies (Ctrl-C to stop; progress is the data itself)",
                args.target,
            )
            try:
                await backfill.run(target=args.target, batch=args.batch, patch=args.patch)
            except KeyboardInterrupt:
                log.info("interrupted: %s", backfill.stats.line())
            left = await backfill.remaining(args.patch)
            print()
            print(
                f"{backfill.stats.matches_new} lobbies measured, "
                f"{left:,} still outstanding"
            )
            print(
                "note: this is every player's rank TODAY, not their rank on the "
                "day they played. Riot exposes no historical rank, so the "
                "measurement date is stored alongside and shown in the UI."
            )
    except RiotUnauthorized as exc:
        log.error("%s", exc.message)
        return 2
    finally:
        await client.aclose()
    return 0


async def cmd_ladders(args) -> int:
    settings = get_settings()
    if not settings.has_key:
        log.error("RIOT_API_KEY is not set. Put your key in backend/.env first.")
        return 2

    await init_db()
    client = make_client(settings)
    tiers = (
        [t.upper() for t in args.tier.split(",")]
        if args.tier != "apex"
        else list(LADDER_APEX_TIERS)
    )
    try:
        async with SessionLocal() as session:
            service = LadderService(session, client, settings)
            total = 0
            for tier in tiers:
                divisions = ["I"] if tier in LADDER_APEX_TIERS else list(LADDER_DIVISIONS)
                for division in divisions:
                    stored = await service.refresh(
                        args.platform, queue_id=args.queue, tier=tier,
                        division=division, pages=args.pages,
                    )
                    total += stored
            print()
            print(f"{total:,} ladder rows stored for {args.platform}")
            print(
                "names fill in as pages are viewed, and a resolved name is kept, "
                "so a ladder gets cheaper the more it is used"
            )
    except RiotUnauthorized as exc:
        log.error("%s", exc.message)
        return 2
    finally:
        await client.aclose()
    return 0


async def cmd_aggregate(args) -> int:
    await init_db()
    await static_data.ensure_loaded()

    async with SessionLocal() as session:
        slices = await available_slices(session)
        if not slices:
            log.error("No matches to aggregate. Run `crawl` first.")
            return 1

        targets = [
            s
            for s in slices
            if (args.patch is None or s["patch"] == args.patch)
            and (args.queue is None or s["queue_id"] == args.queue)
        ]
        if not targets:
            log.error("No data for patch=%s queue=%s", args.patch, args.queue)
            return 1

        # "ALL" plus each crawl provenance we hold, so the UI can offer a
        # bracket filter. On a single-bracket corpus the two are identical and
        # that is fine; it costs one extra pass and keeps the shape uniform.
        brackets = [ALL_BRACKETS] if args.bracket == ALL_BRACKETS else [args.bracket]
        if args.bracket is None:
            brackets = await available_brackets(session)

        for s in targets:
            if s["matches"] < args.min_matches:
                log.info(
                    "skipping patch %s queue %s: only %d matches (need %d)",
                    s["patch"], s["queue_id"], s["matches"], args.min_matches,
                )
                continue
            for bracket in brackets:
                slice_kwargs = {
                    "patch": s["patch"],
                    "queue_id": s["queue_id"],
                    "rank_bracket": bracket,
                }
                champions = await rebuild_champion_stats(session, **slice_kwargs)
                if not champions:
                    continue
                matchups = await rebuild_matchup_stats(
                    session, **slice_kwargs, min_games=args.min_pair_games
                )
                synergies = await rebuild_synergy_stats(
                    session, **slice_kwargs, min_games=args.min_pair_games
                )
                facets = await rebuild_facet_stats(
                    session, **slice_kwargs, min_games=args.min_facet_games
                )
                items = await rebuild_item_stats(session, **slice_kwargs)
                print(
                    f"patch {s['patch']} queue {s['queue_id']} [{bracket}]: "
                    f"{champions} champion, {matchups} matchup, "
                    f"{synergies} synergy, {facets} facet, {items} item rows "
                    f"from {s['matches']:,} matches"
                )
    return 0


async def cmd_score(args) -> int:
    """Lift the unmapped Riot fields, measure the corpus, score every lobby.

    The only ingest command that makes no Riot request. Everything it reads is
    already on disk in `matches.raw`, so there is no key to check, no limiter to
    respect and no reason to pace it.
    """
    await init_db()

    async with SessionLocal() as session:
        service = ScoreService(session)

        outstanding = await service.lift_remaining()
        if outstanding:
            log.info("lifting %d participant rows out of stored payloads", outstanding)
            await service.lift_fields()

        if args.rebuild_distributions or not await service.has_distributions():
            await service.rebuild_distributions()

        if args.rescore:
            cleared = await service.rescore_stale()
            if cleared:
                print(f"{cleared:,} scores cleared: they were computed under older weights")

        left = await service.unscored()
        log.info("lobbies to score: %d", left)
        try:
            await service.score_matches(target=args.target)
        except KeyboardInterrupt:
            log.info("interrupted: %s", service.stats.line())

        print()
        print(service.stats.line())
        coverage = await service.coverage()
        print(
            f"{coverage['scored']:,} of {coverage['participants']:,} participants scored "
            f"({coverage['percent']:.1f}%), {coverage['distributions']} distributions"
        )
        # The lane labels measure the corpus the same way the score does, so
        # they are rebuilt with it: every run, from storage, in a second.
        lanes = await rebuild_lane_distributions(session)
        print(f"lane labels: {lanes} role distributions")
        if coverage["withheld_matches"]:
            print(
                f"{coverage['withheld_matches']:,} lobbies withheld: not ten players "
                "with lane roles, a remake, or a queue our corpus cannot carry"
            )
    return 0


async def cmd_buy_times(args) -> int:
    """Fill purchase times for timelines stored before they were recorded.

    Reads the raw timelines already on disk, so like `score` it makes no Riot
    request and needs no key.
    """
    await init_db()
    async with SessionLocal() as session:
        stats = await backfill_buy_times(session)
    print(f"purchase times filled for {stats.filled:,} players in {stats.matches:,} matches")
    if stats.mismatched:
        print(
            f"{stats.mismatched:,} left without times: their stored purchase order no "
            "longer matches a replay of the timeline"
        )
    return 0


async def cmd_reextract(args) -> int:
    """Bring stored timeline extracts up to the current version.

    Reads `raw_gz`, so like `score` it makes no Riot request and needs no key.
    """
    await init_db()
    async with SessionLocal() as session:
        stats = await backfill_extracts(session)
    print(f"{stats.rows:,} timelines re-extracted to version {EXTRACT_VERSION}")
    if stats.skipped:
        print(f"{stats.skipped:,} skipped: their stored payload has no frames")
    return 0


async def cmd_win_model(args) -> int:
    """Fit and grade the win-chance model on stored timelines. No Riot call."""
    await init_db()
    async with SessionLocal() as session:
        row = await train_win_model(session)
    payload = row.payload
    cv = payload.get("cv") or {}
    overall = cv.get("overall")
    print(f"win model v{row.version}: {payload['trained_games']:,} games, "
          f"{payload['trained_rows']:,} game-minutes")
    if overall:
        print(f"held out: accuracy {overall['accuracy']:.3f}, Brier {overall['brier']:.4f} "
              f"against {overall['baseline_brier']:.4f} guessing, skill {overall['skill']:.3f}, "
              f"calibration error {cv['ece'] * 100:.1f} points")
        for phase in cv["phases"]:
            print(f"  {phase['label']:>8} min: accuracy {phase['accuracy']:.3f}, "
                  f"Brier {phase['brier']:.4f}, {phase['rows']:,} rows")
    print("published" if payload["published"] else f"withheld: {payload['withheld']}")
    return 0


async def cmd_reviews(args) -> int:
    """Weigh every stored game's deaths and takedowns. No Riot call."""
    await init_db()
    async with SessionLocal() as session:
        stats = await rebuild_reviews(session)
    if stats.withheld:
        print(f"no reviews written: {stats.withheld}")
        return 0
    print(f"{stats.matches:,} games reviewed")
    if stats.skipped:
        print(f"{stats.skipped:,} skipped: no usable timeline extract")
    return 0


async def cmd_audit(args) -> int:
    """How well the Riftline score tracks wins, per role. No Riot call."""
    await init_db()
    async with SessionLocal() as session:
        row = await store_audit(session)
    report = row.payload
    overall = report["overall"]
    print(f"score audit, weights v{report['weights_version']}: {report['games']:,} games, "
          f"{report['players']:,} players")
    if report["players"]:
        print(f"winners {overall['winners_mean']} against losers {overall['losers_mean']}, "
              f"AUC {overall['auc']}, top scorer on the winning team "
              f"{overall['top_on_winning_team'] * 100:.1f}%, bottom scorer on the losing team "
              f"{overall['bottom_on_losing_team'] * 100:.1f}%")
    for role in report["roles"]:
        fitted = role["fitted"]["normalised"]
        pairs = ", ".join(f"{c} {role['set_weights'][c]:.2f}/{fitted[c]:.2f}" for c in role["set_weights"])
        print(f"  {role['position']:<8} AUC {role['auc']:.3f}  winners {role['winners_mean']} "
              f"losers {role['losers_mean']}  set/fitted: {pairs}")
    return 0


async def cmd_draft_priors(args) -> int:
    """What the draft's evidence strengths should be on the corpus now. No Riot call."""
    from app.services.draft_priors import measure

    await init_db()
    async with SessionLocal() as session:
        report = await measure(session, args.queue)
    if report.newer is None:
        print(f"draft priors: nothing aggregated for queue {report.queue_id}")
        return 0
    against = f"against {report.older}" if report.older else "(no earlier patch close enough)"
    print(f"draft priors, queue {report.queue_id}: {report.newer} {against}")

    def games(value):
        return "no effect" if value is None else f"{value:,.0f} games"

    for scope in report.scopes:
        print(f"  {scope.scope} (in use: {scope.strength_in_use:,.0f} games)")
        for r in scope.repeatability:
            print(
                f"    repeats, {r.min_games}+ games on both: {r.pairs:,} pairs, typical {r.typical_games:.1f} "
                f"games, r {r.r:+.3f} ({r.r_low:+.3f} to {r.r_high:+.3f}): {games(r.strength)} "
                f"(plausible {games(r.strength_low)} to {games(r.strength_high)})"
            )
        print(
            f"    spread within {report.newer}: {scope.within_pairs:,} pairs with 5+ games, "
            f"{games(scope.within_strength)}"
        )
        if scope.split_slope is not None:
            print(
                f"    time split at the strength in use: slope {scope.split_slope:.2f} over "
                f"{scope.split_pairs:,} pairs (1 is right; above 1 the prior is too strong)"
            )
    rates = report.champion_rates
    if rates is not None:
        spread ="within noise" if rates.spread is None else f"sd {rates.spread * 100:.1f} points"
        print(
            f"  champion win rates, {rates.rows:,} role rows with 20+ games on {report.newer}: "
            f"true spread {spread}, prior {games(rates.strength)}; "
            f"{rates.separated_above} clearly above 50%, {rates.separated_below} clearly below"
        )
        if rates.top_next is not None and rates.bottom_next is not None:
            print(
                f"    the tier list's top and bottom tenth of {report.older} ({rates.split_rows:,} rows "
                f"on both) won {rates.top_next:.1%} and {rates.bottom_next:.1%} on {report.newer}"
            )
    scores = report.player_scores
    if scores is not None and scores.within_sd is not None:
        between = "within noise" if scores.between_sd is None else f"{scores.between_sd:.2f}"
        strength = "none" if scores.strength is None else f"{scores.strength:.1f} games"
        print(
            f"  player scores on a champion, {scores.pairs:,} pairs with {scores.min_scored}+ scored "
            f"games: a game varies by {scores.within_sd:.2f}, players by {between}, prior {strength}"
        )
    if report.damage is not None:
        from app.services.aggregate import wilson_lower_bound, wilson_upper_bound

        mix = report.damage
        print(
            f"  damage mix, from the champions' usual damage: {mix.teams:,} teams with all five "
            f"measured, {mix.unmeasured:,} left out"
        )
        for b in mix.buckets:
            if not b.teams:
                continue
            if b.high is None:
                span = f"{b.low:.0%} and up"
            elif b.low == 0:
                span = f"under {b.high:.0%}"
            else:
                span = f"{b.low:.0%} to {b.high:.0%}"
            print(
                f"    main type {span}: {b.teams:,} teams won {b.wins / b.teams:.1%} "
                f"({wilson_lower_bound(b.wins, b.teams):.1%} to {wilson_upper_bound(b.wins, b.teams):.1%})"
            )
    return 0


async def cmd_groups(args) -> int:
    """Fill in every group's players from Riot, most recently viewed first."""
    settings = get_settings()
    await init_db()
    async with SessionLocal() as session:
        removed = await delete_empty_groups(session)
    if removed:
        print(f"{removed} empty groups removed")
    if not settings.has_key:
        log.error("RIOT_API_KEY is not set. Put your key in backend/.env first.")
        return 2
    calls = args.calls if args.calls is not None else settings.group_nightly_calls
    client = make_client(settings)
    try:
        async with SessionLocal() as session:
            players, budget = await warm_all_groups(session, client, settings, calls=calls)
    finally:
        await client.aclose()
    print(f"{players} group players looked at, {budget.spent:,} Riot calls spent"
          + (f", stopped: {budget.stopped}" if budget.stopped else ""))
    if budget.stopped == "dead":
        log.error("Riot refused the key")
        return 2
    return 0


async def cmd_homes(args) -> int:
    """Put every player row back on its home shard. No Riot call.

    Run by every deploy right after the migration and first in the nightly, so
    rows written under the old rule (a view of another shard moved the row and
    deleted its rank) are repaired before any page is rendered from them.
    """
    await init_db()
    async with SessionLocal() as session:
        report = await repair_homes(session, dry_run=args.dry_run)
    print("home repair" + (" (dry run, nothing written)" if args.dry_run else ""))
    for line in report.lines():
        print(f"  {line}")
    for example in report.examples:
        print(f"    {example}")
    return 0


async def cmd_names(args) -> int:
    """Confirm the Riot IDs of players who qualify for a page, so they get one.

    Run nightly after the local stages, so a player who reached the floor
    tonight is asked before the pages are rendered.
    """
    settings = get_settings()
    await init_db()
    players = args.players if args.players is not None else settings.name_checks_nightly
    if args.dry_run:
        async with SessionLocal() as session:
            report = await confirm_names(session, None, settings, players=players, dry_run=True)
        print(f"names (dry run, nothing asked): {report.due} floor players to confirm")
        for example in report.examples:
            print(f"    {example}")
        return 0
    if not settings.has_key:
        log.error("RIOT_API_KEY is not set. Put your key in backend/.env first.")
        return 2
    client = make_client(settings)
    try:
        async with SessionLocal() as session:
            report = await confirm_names(session, client, settings, players=players)
    finally:
        await client.aclose()
    print("names")
    for line in report.lines():
        print(f"  {line}")
    for example in report.examples:
        print(f"    {example}")
    if report.stopped == "dead":
        log.error("Riot refused the key")
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="ingest", description="Collect and aggregate League match data."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show what has been ingested.")

    crawl = sub.add_parser("crawl", help="Collect matches by walking the ladder.")
    crawl.add_argument("--platform", default="euw1")
    crawl.add_argument("--queue", type=int, default=420, help="420 solo, 440 flex.")
    crawl.add_argument("--target", type=int, default=500, help="New matches to collect.")
    crawl.add_argument("--per-player", type=int, default=10)
    crawl.add_argument(
        "--tier",
        default="challenger",
        help="Seed ladder: challenger, grandmaster, master, DIAMOND, EMERALD, ...",
    )

    tl = sub.add_parser(
        "timelines",
        help="Fetch match timelines for stored matches (laning score, skill order, build path).",
    )
    tl.add_argument("--target", type=int, default=500, help="Timelines to fetch this run.")
    tl.add_argument("--batch", type=int, default=20, help="Matches per round trip.")
    tl.add_argument("--patch", default=None, help="Restrict to one patch.")

    lr = sub.add_parser(
        "lobbyranks",
        help="Measure the average rank of the players in stored matches.",
    )
    lr.add_argument("--target", type=int, default=2000, help="Lobbies to measure.")
    lr.add_argument("--batch", type=int, default=20)
    lr.add_argument("--patch", default=None, help="Restrict to one patch.")

    ld = sub.add_parser("ladders", help="Snapshot ranked ladders for a platform.")
    ld.add_argument("--platform", default="euw1")
    ld.add_argument("--queue", type=int, default=420)
    ld.add_argument(
        "--tier",
        default="apex",
        help="'apex' for master/grandmaster/challenger, or a comma-separated list.",
    )
    ld.add_argument(
        "--pages", type=int, default=5, help="Pages per division below apex."
    )

    sc = sub.add_parser(
        "score",
        help="Riftline scores, placements and badges. Reads local storage only.",
    )
    sc.add_argument(
        "--target",
        type=int,
        default=None,
        help="Stop after this many lobbies. Defaults to every unscored one.",
    )
    sc.add_argument(
        "--rebuild-distributions",
        action="store_true",
        help="Re-measure the corpus first. Do this after ingesting new matches.",
    )
    sc.add_argument(
        "--rescore",
        action="store_true",
        help="Clear scores computed under older weights so they are recomputed.",
    )

    sub.add_parser(
        "buytimes",
        help="Purchase times from the timelines already stored. Reads local storage only.",
    )

    sub.add_parser(
        "audit",
        help="How well the Riftline score tracks wins. Reads local storage only.",
    )

    sub.add_parser(
        "reviews",
        help="Death and kill review for every stored game. Reads local storage only.",
    )

    sub.add_parser(
        "winmodel",
        help="Fit and grade the win-chance model. Reads local storage only.",
    )

    sub.add_parser(
        "reextract",
        help="Bring stored timeline extracts up to date. Reads local storage only.",
    )

    dp = sub.add_parser(
        "draftpriors",
        help="Re-measure the draft's evidence strengths. Reads local storage only.",
    )
    dp.add_argument("--queue", type=int, default=420)

    gr = sub.add_parser(
        "groups",
        help="Fetch what groups' players still lack: ranks, new games, older history.",
    )
    gr.add_argument(
        "--calls", type=int, default=None,
        help="Riot calls to spend at most. Defaults to GROUP_NIGHTLY_CALLS.",
    )

    hm = sub.add_parser(
        "homes",
        help="Put player rows back on their home shard. Reads local storage only.",
    )
    hm.add_argument(
        "--dry-run", action="store_true", help="Report what would change and write nothing."
    )

    nm = sub.add_parser(
        "names",
        help="Confirm the Riot IDs of players who qualify for a profile page.",
    )
    nm.add_argument(
        "--players", type=int, default=None,
        help="Players to ask about at most. Defaults to NAME_CHECKS_NIGHTLY.",
    )
    nm.add_argument(
        "--dry-run", action="store_true", help="Count who is due and ask Riot nothing."
    )

    agg = sub.add_parser("aggregate", help="Rebuild champion and matchup rollups.")
    agg.add_argument("--patch", default=None, help="Defaults to every patch held.")
    agg.add_argument("--queue", type=int, default=None)
    agg.add_argument(
        "--min-matches",
        type=int,
        default=50,
        help="Skip slices thinner than this; aggregates below it are noise.",
    )
    agg.add_argument(
        "--bracket",
        default=None,
        help="Crawl provenance to aggregate. Defaults to ALL plus every bracket held.",
    )
    agg.add_argument(
        "--min-pair-games",
        type=int,
        default=2,
        help="Floor for matchup and synergy pairs.",
    )
    agg.add_argument(
        "--min-facet-games",
        type=int,
        default=3,
        help="Floor for builds, runes and spells. Complete builds have a long tail.",
    )

    args = parser.parse_args()
    if args.command == "status":
        return asyncio.run(cmd_status())
    if args.command == "crawl":
        return asyncio.run(cmd_crawl(args))
    if args.command == "timelines":
        return asyncio.run(cmd_timelines(args))
    if args.command == "lobbyranks":
        return asyncio.run(cmd_lobby_ranks(args))
    if args.command == "ladders":
        return asyncio.run(cmd_ladders(args))
    if args.command == "score":
        return asyncio.run(cmd_score(args))
    if args.command == "aggregate":
        return asyncio.run(cmd_aggregate(args))
    if args.command == "buytimes":
        return asyncio.run(cmd_buy_times(args))
    if args.command == "reextract":
        return asyncio.run(cmd_reextract(args))
    if args.command == "winmodel":
        return asyncio.run(cmd_win_model(args))
    if args.command == "reviews":
        return asyncio.run(cmd_reviews(args))
    if args.command == "draftpriors":
        return asyncio.run(cmd_draft_priors(args))
    if args.command == "audit":
        return asyncio.run(cmd_audit(args))
    if args.command == "groups":
        return asyncio.run(cmd_groups(args))
    if args.command == "homes":
        return asyncio.run(cmd_homes(args))
    if args.command == "names":
        return asyncio.run(cmd_names(args))
    return 1


if __name__ == "__main__":
    sys.exit(main())
