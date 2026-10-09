# F1 Prediction Engine — developer and demo entry points.
# Milestone 1 scaffold: `demo` prints the contract; the demo-scenario task implements it.

.PHONY: demo engine-install web-install test lint

demo: ## One-command demo (stub) — verify → predict → prove → narrate → serve
	@echo "make demo — Milestone 1 scaffold stub. The implemented sequence will be:"
	@echo "  1. verify   re-hash data/snapshot against provenance.json; refuse on DATA_SNAPSHOT_MISMATCH"
	@echo "  2. predict  as-of features; train m1-gbm, m2-logit, m3-form (fixed seeds); ensemble; ledger records"
	@echo "  3. prove    backtest vs actuals — winner hit rate, podium@3, Brier, per model + ensemble"
	@echo "  4. narrate  LLM race brief — fixture mode default; live digest-pinned Ollama (temperature 0)"
	@echo "  5. serve    uvicorn + PWA; print URL and the evidence-basis banner"

engine-install: ## Install the Python engine (editable, with dev tools)
	python3 -m pip install -e "engine[dev]"

web-install: ## Install the PWA workspace
	npm --prefix web ci

test: ## Engine and web tests
	python3 -m pytest engine/tests
	npm --prefix web test

lint: ## Ruff (engine) and tsc --noEmit (web)
	python3 -m ruff check engine
	npm --prefix web run lint
