PYTHON ?= python3.12
VENV   := .venv
BIN    := $(VENV)/bin

export PATH := $(CURDIR)/$(BIN):$(PATH)

export JOBEASE_DUCKDB   ?= $(CURDIR)/data/warehouse.duckdb
export DBT_PROFILES_DIR := $(CURDIR)/dbt
DBT_FLAGS := --project-dir dbt --profiles-dir dbt

.PHONY: setup lint format typecheck test check ingest fetch snapshot build export notebooks map tour dev clean

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
	$(BIN)/jobease ingest-ba
	$(BIN)/jobease ingest-gvisys
	$(BIN)/jobease ingest-bkg

## Fetch listing counts from the BA job board (~20-30 min; resumable with --batch-id).
fetch:
	$(BIN)/jobease fetch-counts

## Store today's open listings (S2; ~30-60 min; rerun the same day to resume).
snapshot:
	$(BIN)/jobease snapshot-listings

## Level 3: the district map, docs/map/index.html + data.js.
map:
	$(BIN)/jobease export-map

## Level 3: the city-to-city tour as an MP4 for LinkedIn (reads docs/map/data.js).
tour: map
	$(BIN)/jobease record-tour

## Seeds, models and data tests, in dependency order.
build:
	$(BIN)/dbt build $(DBT_FLAGS)

export:
	$(BIN)/jobease export

## Run the level-2 notebooks and export each as a standalone page in docs/notebooks/.
## Level 1 (notebooks/level1_learn) reads private tables and is never exported.
NOTEBOOKS := $(wildcard notebooks/level2_analysis/*.py)
notebooks:
	mkdir -p docs/notebooks
	for nb in $(NOTEBOOKS); do \
		$(BIN)/marimo export html "$$nb" -o "docs/notebooks/$$(basename "$$nb" .py).html" || exit 1; \
	done

dev:
	$(BIN)/dagster dev

clean:
	rm -rf dbt/target dbt/logs .pytest_cache .mypy_cache .ruff_cache
