# Deployment

Riftline runs on the shared VPS:

| | |
| --- | --- |
| Site | https://riftline.rhasta.space |
| API | https://riftline-api.rhasta.space |
| Deploy directory | `/root/riftline` |
| Corpus | Docker volume `riftline_data`, mounted at `/srv/riftline/data` |
| CI/CD | GitHub Actions on a self-hosted runner at `/root/actions-runner-riftline` |

## How it fits on that box

The VPS already serves five other sites, so the first requirement was to add
one without touching any of them.

Ports 80 and 443 belong to a `caddy-docker-proxy` container (project `edge`, at
`/root/edge`). It reads Caddy configuration from **Docker labels** on any
container attached to the `edge_default` network and obtains Let's Encrypt
certificates itself. Its own compose file says so: *"a new site is added by
running a labelled container, no edit here."*

So Riftline is a compose project with two labelled containers and no published
ports:

```
                     :443
                       |
        caddy-docker-proxy (project: edge)
           |                        |
  riftline.rhasta.space   riftline-api.rhasta.space
           |                        |
     riftline-web  ---- /api --->  riftline-api
    (nginx + bundle)              (uvicorn + SQLite)
                                        |
                                  riftline_data volume
```

Nothing in `/root/edge` was edited, and neither container publishes a host
port, so this project cannot collide with a neighbour or take one down with it.

`configurespaces.rhasta.space` and `configurespaces-api.rhasta.space` were
already set up this way on the same box and in the same DNS zone. The label
shape here is copied from them rather than invented.

### Why the site proxies its own /api

The client fetches relative paths (`/api/...`, see `frontend/src/lib/api.ts`),
which the Vite dev server proxies in development so the browser stays on one
origin. The web container's nginx does the same in production, so the browser
never makes a cross-origin request and CORS never enters the picture. The API
domain is served in parallel for anything that wants to call it directly.

## First-time setup

Done once. Everything after this is a `git push`.

```bash
# 1. The deploy directory and the environment file, which is not in git.
ssh MyVPS 'mkdir -p /root/riftline'
scp .env.example MyVPS:/root/riftline/.env.example
ssh MyVPS 'cd /root/riftline && cp -n .env.example .env && nano .env'   # paste the Riot key

# 2. The corpus. 316 MB, so it goes once and deploys never touch it again.
#    Copy into the volume through a throwaway container: the volume is not a
#    bind mount, so there is no host path to scp to.
ssh MyVPS 'docker volume create riftline_data'
scp data/lol.db MyVPS:/tmp/lol.db
ssh MyVPS 'docker run --rm -v riftline_data:/data -v /tmp:/host alpine \
             sh -c "cp /host/lol.db /data/lol.db && chmod 644 /data/lol.db" && rm /tmp/lol.db'

# 3. Bring it up, and ask it whether that worked.
ssh MyVPS 'cd /root/riftline && docker compose up -d --build'
make health

# 4. The nightly ingestion timer.
ssh MyVPS 'cp /root/riftline/deploy/riftline-ingest.{service,timer} /etc/systemd/system/ \
           && systemctl daemon-reload && systemctl enable --now riftline-ingest.timer'
```

## Rotating the Riot key

A development key from `developer.riotgames.com` **expires 24 hours after it is
issued**. While it is expired, live lookups (profile search, match history,
mastery, live game) report that the key needs renewing, and everything served
from the stored corpus (tier list, champion pages, leaderboards, the Riftline
scores) carries on working, because none of it calls Riot.

One command, from the repository root:

```bash
make rotate-key KEY=RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

or by hand:

```bash
ssh MyVPS 'cd /root/riftline \
  && sed -i "s|^RIOT_API_KEY=.*|RIOT_API_KEY=RGAPI-...|" .env \
  && docker compose up -d --force-recreate api \
  && docker compose exec -T api python - < deploy/healthcheck.py'
