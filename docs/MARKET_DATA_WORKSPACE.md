# QuantLab Market Data Workspace

This is the main user-facing workflow for source-backed historical data.
Open **Data Library → Download market data** in the React app. This guide
describes the current implementation, not a planned future capability.

## First-time setup (no existing dataset needed)

1. In **Get Data**, select **NIFTY 50**, **BANK NIFTY**, or **My stocks**.
   Search or paste exact NSE tickers for a stock universe. For an index, dated
   membership is required; today's members are not silently substituted.
2. Select your dates. The visible **Through date** is **inclusive**; the
   backend's **to_date** is **exclusive**. Daily is recommended for index and
   factor research; intraday frequencies can require many source requests.
3. Select a model optionally. QuantLab displays its real minimum return count,
   preferred **+20%** count and a conservative suggested earlier start date.
   This is an estimate; actual aligned observations are measured after download.
4. Read the source plan. If the public instrument catalog or dated membership is
   missing, use **Prepare missing sources**. This authorizes *public source*
   synchronization, not Dhan candles. It can fail if the upstream publisher is
   unavailable; the exact missing dependency remains visible.
5. If Dhan is not configured, click **Connect Dhan** and paste the token
   generated in Dhan Web. With your explicit consent, QuantLab verifies it
   against Dhan's read-only profile endpoint and stores the verified token
   in the ignored private local `.env` file (mode 0600 on Unix). The password
   field is not persisted in browser storage and the token never appears in
   job results. Renew expired Dhan tokens using **Replace token**. You can
   alternatively use the existing ignored `.env` workflow.
   **Verify access** and **Get & prepare data** use a live profile check.
   A token's mere presence does **not** prove Data API entitlement.
   A failed authentication or inactive historical data entitlement stops before
   a batch manifest is created.
6. **Get & prepare data** explicitly authorizes only the inspected scope.
   The backend recomputes a source-locked preview token and refuses changed
   dates, tickers, mappings or historical membership. If more than 100
   instruments or unresolved historical identities are involved, additional
   confirmation is required.
7. Continue in **Downloads & Jobs**. The existing Dhan downloader saves
   date-window checkpoints, reuses verified caches, records invalid OHLCV,
   and resumes incomplete batches. When *every* instrument succeeds, the
   original batch engine automatically builds a derived research dataset.
   If the batch has gaps, the UI permits an explicitly acknowledged partial
   preparation; it never marks that partial research as source-certified.
8. In **My Datasets**, open an available dataset in Model Laboratory or
   inspect missing inputs. Delete uses the existing dependency-aware,
   recoverable dataset confirmation; it never silently deletes original
   broker candle caches. Queues have their own Trash and restoration controls.

## Automatic model completion and safe secondary-source recovery

When you choose a compatible historical model in the new-data wizard,
**Get, prepare & run model** uses the same approved Dhan batch and proceeds to
Model Laboratory **only after the saved observations really satisfy the
preferred +20% sample requirement**. A missing or incomplete source produces
an `incomplete` diagnostic, not a simulated performance claim.
Stock-by-name and dividend-reinvested benchmark models still require an
explicit stock/benchmark selection; QuantLab never silently substitutes one.
An already saved dataset can be extended through **My Datasets → Extend /
complete**, which uses the model-specific input selector.

The primary Dhan batch remains the authoritative OHLCV cache. To enable
backup daily-close retrieval, connect Zerodha in **Advanced Data Tools →
Providers & sources** and authorize its use before starting a supported
daily batch. If that original Dhan batch has missing eligible securities,
the runner may attempt a separate Kite retrieval. An incomplete historical
daily batch also offers **Downloads & Jobs → Recover eligible daily closes
via Zerodha**, behind explicit authorization and a source-locked preview.

