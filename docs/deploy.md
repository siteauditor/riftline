# Deployment

Riftline runs on the shared VPS:

| | |
| --- | --- |
| Site | https://www.rhasta.space |
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
    www.rhasta.space      riftline-api.rhasta.space
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

### Hostnames

The site is `www.rhasta.space`. Two other names reach the same container and
answer with a permanent redirect to it, path included: `rhasta.space`, the
bare domain, and `riftline.rhasta.space`, the name the site launched under on
2026-09-23 and moved away from the same day. The redirects are Caddy labels
on the web container (`caddy_1` in `docker-compose.yml`), so a link or a
search result that still names the old host lands on the same page. All
three names are proxied DNS records on the zone; Caddy holds a certificate
for each, obtained the same way as the others. `SITE_ORIGIN` (the sitemap and
canonical links) and `CORS_ORIGINS` name the `www` host and nothing else.

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

### Crawlers, at the edge

Cloudflare blocks AI crawlers by default on new zones, and since the 2026
category defaults it can block the multi-purpose ones (Googlebot, bingbot) as
a side effect of blocking the Training category. Measured on 2026-09-23,
before the setting was changed: Googlebot, bingbot and PerplexityBot got 200,
GPTBot and ClaudeBot got 403. The decision for this site is to **allow every
crawler category** (the site has no ads and wants its explainers cited), and,
because that opens training crawlers that fetch thousands of pages per
referral on a box serving six sites, to keep a **rate-limiting rule** on the
zone ahead of it. Both are dashboard settings under the zone's Security
section; nothing in the repository sets them.

The crawler policy was set on 2026-09-23 (Security > Settings > AI bot
policies: Search, Agent and Training all Allow, Bot Preference Sync off),
after which Googlebot, bingbot, GPTBot, ClaudeBot, PerplexityBot and CCBot
all answered 200. To prove it from anywhere:

```bash
for ua in Googlebot bingbot GPTBot ClaudeBot PerplexityBot; do
  printf '%s -> ' "$ua"; curl -s -o /dev/null -w '%{http_code}\n' -A "Mozilla/5.0 (compatible; $ua/1.0)" https://www.rhasta.space/
done
```

Every one should answer 200.

The rate-limiting rule was set the same day (Security > WAF > Rate limiting
rules): expression `(http.host eq "www.rhasta.space")`, 60 requests per
10 seconds counted per IP address, action Block. On this plan the block lasts
as long as the period, 10 seconds, so the effect is a ceiling of about six
requests a second per address rather than a long ban. The field matters: a
first version compared `http.request.uri.path` with the hostname, which no
request can ever satisfy (a path starts with `/`), and 225 requests in 30
seconds went through untouched. Prove it from the server, so that it is the
server's address that gets blocked for ten seconds and not yours:

```bash
ssh MyVPS 'for i in $(seq 1 75); do curl -s -o /dev/null -w "%{http_code}\n" https://www.rhasta.space/api/health; done | sort | uniq -c'
```

Measured on 2026-09-23: 73 answers of 200, then 429 with `retry-after: 10`
(Cloudflare's count lags the edge by a few requests, so the cut is near the
threshold rather than exactly on it).

Still to do, by hand: register the site in Google Search Console and Bing
Webmaster Tools (DNS TXT records on the zone) and submit the sitemap,
`https://www.rhasta.space/sitemap.xml`, in both.

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
#    bind mount, so there is no host path to scp to. Compose declares it
#    `external`, so this step is required: without the volume, `compose up`
#    stops rather than starting the site on an empty database.
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

Paste the new key into `backend/.env`, then from the repository root:

```bash
bash deploy/rotate-key.sh
```

On Windows, `rotate-key.cmd` at the repository root runs the same script with
Git for Windows' bash: double-click it, or run it from cmd or PowerShell. It
keeps its window open when double-clicked, so the answer can be read.

