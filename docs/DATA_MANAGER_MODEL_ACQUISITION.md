# QuantLab Data Manager — Model-driven acquisition and database inspection

This document describes the **actual implementation**, not a promise of
perfect external market-data availability or independently audited returns.

## Use the browser, not the terminal

Launch QuantLab as usual with `bash run.sh` and open **Data Library →
Data Manager**.

- **Datasets:** existing prepared research datasets; old import/delete/Trash
  controls remain in the expanded legacy section.
- **Get model data:** select a historical model and an original dataset.
  For a one-stock model, choose the exact series; QuantLab does not silently
  pick a different company. The plan reports observed return count, the
  model minimum, the preferred +20% target and estimated new Dhan requests.
  Click **Confirm & get missing Dhan data (+20%)** to authorize new read-only
  vendor queries, or **Reuse saved history** when the Dhan cache already
  covers the required window. Progress and completion are visible in-app.
- **Data Explorer:** inspect bounded pages of actual dataset CSV rows,
  structural data-quality samples, source metadata and saved dependencies.
- **Database tables:** browse explicit read-only columns from the shared
  market-data SQLite database, the research metadata database and the
  activity/recovery database. A fixed backend schema allows only known
  tables and fields, with exact-match filtering and pagination.
- **Sources & provenance:** source capabilities and explicit restrictions.
- **Activity & recovery:** persisted events, completed and interrupted jobs.

## One authoritative model data pipeline

The backend exposes:

| API | Responsibility |
| --- | --- |
| `GET /api/data-manager/model-catalog` | Registered models and required data mode |
| `GET /api/data-manager/acquisition-plan` | Read-only model-specific shortfall and source-chain plan |
| `POST /api/data-manager/acquisition/start` | Validate a SHA-256 preview token and user authorization, then start an existing model-data extension job |
| `GET /api/data-manager/database-catalog` | Allowlisted managed SQLite databases and safe columns |
| `GET /api/data-manager/database-table` | Read-only filtered/paginated data, never raw SQL |
| `GET /api/data-manager/overview` | Unified data and job status |
| `GET /api/jobs/{id}` | Existing persisted job progress |

`data_acquisition.plan` delegates numerical readiness and sample-size
requirements to the preexisting `model_data_manager.inspect` and
`single_series_completion.inspect`. The actual writer is the same preexisting
`model_data_manager.execute`. The two interfaces (Model Laboratory and Data
Manager) use one backend acquisition executor.

A model plan is a read-only calculation. It does not call Dhan or write market
data. Its SHA-256 preview token binds the selected model/parameters, data-source
identity, observed coverage and uncovered-window request scope. The server
rechecks the plan before enqueuing work; source changes require a new preview.

Source order for suitable Dhan historical models:

1. Existing prepared observation source.
2. Canonical identity-keyed, SHA-checked local Dhan candle caches.
3. New **authorized** Dhan daily-candle requests for uncovered windows only.
4. Revalidate actual available returns, not expected market sessions.

**No automatic interchangeable fallback** exists between spot index levels
and an official Total Returns Index, between present-day stock IDs and
historical delisted securities, or between NSE informational MCP and historical
backtest observations. Invalid or unauthorized sources remain blocked with
explanations. Timeouts and provider 429/5xx already use bounded transport retries.

## Security and failure protections

- No provider access in read-only data-plan or database-inspection endpoints.
- Credentials are never accepted from or returned to the browser.
- Database browser uses strict database/table/column allowlists, bound filter
  parameters, URI read-only mode and bounded pagination.
- Sensitive stored fields (e.g. `records.payload`, raw filesystem paths,
  broker diagnostics) are not in the read-only explorer.
- A partial download remains a partial original source, never a successful
  empirical study. Sample length does not establish investability, dividends,
  historical membership integrity or any trading profit.
- Original broker/source observations and all previously saved evidence remain
  immutable during model-driven extension.
- One click is enough to authorize the checked request, but an expired Dhan
  credential, missing entitlement or unavailable exchange history still
  requires authentic user/provider action.

## Scope and verification

