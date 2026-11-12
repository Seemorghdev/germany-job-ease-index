# germany-job-ease-index

**Where in Germany is it easiest to land a job?** This project answers from the job seeker's side, using official statistics only: vacancies registered with the Federal Employment Agency (BA) per 1,000 unemployed people, for the German cities with 100,000+ residents.

![Map of Germany: districts shaded by unemployment, cities coloured by registered vacancies per unemployed person](docs/map/germany-job-ease-map.png)

## Results (October 2026)

| Rank | City | Registered vacancies | Unemployed | Vacancies per 1,000 unemployed |
|---|---|---|---|---|
| 1 | Ulm | 1,620 | 3,212 | 504 |
| 2 | Würzburg | 1,840 | 3,841 | 479 |
| 3 | Erlangen | 1,330 | 3,304 | 403 |
| 4 | Jena | 1,220 | 3,443 | 354 |
| 5 | Regensburg | 1,790 | 5,190 | 345 |
| 64 of 68 | Berlin | 21,240 | 223,254 | 95 |

Ulm has **5.3×** as many registered vacancies per unemployed person as Berlin.

The full table is in [`data/exports/city_vacancy_ease.csv`](data/exports/city_vacancy_ease.csv), and the run's metadata, the unranked cities and the notes are in [`summary.json`](data/exports/summary.json).

## Method