It reads the key from `backend/.env`, checks it looks like a Riot key, puts it
in the server's `.env` (restarting the API only when it changed), and asks
Riot whether it takes it: `Riot accepts the key. Done.` or the reason it does
not. The key travels over ssh's standard input, so it is never in a command
line, the shell history or the output. Or, where `make` is installed:

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
| `homes` | no | **yes** |
| `crawl` | yes | skipped |
| `timelines` | yes | skipped |
| `lobbyranks` | yes | skipped |
| `ladders` (apex, per `LADDER_PLATFORMS`) | yes | skipped |
| `groups` (up to `GROUP_NIGHTLY_CALLS`) | yes | skipped |
| `buytimes` | no | **yes** |
| `reextract` | no | **yes** |
| `aggregate` | no | **yes** |
| `score` (and the lane labels) | no | **yes** |
| `winmodel` | no | **yes** |
| `reviews` | no | **yes** |
| `audit` | no | **yes** |
| `names` (up to `NAME_CHECKS_NIGHTLY` players) | yes | skipped |
| `prerender` | no | **yes** |

`homes` runs first, whatever the key: it puts every player row back on its
home shard from storage alone (`backend/app/services/homes.py`), so the stages
after it and the pages rendered at the end read each player where they play.
It may move a row, drop caches read on another shard and rebuild a rank from
the history; it may not call Riot, delete a player, or touch the history,
matches or scores, and a second run changes nothing. `python -m scripts.ingest
homes --dry-run` prints what it would change. The first release that carried
it ran the dry run in the deploy, so its report could be read in the deploy
log before the nightly run made the first repair.

`groups` fills in the players of every group, most recently viewed first:
ranks, new games, and older history back to `GROUP_HISTORY_CAP` games each. It
spends at most `GROUP_NIGHTLY_CALLS` calls (2,000 by default, about 50 minutes
of a development key), always leaves 20 calls in each two minutes for the
site's own searches, and removes groups that have had nobody in them for a
week. Both settings are in `.env`, so changing them is a container restart.

`names` confirms the Riot IDs of the players who qualify for a profile page
(ten scored ranked games in one role) and whom no lookup has confirmed. Most of
them are rows made from the lobbies they played in, named only by their games,
and a page is written only under a Riot ID account-v1 has confirmed: on
2026-09-24 the local corpus had 515 such players and 20 pages. Each costs two
calls (account-v1, then the active region, which also moves a row to its home),
newest game first, at most `NAME_CHECKS_NIGHTLY` (300) a night, never the 20
calls kept for searches. It runs after the local stages so tonight's scores
decide who qualifies, and before `prerender` so they get their page tonight.
An account Riot does not know is asked again after 30 days.
`python -m scripts.ingest names --dry-run` counts who is due and asks nothing.

`prerender` renders every page again from the night's numbers (see "The
prerendered pages" below). It is its own compose service rather than a stage
inside the api container, and a failure keeps yesterday's pages serving.

The storage stages from `reextract` on also run at the end of every deploy
(`deploy/deploy.sh`, after `migrate`), because each is a no-op when nothing
changed and a release that changes the score weights or adds a timeline field
should not wait for 03:20 to take effect.

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

`deploy/healthcheck.py` waits for `/api/health` to say `ok`, prints whether
Riot accepted the key on its latest answer (`riot_key_ok`: "not asked yet" in
a process that has not called Riot since it started), then counts the
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

## The prerendered pages

Every page is served as HTML rendered from the API's data, and the app
hydrates over it (README, "Search engines"). Three things in the deploy make
that work.

- **`BUILD_ID`**, the short commit sha, exported by `deploy/deploy.sh` and
  baked into both the `web` and `prerender` images as a build argument. nginx
  reads its pages from `/usr/share/nginx/html/pages/<BUILD_ID>` and the
  prerender job writes them there, so the two can only agree, whatever
  environment a later `docker compose up` happens to have. A hand-run
  `docker compose up -d` without `BUILD_ID` set rebuilds nothing and changes
  nothing.