```

It is a restart, not a rebuild: the key is read from `.env` at start, so there
is nothing to compile and the site is down for about two seconds.

## The nightly pipeline

`deploy/nightly-ingest.sh`, run by `riftline-ingest.timer` at 03:20 UTC.

It splits on one fact: with a development key, most nights it will run against
a dead key.

| Stage | Calls Riot | Runs when the key is dead |
| --- | --- | --- |
| `crawl` | yes | skipped |
| `timelines` | yes | skipped |
| `lobbyranks` | yes | skipped |
| `aggregate` | no | **yes** |
| `score` | no | **yes** |

The script asks Riot one cheap question (the EUW Challenger ladder) to decide
which half to run, rather than guessing from the clock, because a key can be
revoked as well as expire. A dead key is logged as the expected state it is,
not as a failure, and the local stages still leave the tier list, the champion
pages and the scores consistent with whatever is on disk.

```bash
journalctl -u riftline-ingest -n 100 --no-pager   # last run
systemctl list-timers riftline-ingest             # when the next one is due
/root/riftline/deploy/nightly-ingest.sh           # run it now
make ingest                                       # the same, from here
```

The script itself is deployed with everything else, so editing it is a push.
**The two systemd units are not**: they live in `/etc/systemd/system/`, outside
the deploy directory, so changing `deploy/riftline-ingest.service` or `.timer`
needs one command afterwards.

```bash
ssh MyVPS 'cp /root/riftline/deploy/riftline-ingest.{service,timer} /etc/systemd/system/            && systemctl daemon-reload && systemctl restart riftline-ingest.timer'
```

A first run with small targets, to prove the plumbing rather than fetch much:

```bash
ssh MyVPS 'CRAWL_TARGET=3 TIMELINE_TARGET=3 LOBBY_TARGET=5 /root/riftline/deploy/nightly-ingest.sh'
```

## CI/CD

`.github/workflows/ci.yml`, on a self-hosted runner labelled `riftline`.

**Test** (every push and pull request) builds both images and runs, inside
them: the 401-test backend suite, `ruff`, the frontend type-check and bundle
build, `oxlint`, and an em dash check. Nothing is installed on the host; the
runner needs only Docker. The suite runs in the image that gets deployed.

**Deploy** (pushes to `main` only) rsyncs the checkout into `/root/riftline`
excluding `.env` and `data/`, rebuilds and restarts the containers, runs
`deploy/healthcheck.py`, checks nginx is serving the built bundle rather than
merely answering, applies migrations, and prints what is live.

`deploy/healthcheck.py` waits for `/api/health` to say `ok`, then counts the
rows in the live database. The second half earns its keep: a container comes up
perfectly healthy against an empty database, and the only symptom would be a
site that looks right and shows nothing. `make health` runs the same check by
hand.

The repository is **private** on purpose. A self-hosted runner executes
workflow code on the box; on a public repository a fork's pull request could
run anything there, and this box serves five other sites.

### The runner

```bash
systemctl status actions.runner.siteauditor-riftline.vmi3198945-riftline
journalctl -u actions.runner.siteauditor-riftline.vmi3198945-riftline -n 50
```

It is a second runner, in its own directory (`/root/actions-runner-riftline`),
alongside the one that already serves another project. They share nothing but
the Docker daemon. Repo-scoped, labelled `riftline`, running as root, which is
what lets it drive Compose.

To re-register it (a new token is needed each time, and lasts an hour):

```bash
gh api -X POST repos/siteauditor/riftline/actions/runners/registration-token -q .token   | ssh MyVPS 'read -r T; cd /root/actions-runner-riftline; export RUNNER_ALLOW_RUNASROOT=1;       ./config.sh --unattended --replace --url https://github.com/siteauditor/riftline         --token "$T" --name vmi3198945-riftline --labels riftline --work _work < /dev/null'
```

## Operating notes

- **One API worker, on purpose.** The workload is IO-bound against Riot and
  SQLite, and several processes writing one SQLite file is how you earn
  `database is locked`. The ingestion CLI already competes for that file.
- **The corpus is the valuable artefact.** 1,795 matches, every stored Riot
  payload, and the 17,520 scores derived from them, in a named volume that no
  deploy touches. To back it up:
  ```bash
  ssh MyVPS 'docker run --rm -v riftline_data:/data alpine \
               tar czf - -C /data lol.db' > riftline-corpus-$(date +%F).tar.gz
  ```
- **Migrations are additive and idempotent**, so the deploy runs them every
  time and a second run reports nothing to do.
- **Data Dragon** is fetched at start and cached in the volume at
  `data/static`, with a disk fallback, so a CDN outage degrades to stale art
  rather than a blank site.
