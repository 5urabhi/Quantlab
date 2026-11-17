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
