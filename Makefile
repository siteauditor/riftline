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
	@echo "health                     Is the API answering, with the corpus under it"
	@echo "deploy [SHA=...]           Deploy the tip of main, or a given commit"

# A development key expires 24 hours after it is issued. This is a restart, not
# a rebuild: the key is read from .env at start.
.PHONY: rotate-key
rotate-key:
	@test -n "$(KEY)" || { echo "usage: make rotate-key KEY=RGAPI-..."; exit 1; }
	@case "$(KEY)" in RGAPI-*) ;; *) echo "that does not look like a Riot key"; exit 1;; esac
	@ssh $(VPS) 'set -e; cd $(DIR); \
	  sed -i "s|^RIOT_API_KEY=.*|RIOT_API_KEY=$(KEY)|" .env; \
	  docker compose up -d --force-recreate api >/dev/null; \
	  docker compose exec -T api python - < deploy/healthcheck.py'
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

# Normally CI does this on a push to main. By hand, it goes through the same
# entry point CI does, so the lock and the main-only check still apply. Deploys
# the tip of main, or SHA=<commit> to deploy (or roll back to) a specific one.
.PHONY: deploy
deploy:
	@sha="$(SHA)"; \
	  [ -n "$$sha" ] || sha=$$(git ls-remote origin refs/heads/main | cut -f1); \
	  echo "deploying $$sha"; \
	  ssh $(VPS) "SSH_ORIGINAL_COMMAND=$$sha /usr/local/bin/riftline-deploy"

# What CI checks after a deploy: the app answers, and the corpus is still
# under it.
.PHONY: health
health:
	@ssh $(VPS) 'cd $(DIR) && docker compose exec -T api python - < deploy/healthcheck.py'
