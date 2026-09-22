#!/usr/bin/env bash
# Nightly ingestion for the deployed corpus.
#
# Run by a systemd timer on the VPS (see riftline-ingest.service/.timer). It
# works through the pipeline in dependency order, inside the api container, so
# it uses the same code and the same database the site serves.
#
# The shape of this script is dictated by one fact: a Riot development key
# expires 24 hours after it is issued, so on most nights some or all of it will
# run with a dead key. It therefore splits into two halves.
#
#   Riot-dependent   crawl, timelines, lobbyranks, ladders, groups. Skipped entirely
#                    when the key is dead, because every request would fail and
#                    the log would be noise rather than information.
#   Local-only       aggregate, score. These read the stored corpus and make no
#                    network call at all, so they always run and always finish.
#                    A dead key therefore still leaves the site's derived data
#                    consistent with whatever was ingested before it died.
#
# Exit status is the honest one: 0 when everything that could run did, 1 only
# when a stage that should have worked failed.

set -uo pipefail

PROJECT_DIR="${PROJECT_DIR:-/root/riftline}"
COMPOSE="docker compose -f ${PROJECT_DIR}/docker-compose.yml"

# How much to fetch per night. Deliberately modest: a development key allows 100
# requests per two minutes, so this is a few hours of crawling, and the point is
# a corpus that grows steadily rather than one that races a rate limiter.
CRAWL_TARGET="${CRAWL_TARGET:-400}"
TIMELINE_TARGET="${TIMELINE_TARGET:-400}"
LOBBY_TARGET="${LOBBY_TARGET:-600}"
# Apex ladders to snapshot: Master, Grandmaster and Challenger, one call each per
# platform. A profile reads its ladder position from these snapshots and hides
# it once one is two days old, so without this stage the position only existed
# on days somebody happened to open the leaderboard.
LADDER_PLATFORMS="${LADDER_PLATFORMS:-euw1 kr na1 oc1 sg2 br1}"

log() { printf '%s  %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

run_stage() {
  local name="$1"; shift
  log "=== ${name} ==="
  if $COMPOSE exec -T api "$@"; then
    log "${name}: done"
    return 0
  fi
  log "${name}: FAILED"
  return 1
}

cd "$PROJECT_DIR" || { log "no project at ${PROJECT_DIR}"; exit 1; }

if ! $COMPOSE ps --status running --services 2>/dev/null | grep -qx api; then
  log "api container is not running; nothing to do"
  exit 1
fi

failures=0

# Is the key alive? Asked by making the cheapest real call there is rather than
# by reading the clock: a key can also be revoked, and the answer we want is
# "will Riot talk to us", not "is it probably still fresh".
log "=== checking the Riot key ==="
key_output=$($COMPOSE exec -T api python - <<'PY' 2>/dev/null
import asyncio
from app.config import get_settings
from app.riot.client import RiotClient
from app.riot.errors import RiotUnauthorized
from app.riot.routing import resolve_platform

async def main():
    settings = get_settings()
    if not settings.has_key:
        print("absent"); return
    async with RiotClient(settings.riot_api_key) as client:
        try:
            # Challenger ladder: one call, no puuid needed, always exists.
            await client.apex_league("RANKED_SOLO_5x5", "challenger", resolve_platform("euw1"))
            print("alive")
        except RiotUnauthorized:
            print("expired")
        except Exception as exc:
            print(f"unreachable:{type(exc).__name__}")

asyncio.run(main())
PY
) || key_output=""

# Only the four answers below count. Anything else the container happened to
# write on stdout is ignored, so one stray line of application logging cannot be
# mistaken for a verdict on the key.
key_state=$(printf '%s\n' "$key_output" | tr -d '\r' \
  | grep -Ex 'alive|expired|absent|unreachable:.*' | tail -n 1)
key_state="${key_state:-unknown}"
log "riot key: ${key_state}"

# Whether tonight actually brought anything new in. It decides below whether the
# percentile distributions are worth rebuilding.
ingested=0

case "$key_state" in
  alive)
    # Order matters. Crawling finds matches, timelines deepen them, lobby ranks
    # measure them; each later stage works on what the earlier one found.
    if run_stage "crawl" python -m scripts.ingest crawl --target "$CRAWL_TARGET"; then
      ingested=1
    else
      failures=$((failures+1))
    fi
    run_stage "timelines"  python -m scripts.ingest timelines --target "$TIMELINE_TARGET" || failures=$((failures+1))
    run_stage "lobbyranks" python -m scripts.ingest lobbyranks --target "$LOBBY_TARGET"  || failures=$((failures+1))
    for ladder_platform in $LADDER_PLATFORMS; do
      run_stage "ladders ${ladder_platform}" python -m scripts.ingest ladders --platform "$ladder_platform" --tier apex || failures=$((failures+1))
    done
    # Groups' players: ranks, new games and older history up to the cap, most
    # recently viewed groups first, within GROUP_NIGHTLY_CALLS. Before the
    # local stages, so the games it brings in are scored and reviewed tonight.
    run_stage "groups" python -m scripts.ingest groups || failures=$((failures+1))
    ;;
  expired|absent)
    log "skipping crawl, timelines, lobbyranks, ladders and groups: the key is ${key_state}."
    log "rotate it with: docs/deploy.md -> 'Rotating the Riot key'"
    ;;
  *)
    log "skipping the Riot stages: could not reach Riot (${key_state})."
    ;;
