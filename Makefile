PYTHON ?= python3.12
VENV   := .venv
BIN    := $(VENV)/bin
# Through Python, not the .venv/bin/jobease launcher, which pip can leave non-executable.
JOBEASE := $(BIN)/python -m jobease

export PATH := $(CURDIR)/$(BIN):$(PATH)

export JOBEASE_DUCKDB   ?= $(CURDIR)/data/warehouse.duckdb
export DBT_PROFILES_DIR := $(CURDIR)/dbt
DBT_FLAGS := --project-dir dbt --profiles-dir dbt

.PHONY: setup lint format typecheck test check ingest fetch snapshot build export notebooks map tour vacancies dev clean

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e '.[dev,notebooks,video]'
	$(BIN)/playwright install chromium

lint:
	$(BIN)/ruff check src tests scripts notebooks
	$(BIN)/ruff format --check src tests scripts notebooks

format:
	$(BIN)/ruff check --fix src tests scripts notebooks
	$(BIN)/ruff format src tests scripts notebooks

typecheck:
	$(BIN)/mypy

test:
	$(BIN)/pytest

## Offline checks: what CI runs. No network, no data files needed.
check: lint typecheck test
	$(BIN)/dbt parse $(DBT_FLAGS)

## Load the local source files into the warehouse.
ingest:
	$(JOBEASE) ingest-ba
	$(JOBEASE) ingest-gvisys
	$(JOBEASE) ingest-bkg

## Fetch listing counts from the BA job board (~20-30 min; resumable with --batch-id).
fetch:
	$(JOBEASE) fetch-counts

## Store today's open listings (S2; ~30-60 min; rerun the same day to resume).
snapshot:
	$(JOBEASE) snapshot-listings

## Level 3: the district map, docs/map/index.html + data.js.
map:
	$(JOBEASE) export-map

## Level 3: the city-to-city tour as an MP4 for LinkedIn (reads docs/map/data.js).
tour: map
	$(JOBEASE) record-tour

## Level 3 input: the official BA vacancy index (data/official-vacancies/). --offline
## rebuilds from the tables the last fetch stored, with no requests.
vacancies:
	$(JOBEASE) vacancy-index --offline

## Seeds, models and data tests, in dependency order.
build:
	$(BIN)/dbt build $(DBT_FLAGS)

export:
	$(JOBEASE) export

## Run the level-2 notebooks and export each as a standalone page in docs/notebooks/.
## Level 1 (notebooks/level1_learn) reads private tables and is never exported.
## Only the unemployment history is exported: the other two read job-board marts, which
## are no longer published (BA Jobbörse terms of use).
NOTEBOOKS := notebooks/level2_analysis/02_unemployment_history.py
notebooks:
	mkdir -p docs/notebooks
	for nb in $(NOTEBOOKS); do \
		$(BIN)/marimo export html "$$nb" -o "docs/notebooks/$$(basename "$$nb" .py).html" || exit 1; \
	done

dev:
	$(BIN)/dagster dev

clean:
	rm -rf dbt/target dbt/logs .pytest_cache .mypy_cache .ruff_cache
