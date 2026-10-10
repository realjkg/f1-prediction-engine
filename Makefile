# F1 Prediction Engine — developer and demo entry points.

.PHONY: demo engine-install web-install test lint refresh-data

demo: engine-install web-install ## One-command demo: verify → predict → prove → narrate → serve
	python3 scripts/demo.py --data-dir data/snapshot --port 8000

engine-install: ## Install the Python engine (editable, with dev tools)
	python3 -m pip install -e "engine[dev]"

refresh-data: ## Offline tool: regenerate the pinned snapshot from Jolpica (rate-aware, resumable)
	python3 scripts/refresh-data.py

web-install: ## Install the PWA workspace
	npm --prefix web ci

test: ## Engine and web tests
	python3 -m pytest engine/tests
	npm --prefix web test

lint: ## Ruff (engine + scripts) and tsc --noEmit (web)
	python3 -m ruff check engine scripts
	npm --prefix web run lint
