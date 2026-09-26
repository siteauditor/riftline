#!/usr/bin/env bash
# Put the Riot key from backend/.env on the server, restart the API, and ask
# Riot whether it takes the key.
#
#   bash deploy/rotate-key.sh
#
# A development key expires 24 hours after it is issued, so this runs about
# once a day: paste the new key into backend/.env, then run this from the
# repository root. `make rotate-key KEY=...` does the same job, but it needs
# make, which the owner's Windows machine does not have, and it takes the key
# on the command line, where it lands in the shell history and in the process
# list of both machines.
#
# The key never appears in a command's arguments or in this script's output:
# it travels over ssh's standard input and is written into the server's .env
# by shell builtins. The file is rewritten in place (`cat >`), so it keeps its
# owner and its 0600 mode.
#
# VPS and DIR can be overridden, as in the Makefile. ENV_FILE is for testing.

set -euo pipefail

VPS="${VPS:-MyVPS}"
DIR="${DIR:-/root/riftline}"
ENV_FILE="${ENV_FILE:-backend/.env}"

say() { printf '%s\n' "$*"; }
fail() { printf 'rotate-key: %s\n' "$*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || fail "no $ENV_FILE here; run this from the repository root"

# The last RIOT_API_KEY line wins, as it does for the app. A file saved on
# Windows carries CRLF, and an editor may have quoted the value.
key="$(grep -E '^[[:space:]]*RIOT_API_KEY=' "$ENV_FILE" | tail -n 1 | cut -d= -f2- | tr -d '\r"'"'"' [:space:]' || true)"
[ -n "$key" ] || fail "$ENV_FILE has no RIOT_API_KEY line"
# RGAPI- and a UUID: anything else is a paste gone wrong, and would take the
# live site's lookups down for nothing.
[[ "$key" =~ ^RGAPI-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] \
  || fail "the RIOT_API_KEY in $ENV_FILE does not look like a Riot key (RGAPI-xxxxxxxx-...)"

say "key in $ENV_FILE ends ...${key: -4}"

# One stream on ssh's stdin: the key's line, taken by `read` (a builtin, which
# reads no further than the newline), then the script for a second bash to
# run. The script replaces the line (or adds it), restarts the API only when
# the key changed, and says which.
state="$(
  {
    printf '%s\n' "$key"
    cat <<'REMOTE'
set -euo pipefail
cd "$1"
key="$ROTATE_KEY"
unset ROTATE_KEY
current="$(grep -E '^RIOT_API_KEY=' .env | tail -n 1 | cut -d= -f2- || true)"
if [ "$current" = "$key" ]; then
  echo same
  exit 0
fi
{
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in RIOT_API_KEY=*) ;; *) printf '%s\n' "$line" ;; esac
  done < .env
  printf 'RIOT_API_KEY=%s\n' "$key"
} > .env.rotating
cat .env.rotating > .env
rm -f .env.rotating
docker compose up -d --force-recreate api >/dev/null 2>&1
echo changed
REMOTE
  } | ssh "$VPS" "IFS= read -r ROTATE_KEY && export ROTATE_KEY && exec bash -s -- '$DIR'"
)" || fail "could not update the server (ssh $VPS)"

state="$(printf '%s' "$state" | tr -d '\r' | tail -n 1)"
case "$state" in
  same) say "the server already had this key; not restarted" ;;
  changed) say "key replaced on the server; API restarted" ;;
  *) fail "unexpected answer from the server: $state" ;;
esac

# Ask Riot, from inside the API container with the key it now runs on: the
# cheapest real call there is, the one the nightly run makes. The API can take
# a few seconds to come back after a restart.
verdict=""
for _ in 1 2 3 4 5 6; do
  verdict="$(ssh "$VPS" "cd '$DIR' && docker compose exec -T api python -" <<'PY' 2>/dev/null | tr -d '\r' | grep -Ex 'alive|expired|absent|unreachable:.*' | tail -n 1 || true
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
            await client.apex_league("RANKED_SOLO_5x5", "challenger", resolve_platform("euw1"))
            print("alive")
        except RiotUnauthorized:
            print("expired")
        except Exception as exc:
            print(f"unreachable:{type(exc).__name__}")

asyncio.run(main())
PY
)"
  [ -n "$verdict" ] && break
  sleep 5
done

case "$verdict" in
  alive) say "Riot accepts the key. Done." ;;
  expired) fail "Riot refuses this key: it has expired or was mistyped. Get a new one at developer.riotgames.com" ;;
  absent) fail "the API started without a key; check $DIR/.env on the server" ;;
  "") fail "the API did not answer; check it with: ssh $VPS 'cd $DIR && docker compose ps api'" ;;
  *) fail "could not reach Riot ($verdict); the key is in place, try the check again later" ;;
esac
