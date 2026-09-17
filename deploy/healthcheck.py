"""Is the API actually serving, and is the corpus still under it?

Run inside the api container, program on stdin so there is no path to keep in
step with the image:

    docker compose exec -T api python - < deploy/healthcheck.py

Exits 0 only when the app answers "ok" and the database has matches in it. The
second half is the one that earns its keep: a container can come up healthy
against an empty database if the volume is ever lost or renamed, and the first
symptom would be a site that looks fine and shows nothing. A deploy should fail
on that, not print it.

Lives in a file rather than inline in the workflow because an indented Python
program inside a YAML block scalar is either an IndentationError or invalid
YAML, and it was invalid YAML.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

HEALTH_URL = "http://127.0.0.1:8000/api/health"
ATTEMPTS = int(os.environ.get("HEALTHCHECK_ATTEMPTS", "30"))
DELAY_SECONDS = 2.0


def health() -> dict | None:
    """The app's readiness answer, or None while it is still starting."""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5) as response:
            return json.load(response)
    except (urllib.error.URLError, OSError, ValueError):
        return None


def corpus_path() -> str | None:
    """The database file DATABASE_URL points at, if it is a SQLite one."""
    url = os.environ.get("DATABASE_URL", "")
    if "sqlite" not in url:
        return None
    _, _, tail = url.partition("://")
    # SQLAlchemy spells a relative path "sqlite:///lol.db" and an absolute one
    # "sqlite:////srv/lol.db", so whatever follows the scheme carries exactly one
    # slash more than the path itself.
    return tail[1:] if tail.startswith("/") else tail


def matches() -> int | None:
    """How many matches the live database holds, or None if it cannot say."""
    path = corpus_path()
    if not path or not os.path.exists(path):
        return None
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            return int(connection.execute("SELECT count(*) FROM matches").fetchone()[0])
        finally:
            connection.close()
    except sqlite3.Error:
        return None


def main() -> int:
    ready = None
    for attempt in range(1, ATTEMPTS + 1):
        body = health()
        if body is not None and body.get("status") == "ok":
            ready = body
            break
        if attempt == ATTEMPTS:
            print(f"api did not answer ok after {ATTEMPTS} attempts", file=sys.stderr)
            if body is not None:
                print(json.dumps(body), file=sys.stderr)
            return 1
        time.sleep(DELAY_SECONDS)

    body = ready or {}
    stored = matches()
    print(
        "api ok"
        f" | riot key configured: {body.get('riot_key_configured')}"
        f" | data dragon: {body.get('static_data_version')}"
        f" | spectator: {body.get('spectator_enabled')}"
        f" | matches stored: {stored if stored is not None else 'unknown'}"
    )

    if stored == 0:
        print(
            "the database is empty: the corpus volume is missing or not mounted",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
