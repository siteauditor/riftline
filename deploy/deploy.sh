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

  # Names this build: the web image reads its prerendered pages from
  # /pages/<BUILD_ID>, and the prerender job writes them there.
  export BUILD_ID
  BUILD_ID=$(git rev-parse --short HEAD)

  # Named, because the prerender service sits behind a profile and a bare
  # `build` would skip it.
  docker compose build api web prerender
  docker compose up -d api

  # The app answers, and the corpus is still under it. See healthcheck.py for
  # why the second half is the one that matters.
  docker compose exec -T api python - < deploy/healthcheck.py

  # Additive and idempotent, so safe on every deploy, and the only way a new
  # column reaches the live corpus.
  docker compose exec -T api python -m scripts.migrate

  # Every page as HTML, from the API just started, before the new web container
  # takes over. Fatal on purpose: a build that cannot prerender must not be
  # switched to, and the web container still running is the last build with
  # its own pages, which keeps serving.
  docker compose run --rm prerender

  docker compose up -d web

  # Captured before matching rather than piped into `grep -q`: grep exits on
  # its first match, the writer can then die of SIGPIPE, and under pipefail
  # that reports a working site as a failed one. The home page is prerendered,
  # so a served page carries an <h1>; the empty shell would not.
  local page
  page=$(docker compose exec -T web wget -q -O - http://127.0.0.1/)
  if [[ "$page" != *'id="root"'* || "$page" != *'<h1'* ]]; then
    echo "the web container is not serving the prerendered site" >&2
    docker compose logs --tail 50 web >&2
    exit 1
  fi

  # Storage only, and each a no-op when nothing changed: brings the stored
  # corpus up to the code just deployed instead of leaving the site half on the
  # old rules until the nightly run. New score weights would otherwise show
  # beside scores computed under the old ones, and a new score component would
  # withhold every new game, for up to a day. A failure here is reported and
  # not fatal: the site is already up and serving, and the nightly run retries
  # every one of these.
  local stage
  for stage in reextract "score --rescore" winmodel reviews audit; do
    # shellcheck disable=SC2086
    docker compose exec -T api python -m scripts.ingest $stage || echo "post-deploy stage '${stage}' failed; the nightly run retries it" >&2
  done

  docker compose ps
}

main "$@"