Both backup paths enforce an exact NSE/BSE Security ID, exchange token and
trading-symbol match; a current authenticated Kite session; and at least
three original Dhan sessions for a compatible price-overlap gate. Recovered
closes go only to the separate `dhan_shared` analytical dataset. The
original Dhan OHLCV and batch manifest stay unchanged, even if the Kite
download succeeds. Minute candles, reconstructed historical memberships,
dividend-reinvested TRI and trading orders are **not** backup products.
Recovery jobs are limited to 24 eligible securities and five calendar years
per approval; ineligible inputs display a blocker rather than trying to
replace a different instrument.

## Large-history safety

The planner shows a conservative **uncached upper-bound** estimate of
historical observations and storage size. Requests estimated at 1 GiB or
larger require an additional checkbox. Estimates over 40 GiB per job are
blocked and must be split into smaller user-approved jobs. These are
budgeting policies, not measured hardware limits or proof of Dhan entitlement.

Dhan original CSV checkpoints now check disk capacity before staging a
replacement; low space fails with an actionable error and preserves existing
SHA-verified original windows. The shared cache uses streaming hashes and
collapses multiple dated source windows into one read per original frequency,
reducing repeated scans. This **does not** establish a measured memory or
throughput guarantee on real multi-year minute archives. Only local tests
with genuine storage and brokerage access can establish those results.

## What is automated, and what is not

- **Automatic:** compatible, user-selected first-run model continuation when enough true
  aligned returns exist; original source inventory, dated index preview and exact
  Dhan instrument mapping; reuse of existing verified candle windows;
  source-quality checks; resumable batch manifests; automatic preparation
  of completely successful batches; read-only planning and model sample
  recommendation.
- **Approval required:** saving a verified token locally, public source synchronization, new broker history
  requests, unusually large batches and high disk estimates, incomplete
  index mapping, partial dataset preparation, deletion, and secondary-source usage.
- **Dhan** is the primary batch downloader. **Zerodha** is an optional
  secondary provider for eligible model extensions and explicitly authorized
  daily batch recovery, after exact source-identity and price-overlap checks.
  General index batches never silently route through Zerodha.
- Official NSE reference/MCP lookups **cannot replace** a licensed historical
  feed, independently audited point-in-time membership, publication-dated
  fundamentals, true delisted-security prices, corporate-action adjustments,
  or an official NIFTY TRI benchmark. Unadjusted daily OHLCV or index spot
  prices must not be labeled total returns.
- If historical membership is available only through an earlier date, **Use latest
  documented membership date** explicitly changes the requested date and
  rechecks the plan. No historical date window is truncated silently.
- A model's "+20%" preference is a target for **valid, aligned observed
  returns**. Requesting enough calendar days does not prove the target was met.
  Exact readiness still depends on genuine retained market observations.
- Provider login expiration, plan entitlement, and licensed data are external
  dependencies. QuantLab cannot guarantee an API never fails.

## Advanced access

The Market Data Workspace has three primary tabs: **Get Data**, **My Datasets**
and **Downloads & Jobs**. Use **Advanced Data Tools** at the bottom for:

- **Providers & sources:** official Zerodha sign-in, original CSV import and
  validated secondary-source append.
- **Detailed downloader:** legacy per-instrument Dhan controls and raw
  diagnostic records, retained for expert review.
- **Database Manager:** database explorer, integrity tools, source and
  provenance catalog, minute/depth tools, columnar cache and research
  readiness. Existing TRI ZIP/CSV import tools remain in the expandable
  advanced dataset area on the Data Library route.

All source and numerical calculations remain in the existing FastAPI pipeline.
The new UI does not store broker credentials in the browser or place trades.

## Test and local release gate

Run from the repository root:

```bash
npm run build
python -m unittest discover -s tests -p 'test_market_data_workspace.py' -v
bash run.sh
```

The full CI also runs the Python regression suite and Chromium UI acceptance.
Offline targeted recovery tests: `python -m unittest tests.test_market_data_completion_recovery -v`.
The browser test uses synthetic fixtures and mocked public-source setup, not
your authenticated Dhan account. Live entitlement and market-data completeness
must be confirmed on your own workstation.
