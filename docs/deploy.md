# Deployment

Riftline runs on the shared VPS:

| | |
| --- | --- |
| Site | https://riftline.rhasta.space |
| API | https://riftline-api.rhasta.space |
| Deploy directory | `/root/riftline`, a clone of the public repository |
| Corpus | Docker volume `riftline_data`, mounted at `/srv/riftline/data` |
| CI/CD | GitHub-hosted runners; deploys over SSH to a forced command |

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

### Web traffic only from Cloudflare

Every hostname served from this box is proxied by Cloudflare, so ports 80 and
443 answer Cloudflare's address ranges and nobody else. Someone who finds the
origin address gets no answer, rather than a way around Cloudflare's WAF, DDoS
protection and rate limiting. Keeping the address secret does not hold up
against scanners or a leaked commit; refusing everyone but Cloudflare does.

`deploy/cloudflare-only-web`, installed at `/usr/local/sbin/` and run at boot
(and after every Docker restart) by `cloudflare-only-web.service`. It covers IPv4
and IPv6, and both routes traffic takes to Caddy: Docker's DNAT, which only the
`DOCKER-USER` chain sees, and Docker's userland proxy, which arrives on `INPUT`.

It leaves alone SSH, the miner's port 8091, and traffic the box starts itself.
Only new connections arriving on the public interface are checked, so replies
to a container's own calls out on 443 (Riot's API, Data Dragon) pass. Certificate
renewal is unaffected: every certificate here was issued through `http-01`,
which arrives via Cloudflare like any request.

Verified when it went in: all six sites answered exactly as before through
Cloudflare, the origin stopped answering directly on 80 and 443, and the miner,
SSH and outbound calls from containers were unchanged.

```bash
ssh MyVPS cloudflare-only-web status          # the rules in force
ssh MyVPS systemctl stop cloudflare-only-web  # open 80/443 to everyone again
ssh MyVPS systemctl start cloudflare-only-web # and close them

# Install or update, after editing the script (for example, when Cloudflare
# publishes new ranges: https://api.cloudflare.com/client/v4/ips).
ssh MyVPS 'install -m 0755 /root/riftline/deploy/cloudflare-only-web /usr/local/sbin/ \
  && install -m 0644 /root/riftline/deploy/cloudflare-only-web.service /etc/systemd/system/ \
  && systemctl daemon-reload && systemctl enable cloudflare-only-web \
  && systemctl restart cloudflare-only-web'
```

### Why the site proxies its own /api

The client fetches relative paths (`/api/...`, see `frontend/src/lib/api.ts`),
which the Vite dev server proxies in development so the browser stays on one
origin. The web container's nginx does the same in production, so the browser
never makes a cross-origin request and CORS never enters the picture. The API
domain is served in parallel for anything that wants to call it directly.

## First-time setup

Done once. Everything after this is a `git push`.

```bash
# 1. The deploy directory, a clone of the public repository, and the
#    environment file, which is not in git (it is ignored, so no deploy's
#    `git reset --hard` ever touches it).
ssh MyVPS 'git clone https://github.com/siteauditor/riftline.git /root/riftline'
ssh MyVPS 'cd /root/riftline && cp -n .env.example .env && chmod 600 .env && nano .env'   # paste the Riot key

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

# 5. What CI deploys through. See "CI/CD" below for the key and the secrets.
ssh MyVPS 'install -m 0755 /root/riftline/deploy/riftline-deploy /usr/local/bin/riftline-deploy'
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

`.github/workflows/ci.yml`. The repository is **public**, so anyone can open a
pull request, and a pull request can edit that file. The pipeline is built so
that doing so reaches nothing that matters.

```
  pull request / push                  push to main only
         |                                    |
  GitHub-hosted runner              GitHub-hosted runner
  (fresh VM, thrown away)           + `production` environment secrets
         |                                    |
  tests, lint, bundle build          ssh root@VPS "<commit sha>"
                                              |
                                  /usr/local/bin/riftline-deploy
                                  (forced command: the only thing the key runs)
                                              |
                                  sha on main?  fetch, reset, deploy/deploy.sh
```

**Test** (every push and pull request) runs on a GitHub-hosted machine: it
builds both images and runs, inside them, the backend suite, `ruff`, the
frontend type-check and bundle build, `oxlint`, and an em dash check. A hostile
pull request can run anything it likes there, on a machine that holds nothing
and is deleted afterwards.

**Deploy** (pushes to `main` only) never runs on the server. It connects over
SSH with a key whose `authorized_keys` entry is a forced command,
`deploy/riftline-deploy`, installed at `/usr/local/bin/riftline-deploy`. That
script ignores whatever the client asked to run and reads it as one thing: a
40-character commit sha. It refuses anything else, and refuses a sha that is not
on `main`. Then it takes a lock, moves `/root/riftline` to exactly that commit,
and runs `deploy/deploy.sh`, which rebuilds the containers, runs
`deploy/healthcheck.py`, checks nginx is serving the built bundle rather than
merely answering, applies migrations, and prints what is live.

So a leaked deploy key can redeploy a commit that was already merged, and
nothing else. Tested with the key itself: no shell (the PTY request is refused),
no arbitrary command, no sha from outside `main`.

Re-running an old deploy from the Actions tab deploys that old commit, which is
the rollback.

`deploy/healthcheck.py` waits for `/api/health` to say `ok`, then counts the
rows in the live database. The second half earns its keep: a container comes up
perfectly healthy against an empty database, and the only symptom would be a
site that looks right and shows nothing. `make health` runs the same check by
hand.

### Why there is no self-hosted runner

There was one, on this VPS, running as root with Docker, while the repository
was private. On a public repository that is the worst available arrangement: a
pull request can change `runs-on` to name it, and whatever it runs, runs as root
on a box that serves five other sites, next to the Riot key. GitHub's own
guidance is not to use self-hosted runners with public repositories.

It was removed when the repository went public. Do not add one back.

### The secrets

On the `production` environment, which only `main` may deploy from. There are
no repository-level secrets, and GitHub never gives secrets to a pull request
from a fork.

| Secret | Holds |
| --- | --- |
| `DEPLOY_SSH_KEY` | The deploy key's private half. Its public half is the forced-command entry in `/root/.ssh/authorized_keys`, commented `riftline-github-deploy` |
| `DEPLOY_KNOWN_HOSTS` | The server's ed25519 host key, pinned. Read from the server over a trusted session, not scanned, so a first connection cannot be spoofed |
| `DEPLOY_HOST` | The server address |

To replace the key:

```bash
ssh-keygen -t ed25519 -N "" -C riftline-github-deploy -f riftline_deploy
gh secret set DEPLOY_SSH_KEY --env production < riftline_deploy
# In /root/.ssh/authorized_keys, replace the riftline-github-deploy line with:
#   command="/usr/local/bin/riftline-deploy",restrict <contents of riftline_deploy.pub>
rm riftline_deploy riftline_deploy.pub
```

### Pull requests from outside

- Anyone can open one. Only collaborators with write access can merge, and
  there is one: the owner.
- A pull request from a fork waits for the owner to click **Approve and run**
  before any workflow runs (Settings, Actions, "Require approval for all
  external contributors"). With no runner of ours to reach, that is a guard
  against wasted minutes rather than the only thing between a stranger and
  root, which is what it would be with a self-hosted runner.
- `main` has a ruleset: changes arrive through a pull request that passes
  **Tests and build**, and it cannot be force-pushed or deleted. The owner can
  bypass it, which is how a direct push to `main` still deploys.

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