esac

# Always. These read the stored corpus and make no network call, so they are
# what keeps the tier list, the champion pages and the scores consistent with
# whatever is on disk, key or no key. Purchase times first: the item guide's
# figures in `aggregate` read them, and timelines stored before they were
# recorded are filled from their own raw events. `reextract` brings stored
# timelines up to the fields the win-chance model and the review read.
run_stage "buytimes"  python -m scripts.ingest buytimes  || failures=$((failures+1))
run_stage "reextract" python -m scripts.ingest reextract || failures=$((failures+1))
run_stage "aggregate" python -m scripts.ingest aggregate || failures=$((failures+1))

# --rescore costs one query and makes a change to the weights self-applying on
# the first run after a deploy. --rebuild-distributions is the expensive one: it
# clears and recomputes every score in the corpus, which is worth doing when the
# night brought new matches and is pure work when the key was dead and nothing
# moved. So it is conditional, and `score` on its own still measures the
# distributions the first time it finds none.
score_stage=(python -m scripts.ingest score --rescore)
if [ "$ingested" -eq 1 ]; then
  score_stage+=(--rebuild-distributions)
fi
run_stage "score" "${score_stage[@]}" || failures=$((failures+1))

# The win-chance model is refitted on whatever timelines are stored, then every
# game its new version has not weighed is reviewed, and the score is audited
# against the night's corpus. All three read storage only.
run_stage "winmodel" python -m scripts.ingest winmodel || failures=$((failures+1))
run_stage "reviews"  python -m scripts.ingest reviews  || failures=$((failures+1))
run_stage "audit"    python -m scripts.ingest audit    || failures=$((failures+1))

# Every page as HTML again, now that the numbers behind them have moved. Not
# through run_stage, which execs inside the api container: this is its own
# service, built with the deployed image and writing the pages volume nginx
# reads. A failure keeps yesterday's pages serving, which is the right
# failure.
log "=== prerender ==="
if $COMPOSE run --rm prerender; then
  log "prerender: done"
else
  log "prerender: FAILED (yesterday's pages keep serving)"
  failures=$((failures+1))
fi

log "=== corpus now holds ==="
$COMPOSE exec -T api python -m scripts.ingest status 2>&1 | sed -n '1,12p'

if [ "$failures" -gt 0 ]; then
  log "finished with ${failures} failed stage(s)"
  exit 1
fi
log "finished cleanly"