- **The `riftline_pages` volume**, Compose's own (it holds nothing that a
  `docker compose run --rm prerender` cannot make again), mounted read-only
  into `web` and read-write into `prerender`. Each build's pages live in
  their own directory; the two newest are kept. (The first prerendered
  deploy, 5a11ead, created it under Compose's project-prefixed name before
  the name was fixed in the compose file; that orphan was removed on
  2026-09-23.)
- **Each kept build's files stay reachable.** The prerender job copies the
  build's hashed files (`dist/assets`) into `_shared/assets` in the pages
  volume and names them in the build's record, `_shared/builds/<id>.json`,
  and nginx serves `/assets/` from its own image first and from there
  second. A page served from a cache, or a tab left open across a deploy,
  asks for the files of the build that rendered it, which the new image no
  longer holds; without them such a page arrived unstyled and without its
  script. The records of the current build, the two newest others and every
  build rendered in the last week are kept (`frontend/prerender/retention.mjs`),
  and a file goes when no kept record names it. Page folders are still two:
  the current build's and the one before.
- **The order of a deploy**: build, start the api, migrate, **prerender**,
  then start the web container. The prerender is fatal on purpose: a build
  that cannot render its pages is not switched to, and the web container
  still running is the previous build with its own pages, which keeps
  serving. The nightly run prerenders again after the storage stages so the
  numbers on the pages are the night's.
- **Profiles are rendered on request**, by the `render` service
  (`frontend/prerender/live.mjs`, kept up from the prerender image), so the
  title and description a crawler or a link preview read carry the rank Riot
  gives now rather than the one stored at the last prerender: a stored rank
  moves only when someone opens the page, and Telegram's preview of a Silver
  IV player read Bronze I for a day (2026-09-24). nginx sends a profile there
  only when it has a file, so which profiles exist and are indexable is still
  the prerender's call. The renderer gives the live profile three seconds
  (`LIVE_BUDGET_MS`) and at most two at once (`MAX_LIVE`), and past either
  renders from storage, the same HTML as the file; nginx serves the file
  whenever the renderer is down, slow or failing. `X-Prerendered` says which
  answered: `live <build>` or `stored <build>` from the renderer, the bare
  build id from the file. A deploy recreates it from the new image
  (`up -d render web`); the nightly prerender does not need to touch it.

```bash
ssh MyVPS 'cd /root/riftline && docker compose run --rm prerender'   # render every page now
ssh MyVPS 'docker run --rm -v riftline_pages:/pages alpine cat /pages/$(cd /root/riftline && git rev-parse --short HEAD)/_manifest.json'
curl -sI https://www.rhasta.space/tierlist | grep -i 'x-prerendered\|x-robots'   # the build id, and no noindex
curl -sI https://www.rhasta.space/summoner/sg2/Veystrix/999 | grep -i x-prerendered   # live <build>: the renderer answered
ssh MyVPS 'cd /root/riftline && docker compose logs --tail 20 render'     # one line per profile: live or stored, and how long
curl -sI https://www.rhasta.space/no-such-page | grep -i x-robots           # the shell: noindex
```

### Pages in Cloudflare's cache (an owner step)

nginx marks every prerendered page `public, max-age=0, s-maxage=300,
stale-while-revalidate=60`: browsers revalidate every time, and a shared cache
may keep a page five minutes and serve it a minute longer while it fetches the
next. Cloudflare ignores that for HTML unless a rule makes the page eligible
(`cf-cache-status: DYNAMIC` on every page, measured 2026-09-24), so every
visit reaches the origin. Nothing in the repository manages the zone, so the
rule is added by hand, after a deploy that includes the kept files above:

- Caching > Cache Rules > Create rule, named `Riftline pages`.
- When incoming requests match:
  `(http.host eq "www.rhasta.space" and not starts_with(http.request.uri.path, "/api/"))`
