# Riftline: the handful of commands worth not retyping.
#
# Deployment lives in docs/deploy.md. These are the operations that touch the
# live box, kept here so they are one command rather than a remembered pipeline.

VPS ?= MyVPS
DIR ?= /root/riftline
COMPOSE = cd $(DIR) && docker compose

.PHONY: help
help:
	@echo "rotate-key KEY=RGAPI-...   Replace the Riot key and restart the API"
	@echo "status                     What the live corpus holds"
	@echo "logs [N=50]                Tail the API log"
	@echo "ingest                     Run the nightly pipeline now"
	@echo "backup                     Copy the live corpus here as a tarball"
	@echo "deploy                     Rebuild and restart from what is on the box"

# A development key expires 24 hours after it is issued. This is a restart, not
# a rebuild: the key is read from .env at start.
.PHONY: rotate-key
rotate-key:
	@test -n "$(KEY)" || { echo "usage: make rotate-key KEY=RGAPI-..."; exit 1; }
	@case "$(KEY)" in RGAPI-*) ;; *) echo "that does not look like a Riot key"; exit 1;; esac
	@ssh $(VPS) 'set -e; cd $(DIR); \
	  sed -i "s|^RIOT_API_KEY=.*|RIOT_API_KEY=$(KEY)|" .env; \
	  docker compose up -d --force-recreate api >/dev/null; \
	  sleep 6; \
	  docker compose exec -T api python -c "\
import json,urllib.request; \
b=json.load(urllib.request.urlopen(\"http://127.0.0.1:8000/api/health\",timeout=10)); \
print(\"key configured:\", b[\"riot_key_configured\"], \"| data dragon:\", b[\"static_data_version\"])"'
	@echo "rotated. The key is never printed by this target or by the app."

.PHONY: status
status:
	@ssh $(VPS) '$(COMPOSE) exec -T api python -m scripts.ingest status'

N ?= 50
.PHONY: logs
logs:
	@ssh $(VPS) '$(COMPOSE) logs --tail $(N) api'

.PHONY: ingest
ingest:
	@ssh $(VPS) '$(DIR)/deploy/nightly-ingest.sh'

.PHONY: backup
backup:
	@ssh $(VPS) 'docker run --rm -v riftline_data:/data alpine tar czf - -C /data lol.db' \
	  > riftline-corpus-$$(date +%F).tar.gz
	@ls -lh riftline-corpus-$$(date +%F).tar.gz

# Normally CI does this on a push to main. Useful when the runner is down or to
# redeploy without a commit.
.PHONY: deploy
deploy:
	@ssh $(VPS) 'set -e; $(COMPOSE) up -d --build; \
	  $(COMPOSE) exec -T api python -m scripts.migrate; \
	  $(COMPOSE) ps'
