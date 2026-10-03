.PHONY: env config up up-core up-edge down ps backup metabase-register check verify

PROFILES ?= --profile core --profile stream --profile orchestration --profile bi --profile docs
COMPOSE = docker compose $(PROFILES)

# Fresh random secrets, written once; .env is gitignored.
env:
	@test -f .env || python3 scripts/make_env.py > .env
	@echo ".env ready"

config: env
	$(COMPOSE) --profile edge config --quiet

# No --wait: compose counts finished init jobs as failures; check with `make ps`.
up: env
	$(COMPOSE) up -d --build

up-core: env
	docker compose --profile core up -d

# Requires edge/config.yml + tunnel credentials; see edge/README.md.
up-edge:
	docker compose --profile edge up -d

down:
	$(COMPOSE) --profile edge down

ps:
	$(COMPOSE) ps

backup:
	python3 scripts/backup_clickhouse.py backup marts

# Needs .metabase_api_key (Metabase admin API key, chmod 600, gitignored).
metabase-register:
	sh scripts/grant_metabase_readers.sh
	python3 scripts/metabase_register.py

check:
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_project.py

verify:
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/verify_runtime.py
