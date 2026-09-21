"""Additive schema migration for SQLite.

    python -m scripts.migrate

``create_all`` creates missing *tables* but never ALTERs an existing one, so a
new column on a populated table is invisible to it. Until the schema settles and
earns Alembic, this covers the two cases we actually hit:

* **Additive columns** on tables whose contents are expensive. ``matches`` holds
  one Riot API call per row; throwing it away to add a nullable column would be
  absurd.
* **Derived tables** are dropped and left for ``ingest aggregate`` to rebuild.
  They are pure functions of ``match_participants``, so recreating them is free
  and avoids fighting SQLite's very limited ALTER support.

Idempotent: safe to run repeatedly.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.schema import CreateIndex

from app.db import models  # noqa: F401  (registers the mappers on Base.metadata)
from app.db.base import DATABASE_URL, Base, engine, init_db

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("migrate")

# table -> [(column, SQL type and constraints)]
#
# `match_participants` is technically re-derivable from `matches.raw`, but at
# ~17k rows an additive column is cheaper and far less risky than a re-parse.
# table -> [(old name, new name)]. Applied before ADDITIVE, so a renamed
# column is not then re-added under its new name as an empty duplicate.
RENAMES: dict[str, list[tuple[str, str]]] = {
    # Held the mean; now holds the median, which is a different statistic and
    # deserves a name that does not claim otherwise.
    "matches": [("lobby_avg_rank", "lobby_rank_points")],
}

ADDITIVE: dict[str, list[tuple[str, str]]] = {
    # Pre-dates create_all on some databases, so it is never picked up there.
    "ingest_cursors": [("updated_at", "DATETIME")],
    "matches": [
        ("source_bracket", "VARCHAR(24)"),
        ("lobby_rank_points", "FLOAT"),
        ("lobby_ranked_players", "INTEGER"),
        ("lobby_rank_measured_at", "DATETIME"),
    ],
    "players": [
        ("summoner_platform", "VARCHAR(8)"),
        ("league_platform", "VARCHAR(8)"),
        ("mastery_platform", "VARCHAR(8)"),
    ],
    "match_participants": [
        ("laning_score", "FLOAT"),
        ("opponent_champion_id", "INTEGER"),
        ("gold_at_14", "INTEGER"),
        ("xp_at_14", "INTEGER"),
        ("cs_at_14", "INTEGER"),
        ("gold_diff_14", "INTEGER"),
        ("xp_diff_14", "INTEGER"),
        ("cs_diff_14", "INTEGER"),
        # SQLite stores JSON as TEXT; SQLAlchemy's JSON type handles the coding.
        ("skill_order", "TEXT"),
        ("build_order", "TEXT"),
        ("build_times", "TEXT"),
        # Lifted out of `matches.raw` by `scripts.ingest score`.
        ("time_dead", "INTEGER"),
        ("turret_takedowns", "INTEGER"),
        ("turret_plates", "INTEGER"),
        ("epic_takedowns", "INTEGER"),
        ("objectives_stolen", "INTEGER"),
        ("solo_kills", "INTEGER"),
        ("heal_and_shield", "INTEGER"),
        ("wards_placed", "INTEGER"),
        ("wards_killed", "INTEGER"),
        ("control_wards", "INTEGER"),
        # The Riftline score and what it was computed from.
        ("performance_score", "FLOAT"),
        ("performance_rank", "INTEGER"),
        ("performance_detail", "TEXT"),
        ("performance_scored_at", "DATETIME"),
    ],
}

# Rebuilt from scratch by `python -m scripts.ingest aggregate`.
DERIVED = ("matchup_stats", "champion_stats", "synergy_stats", "champion_facet_stats")


async def existing_columns(conn, table: str) -> set[str]:
    rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).all()
    return {r[1] for r in rows}


async def table_exists(conn, table: str) -> bool:
    row = (
        await conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"),
            {"n": table},
        )
    ).first()
    return row is not None


async def main() -> int:
    if not DATABASE_URL.startswith("sqlite"):
        log.error("This helper only knows SQLite. Use a real migration tool on Postgres.")
        return 2

    async with engine.begin() as conn:
        renamed = 0
        for table, pairs in RENAMES.items():
            if not await table_exists(conn, table):
                continue
            present = await existing_columns(conn, table)
            for old, new in pairs:
                if old not in present or new in present:
                    continue
                await conn.execute(
                    text(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
                )
                log.info("renamed %s.%s to %s", table, old, new)
                renamed += 1

        added = 0
        for table, columns in ADDITIVE.items():
            if not await table_exists(conn, table):
                continue
            present = await existing_columns(conn, table)
            for name, ddl in columns:
                if name in present:
                    continue
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                log.info("added %s.%s", table, name)
                added += 1

        # ALTER TABLE ADD COLUMN never creates an index, and create_all skips a
        # table that already exists along with all of its indexes. So an index
        # declared on an added column is never built on an upgraded database:
        # `ix_matches_source_bracket` was genuinely absent here, on the largest
        # table in the schema, with aggregate.py filtering on it.
        indexed = 0
        for table_name, table in Base.metadata.tables.items():
            if not await table_exists(conn, table_name):
                continue
            columns = await existing_columns(conn, table_name)
            rows = (
                await conn.execute(text(f"PRAGMA index_list({table_name})"))
            ).all()
            have = {r[1] for r in rows}
            for index in table.indexes:
                if index.name in have:
                    continue
                if not {c.name for c in index.columns} <= columns:
                    continue  # the column itself is missing; nothing to index
                await conn.execute(CreateIndex(index, if_not_exists=True))
                log.info("created missing index %s", index.name)
                indexed += 1

        # Only drop a derived table when its columns no longer match the model.
        # Dropping unconditionally makes a no-op run destructive: it would throw
        # away the aggregation every time, which is minutes of work for nothing.
        expected = {
            name: set(table.columns.keys())
            for name, table in Base.metadata.tables.items()
        }
        dropped = 0
        for table in DERIVED:
            if not await table_exists(conn, table):
                continue
            if await existing_columns(conn, table) == expected.get(table):
                continue
            await conn.execute(text(f"DROP TABLE {table}"))
            log.info("schema changed, dropped %s", table)
            dropped += 1

    # Recreates the derived tables, and any table that is new entirely.
    await init_db()
    await engine.dispose()

    log.info(
        "%d column(s) renamed, %d added, %d index(es) created, "
        "%d derived table(s) dropped and recreated",
        renamed, added, indexed, dropped,
    )
    if dropped:
        log.info("run `python -m scripts.ingest aggregate` to repopulate them")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
