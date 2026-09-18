#!/usr/bin/env bash
# The versioned half of a deploy: what to do with the code once it is in place.
#
# Run by /usr/local/bin/riftline-deploy after it has moved /root/riftline to the
# commit being deployed (see deploy/riftline-deploy). Lives in the repository so
# that changing the steps is an ordinary commit, reviewed and tested like any
# other.
#
# Everything is inside main(), so bash has read the whole script before any of
# it runs. Without that, a deploy that changes this file would be executing a
# file that git had just replaced beneath it.

set -euo pipefail

main() {
  cd /root/riftline
  echo "deploying $(git rev-parse --short HEAD): $(git log -1 --format=%s)"

  docker compose up -d --build

  # The app answers, and the corpus is still under it. See healthcheck.py for
  # why the second half is the one that matters.
  docker compose exec -T api python - < deploy/healthcheck.py

  # Captured before matching rather than piped into `grep -q`: grep exits on
  # its first match, the writer can then die of SIGPIPE, and under pipefail
  # that reports a working site as a failed one.
  local page
  page=$(docker compose exec -T web wget -q -O - http://127.0.0.1/)
  if [[ "$page" != *'id="root"'* ]]; then
    echo "the web container is not serving the built bundle" >&2
    docker compose logs --tail 50 web >&2
    exit 1
  fi

  # Additive and idempotent, so safe on every deploy, and the only way a new
  # column reaches the live corpus.
  docker compose exec -T api python -m scripts.migrate

  docker compose ps
}

main "$@"