- Cache eligibility: **Eligible for cache**. Edge TTL: **Use cache-control
  header if present, bypass cache if not**. Browser TTL: **Respect origin**.
- Caching > Configuration > Browser Cache TTL: **Respect existing headers**.
  With a zone TTL set there, Cloudflare rewrote every page's `max-age=0` to
  `max-age=14400` (measured 2026-09-24), so a browser kept a page four hours
  and could ask for files of a build no longer kept. Check with
  `curl -sI https://www.rhasta.space/tierlist | grep -i cache-control`, which
  should show `max-age=0`.

What the origin says then decides everything: the shell, which answers any
path that has no page, is `no-store` and never held; a profile from the live
renderer says `s-maxage=300` itself; hashed files are immutable for a year;
the sitemap is an hour; and the API is outside the rule. To see it working:

```bash
curl -sI https://www.rhasta.space/tierlist | grep -i cf-cache-status      # MISS, then HIT
curl -sI https://www.rhasta.space/no-such-page | grep -i cf-cache-status  # BYPASS: the shell
curl -s -o /dev/null -D - https://www.rhasta.space/api/health | grep -i cf-cache-status   # DYNAMIC
```

The rate-limiting rule counts every request to the host, hashed files
included, and one page load is 18 to 27 of them (measured on six pages,
2026-09-24), so three quick page views come close to its 60; scoping it to
`starts_with(http.request.uri.path, "/api/")` keeps it on what costs the
origin work. That is the owner's call, in the same Security section.

The manifest of pages, and which of them are indexable, is `GET
/api/meta/pages`; the sitemap nginx serves at `/sitemap.xml` is `GET
/api/meta/sitemap.xml`, the same list filtered. `SITE_ORIGIN` in `.env` is the
absolute origin both are written with. Profile pages are in the manifest
for players with ten scored ranked games in one role (the floor the page's
own score breakdown needs) and a known Riot ID, at their home shard's address,
and are rendered
with `?source=stored`, so the prerender never spends the Riot key however
many players it lists; their number grows with the players people look up.

## Analytics

Umami, self-hosted, at `https://stats.rhasta.space`: page views, referrers,
countries and devices for every page, with no cookies and no personal
identifiers, so no consent banner and nothing sent to a third party. It is
box-level infrastructure like the edge proxy, not part of Riftline's deploy:
one instance can count every site here, and Riftline only carries the
script tag.

- **Where it runs.** `/root/umami`, a compose project of two containers
  (`umami`, `umami-db`), from `deploy/umami/docker-compose.yml` in this
  repository plus a `.env` generated on the server. The database lives in
  the `umami_db` volume. It went in on 2026-09-23.
- **Getting in.** User `admin`; the password is in `/root/umami/.admin-password`
  (root only). The default `umami` password was replaced through the API at
  install, before the hostname was public.
- **The tag.** The site's website id is in `/root/umami/website-id` and in
  `frontend/index.html`. The tracker is served as `/insight.js` and collects
  to `/api/insight`, not Umami's default names, because the common
  ad-blocker lists match those; `data-domains` limits counting to the www
  host, so local development and the redirect names count nothing, and
  `data-exclude-search` drops query strings, so a profile's queue filter or a
  champion's tab is not a separate page. Route changes inside the app are
  counted as page views by the tracker itself.
- **Updating.** `ssh MyVPS 'cd /root/umami && docker compose pull && docker
  compose up -d'`; migrations run on start. The image is the Docker Hub copy
  (`umamisoftware/umami`) because the box's stale `ghcr.io` login makes the
  daemon refuse public ghcr images.
- **Backup.** `ssh MyVPS 'docker exec umami-db pg_dump -U umami umami' >
  umami.sql` takes the whole history; nothing is scheduled.

```bash
curl -s https://stats.rhasta.space/api/heartbeat        # ok
ssh MyVPS 'cd /root/umami && docker compose ps'
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