- **Vacancies:** the stock of vacancies registered with the BA (*Gemeldete Arbeitsstellen*) in the city's district (Kreis), for October 2026.
- **Job seekers:** registered unemployed (*Arbeitslose*) in the same district and month.
- **Source:** both come from the BA's statistics interface (*Aktuelle Eckwerte*, table `EckwerteTabelleSTEA`), which the BA offers for automated retrieval. Every table is stored under its SHA-256 hash with its URL ([`src/jobease/official_vacancies.py`](src/jobease/official_vacancies.py)).
- **Rate:** vacancies ÷ unemployed × 1,000. Cities are ranked by this rate.
- **Not ranked:**
  - 10 cities that make up less than half of their district's population, such as Hannover in the Region Hannover. The district's figures mostly describe other places.
  - Köln: its October 2026 count (44,350, against 10,340 a year earlier) includes many Bundeswehr posts advertised for all of Germany, per the [BA Köln press release](https://www.arbeitsagentur.de/vor-ort/koeln/presse/2026-22-herbstbelebung-bleibt-schwunglos). Reviewed exclusions live in [`config/vacancy_exclusions.csv`](config/vacancy_exclusions.csv), each with a reason and a source.
- **Jump check:** a district whose vacancy count more than doubled in a year is flagged, and `jobease vacancy-index` exits with an error until the jump has been explained or the district excluded. Remscheid (420 → 970) is flagged: it stays ranked, and the table, map and summary show a note that no explanation has been found yet. Erfurt (1,140 → 2,220) is just under the threshold.
- **History:** unemployment for all ~400 districts, monthly, from January 2007 to October 2026. Every gap is explained by a district reform (for example Hanau became a district-free city in 2026, and Eisenach merged into Wartburgkreis in 2021), recorded in [`dbt/seeds/district_changes.csv`](dbt/seeds/district_changes.csv) with sources.

Every bug found during development has a test that keeps it fixed, for example AGS join integrity, a plausible unemployed-to-population ratio and districts matching the boundary file.

### Limitations

- **Registered vacancies are part of the job market, not all of it.** Not every employer reports every opening to the BA, and the share differs by sector. A city where employers report more often looks better.
- **One measure for all work.** This is the total across skill levels. The split by skill level is below, at Land level.
- **Where people live vs where they work.** Unemployment is counted where people live, but vacancies where the job is. Cities many people commute into can look better than the area around them.
- **Openings, not hires.** The rate says nothing about applicants per opening, pay, or how easy the jobs are to reach without a car.

## By skill level (October 2026)

The same rate, split by the BA's skill levels (*Anforderungsniveau*), for Germany and each Land. Source: "Arbeitsmarkt nach Berufen (KldB 2010)". The BA publishes no free split below Land level.

| Skill level | Unemployed | Registered vacancies | Vacancies per 1,000 unemployed |
|---|---:|---:|---:|
| Helfer (unskilled) | 1,491,232 | 112,031 | 75 |
| Fachkraft (vocational) | 826,597 | 396,673 | 480 |
| Spezialist | 229,907 | 84,469 | 367 |
| Experte (degree level) | 240,450 | 60,800 | 253 |

- **The level matters more than the place.** Helfer are 53% of the unemployed with a known skill level, but 17% of the vacancies. In office work the rate is 7 for Helfer and 140 for Fachkraft; in retail, 17 and 490.
- **Bayern leads at both entry levels** (Helfer 129, Fachkraft 690); Berlin is last at every level.
- **Checks:** the 16 Länder add up exactly to Germany for unemployed people. For job seekers and vacancies Germany is slightly higher, because it also counts people and posts that belong to no Land. Skill levels never add up to more than the total. Cells the BA suppresses stay unknown, never zero.

Models: `int_occupation_levels`, `mart_region_level_ease`, `mart_region_occupation_ease`.

### Earlier versions

The first version (6–7 Nov 2026) counted listings on the BA Jobbörse, the job board. The arbeitsagentur.de terms of use forbid automated reading of portal content for data collection, so that method was stopped on 8 Nov 2026 and its figures are no longer published. The code stays in the repo to document the method, with job-board access switched off in [`config/inputs.toml`](config/inputs.toml); every command that would call the job board refuses to run.

The two versions measure different things, but agree on the top three: Ulm, Würzburg and Erlangen.

## Stack

Python · DuckDB · dbt (dbt-duckdb) · Dagster · marimo · Observable Plot and D3. Everything runs locally; there's no cloud.

```
sources (BA statistics, Destatis, BKG)  →  Python parsers  →  DuckDB landing tables
  →  dbt staging → intermediate → marts (with data tests)
  →  official vacancy index  →  exports · notebook · map · tour video
```

Dagster drives the same steps as an asset graph (`make dev`).

## Run it

Needs Python 3.12.

```sh
make setup        # virtualenv, dependencies, headless Chromium for the video
make check        # lint, types, unit tests, dbt parse (offline, what CI runs)
.venv/bin/python -m jobease download-ba 2008 2025   # BA district issues, one per year (slow: the BA throttles)
make ingest       # load the BA issues, the Destatis municipality list and the BKG boundaries
make build        # dbt seeds, models and data tests
.venv/bin/python -m jobease vacancy-index           # fetch the BA vacancy tables (one per district)
make vacancies    # rebuild the vacancy index offline from the stored tables
make export       # data/exports/city_vacancy_ease.csv and summary.json
make notebooks    # the unemployment-history notebook → docs/notebooks/
make map          # docs/map/data.js; open docs/map/index.html
make tour         # the city-to-city tour → docs/tour/germany-job-ease-tour.mp4
make dev          # Dagster UI with the asset graph
```

The Destatis municipality list and the BKG boundary ZIP go in `data/inputs/` (paths in [`config/inputs.toml`](config/inputs.toml)).

## Layout

```
config/
  inputs.toml              every input path, column and parameter, in one place
  vacancy_exclusions.csv   reviewed districts left out of the ranking, with sources
src/jobease/
  sources/                 one parser per source: BA unemployment, BA occupations by skill
                           level, Destatis, BKG (and the switched-off job-board client)
  official_vacancies.py    the BA vacancy tables → the local city index
  vacancy_export.py        publishable files from that index
  map_export.py            the map's data, aggregates only
  raw_store.py             content-addressed copies of every input file and API response
  warehouse.py             DuckDB landing tables (written by Python, read by dbt)
  pipeline.py              ingest steps; the CLI and Dagster both call these
  tour_video.py            records docs/tour/index.html frame by frame to MP4
  orchestration/           Dagster asset graph
dbt/                       staging → intermediate → marts, seeds and data tests
notebooks/level2_analysis/ analysis notebooks (only the unemployment history is exported)
docs/                      map, tour and exported notebook
tests/                     Python unit tests (offline, synthetic inputs)
```

## Data and licences

- **Statistik der Bundesagentur für Arbeit** ([statistik.arbeitsagentur.de](https://statistik.arbeitsagentur.de)): registered vacancies and unemployed per district, and by occupation and skill level per Land. The rates, ranking and year-on-year ratios here are **own calculations**, not BA figures.
- **Destatis Gemeindeverzeichnis (GV-ISys):** residents per municipality.
- **© GeoBasis-DE / BKG (2026), [dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0):** VG250 boundaries.

Code: [Apache-2.0](LICENSE).