The main-workstation regression suite and Ubuntu browser smoke tests cover
model planning, source-aware blockers, token invalidation, local table
inspection, pagination, sensitive-field protection and UI navigation. Tests
use mocked vendor calls and local fixtures, never a live Dhan account.

DuckDB/Parquet remains a potential **optional analytical cache** for later
work; SQLite is still the canonical shared source and no on-disk market-data
migration is performed by this change. Multi-provider historical vendor
failover must be added only with verified identity, adjustment and licensing
compatibility; data sources are never silently treated as equivalent.


## Next phase: compatible local alternatives (source fallback)

Go to **Data Library → Data Manager → Sources & provenance**.

The **Compatible source fallback** card accepts an **original UTF-8 CSV**
containing a YYYY-MM-DD `date` and original unadjusted `close`.
Select the *exact existing canonical* `NSE_EQ:<Dhan Security ID>` or
`BSE_EQ:<Dhan Security ID>` from the in-app instrument list and choose:

- An original Dhan export; or
- An original daily-close CSV obtained lawfully from a different provider.

Confirm the right to use the data and that the closes are unadjusted, then
select **Validate & append compatible source**. The local server (not the
browser) checks unique dates, finite positive prices, exact security identity,
the same unadjusted-close basis, **at least three matching Dhan sessions**,
and all overlapped prices for conflicts. All imported raw files and signed
receipts are kept locally. Conflicting sources or insufficient overlap remain
blocked evidence and are **not merged into canonical research observations**.
A compatible source may only append missing observations; existing prices
are never replaced. The check is a reproducible consistency gate, **not**
independent licensing or vendor certification.

This provides an in-app **authorized fallback for data the user has obtained**.
It does **not** add an unlicensed Yahoo scraper, an unlimited NSE candle
provider, automatic switching between different security-ID conventions, or
an entitlement to copyrighted exchange data. If a provider has no
compatible authenticated source, the interface explains the blocked step
instead of inventing observations.

## Next phase: optional local DuckDB / Parquet accelerator

Go to **Data Library → Data Manager → Fast analytics** and select
**Build / refresh Parquet cache**. The backend reads validated original
daily closes from `data/dhan/shared_market.sqlite3`, writes year-partitioned
ZSTD-compressed Parquet off to the side under the *ignored local*
`data/research_workspace/analytics_cache` directory, verifies that
every source row was transferred, and atomically activates a new generation.
No runtime DuckDB extensions or external network requests are needed.

The interface reports original SQLite size, compressed cache size, row count,
source freshness, searchable existing instruments and an interactive
read-only original-close chart with INR units. A changed SQLite file or WAL
makes the previous cache **stale**, so it cannot be queried as fresh market
data. After the cache is enabled, smaller canonical history updates through
the model-data acquisition and verified-source imports automatically refresh
it. For SQLite sources larger than 750 MB, refresh remains a visible manual
action to avoid unexpectedly exhausting local CPU/RAM/disk.

The columnar mirror accelerates **selective, source-checked historical
queries**; it does not silently replace the model runner, change benchmark
definitions, reconstruct the past, adjust dividends, or migrate the canonical
SQLite storage. No user dataset or market evidence can be deleted by
building or refreshing the mirror.

### Endpoints added in this phase

| API | Action |
| --- | --- |
| `GET /api/data-manager/fallback/registry` | Show known provider classes and compatibility policy |
| `GET /api/data-manager/fallback/receipts` | Show local source-import acceptance/blocking evidence |
| `POST /api/data-manager/fallback/import` | Validate and conditionally append one authorized CSV as a job |
| `GET /api/data-manager/columnar/status` | Inspect DuckDB availability and source fingerprint freshness |
| `POST /api/data-manager/columnar/build` | Build or rebuild versioned Parquet in a local background job |
| `GET /api/data-manager/columnar/instruments` | Search only canonical exact Security IDs |
| `GET /api/data-manager/columnar/series` | Query bounded original-close series through read-only DuckDB |

The Python integration tests use isolated SQLite fixtures and never require
broker access. Browser tests exercise these tabs without uploading fake
claims of verified outside-source authenticity.
