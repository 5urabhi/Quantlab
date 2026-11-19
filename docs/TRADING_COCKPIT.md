# QuantLab Trading Cockpit — read-only source and audit foundation

This module is a **local-only, read-only, explicitly unvalidated** intraday
research feature on the `feature/intraday-trading-cockpit-20261119` branch.

## Open the module

Run `bash run.sh`, browse to http://127.0.0.1:5173, then select
**Trading Cockpit** in the left navigation. The backend is the existing
FastAPI server at http://127.0.0.1:8765.

No synthetic prices are shown. Populate actual one-minute Dhan instrument
history via **Data Library -> Download market data** and build the
one-minute Parquet mirror before using the cockpit. The catalog includes supported NSE_EQ/BSE_EQ identities with prepared
one-minute observations. The Bank Nifty and Nifty 50 spot index entries
become usable only when an authentic **Dhan IDX_I one-minute historical
batch with matching SHA-256 manifest** exists in the local source library.
These are index spot values, **not live quotes or traded option prices**.
NSE_FNO options contracts are not yet connected to a streaming quote feed.

## One shared market library — resolving "source unavailable"

QuantLab's everyday market database is **`dhan_shared`** (canonical
daily-price history per exchange/Security ID). BANKNIFTY, NIFTY 50, sectors
and other groups are *dated views*, not one database for each universe.
The UI's **Download History** entries are retained original vendor receipts,
not user-facing datasets. Keep original per-batch evidence for existing
research runs; do not erase it during a migration.

Existing Dhan **one-minute** CSV+SHA files are distinct-resolution market
observations in the same logical library. Their regenerable Parquet chart
indexes are *not* separate datasets. Trading Copilot now lets you select
**Prepare cached minute instruments** to build up to 40 verified charts
from existing local originals without calling Dhan again. Subsequent small
(<=30 instruments) one-minute downloads prepare their charts automatically.
A budget guard skips oversized sources and reports them instead of
exhausting workstation storage.

When **BANKNIFTY spot** or **NIFTY 50 spot** is unavailable, the index does
not become ready just because its component stocks were downloaded. Trading
Copilot offers **Get missing index spot candles**, with explicitly chosen
dates (<=90 calendar days) and a read-only Dhan Data API entitlement check.
The source is original Dhan IDX_I data; no index levels are simulated from
the 14 bank stocks. No additional research dataset is created; the original
index-spot source receipt remains verifiable.

The Market Library now shows observed daily closes and one-minute source
readiness side-by-side for each equity. A prepared daily series alone cannot
power a 3/6-minute cockpit signal. Historical observations also cannot be
presented as current streaming quotes.

## Dhan token management (inside Trading Cockpit)

The **Dhan market data connection** panel calls the existing local-only
`POST /api/market-data/providers/dhan/connect` endpoint. Enter a fresh Dhan
Web token and explicitly approve local storage. The backend verifies it
against Dhan's profile endpoint and stores it only in the gitignored
project-root `.env`; the React UI never saves it to localStorage, logs,
reports, or a remote API.

The panel also calls the existing `GET /api/dhan/credentials/check` on
opening and roughly every 60 seconds while it remains open. Dhan's
`tokenValidity` is parsed in Asia/Kolkata; the backend returns only the
expiry timestamp and seconds remaining, never the token or account ID.
The panel displays **CONNECTED**, **EXPIRING SOON** (under one hour),
**EXPIRED / REJECTED**, or **UNVERIFIED / NEEDS ATTENTION**.
A network failure is *unverified*, not automatically *expired*.
The displayed countdown updates locally between broker checks.
The browser does not attempt autonomous credential renewal, because
renewal must follow the broker's authorized login flow.

**Security:** QuantLab is designed to bind to loopback only. Do not expose
its local API via a public URL, tunnel, shared proxy, or network interface.
Credential verification tests use mocked broker responses, never real tokens.

## Trading interpretation and backtests

The signal is calculated from original **BANKNIFTY spot index one-minute
candles** when available. It is not a prediction of a specific CE/PE
premium. You manually select the contract, expiry and strike in your
broker, then enter the *actual* filled option premium and quantity in the
journal. The journal records manual receipts only, and cannot execute
or independently verify those trades.

The historical **directional backtest** reuses the existing fixed-rule
replay. Choose 3 or 6 minutes and 500, 1,500, 3,000 or 5,000
source candles. It reports original-index direction accuracy by day,
counts skipped/no-trade and unverifiable bars, and never mixes
retrospective results with the prospective real-time prediction ledger.

This is **not yet an options P&L backtest**. A credible executable
options backtest would require time-aligned historical contract symbols,
expiry, bid/ask or realistic fill assumptions, spreads, fees, actual lot
sizes, and contract turnover. Do not apply BANKNIFTY spot point changes
to the manually entered option premium as if they were equivalent.

## What works now

- Stable React cockpit panel with source-backed one-minute OHLC chart,
  hover OHLC, 9/21 EMA overlays, RSI(14), and ATR(14).
- A conservative deterministic direction baseline. `UP`, `DOWN`, and
  `NO_TRADE` are **unvalidated technical rule classifications**, not
  profitable trade recommendations or model probabilities.
- A 3/6-minute prediction ledger that captures the model version,
  original timestamp, last observed close, direction, features and source
  status. Repeated records for the same model, instrument, horizon, and
  source bar return the original saved prediction.
- A due-horizon evaluator that scores underlying direction only when
  real minute observations exist. NO_TRADE and unverifiable gaps are not
  counted as direction wins.
- An opt-in, browser-open auto-audit that deduplicates both 3/6-minute
  predictions and evaluates due outcomes on each interval while the page is
  running. A historical/stale source cannot become a prospective prediction.
- An IST-day scorecard over prospective records with separate correct,
  incorrect, no-trade, flat, pending and missing-evidence counts.
- A source-anchored historical 3/6-minute replay, computed without future
  price information in the signal features and **never counted as live calls**.
  The fixed rule is not fitted or independently validated, and the replay
  does not contain options transaction prices or profits.
- A local manual long CALL/PUT journal using actual *user-entered* entry
  and exit premiums, quantity and optional charges, with explicit
  >6-minute holding-discipline flags and daily net realized totals.
- A manual six-minute reminder timer, saved locally across page refreshes.
  It starts when clicked or after recording a manual entry and **never
  places or cancels broker orders**.

## Critical limitations

- The existing one-minute Parquet store is an **offline prepared source**,
  not a streaming market data connection. The UI refreshes the backend
  snapshot but does not launch a broker live-feed recorder.
- Only an original, market-hours candle between **60 and 90 seconds
  old**, assumed stamped at the *start* of its one-minute interval,
  can generate a new prospective local snapshot; the observation window
  is deliberately narrow to limit stale-bar horizon bias. That still does not
  prove a live quote or an executable option fill.
- The auto-audit is active **only while its page remains open** and the
  user enables the switch. It cannot replace a dedicated server-side
  broker WebSocket recorder or survive browser closure.
- RSI/EMA/ATR and directional classification reset across missing-minute
  gaps and Indian trading sessions. No nonexistent minute is imputed.
  NSE holiday/calendar entitlement checks and real-time feed validation
  remain to be implemented.
- The initial chart is an SVG OHLC/EMA implementation rather than the
  future full trading-chart library with drawing tools.
- Calibrated intraday predictions, real-time option bid/ask, Greeks
  within the cockpit, actual broker position reconciliation, transaction-cost
  backtests and live trade execution are **not implemented**.
- The manual option journal computes P&L from user-entered prices and
  server receipt timestamps. These are **not broker verified fills**, and
  the software cannot guarantee actual stop-loss/time exits.
- The prediction history is a local append-only-style journal via
  SQLite inserts and one-time outcome evaluation. It is not a tamper-proof
  or cryptographically signed record. SQLite back-up and source hashes
  are required for stronger audit guarantees.
- The reported directional score is an *operational ledger accuracy*
  over recorded observations. It is not a walk-forward or out-of-sample
  performance study, and it is not evidence of profitable short-term trading.

## API routes

- `GET /api/trading-cockpit/instruments`: source-aware equity and spot-index catalog.
- `GET /api/trading-cockpit/snapshot?identity=NSE_EQ:...&limit=500`:
  observed source candles, indicators, and rule label.
- `POST /api/trading-cockpit/predictions`: record a **recent** prospective
  source-bar prediction with an explicit 3- or 6-minute horizon.
- `POST /api/trading-cockpit/evaluate`: update due outcomes using
  source-backed future bars. Missing evidence remains pending/unverifiable.
- `GET /api/trading-cockpit/predictions`: inspect immutable inputs
  and once-resolved evaluation results.
- `POST /api/trading-cockpit/monitor/tick`: opt-in browser-session
  observation/dual-horizon recording and exact-source evaluation.
- `GET /api/trading-cockpit/report`: prospective IST-day source-bound reports.
- `GET /api/trading-cockpit/replay`: fixed-rule mechanical historical
  replay with missing-minute and session safeguards.
- `GET /api/trading-cockpit/trades`, `POST /api/trading-cockpit/trades`,
  `POST /api/trading-cockpit/trades/{trade_id}/exit`: purely local manual
  option-trade receipts, no broker API write.

## Test and acceptance

```bash
python -m unittest discover -s tests -p 'test_trading_cockpit.py' -v
bash run.sh check
```

Accept only after these pass and the page is tested with genuine local
one-minute candles. A working interface is **not** a validated trading model.

## Next implementation milestones

1. Authorized Dhan streaming feed (and Zerodha secondary source), with
   instrument master resolution for Bank Nifty index, current futures,
   and option contracts; exchange timestamps, latency/freshness and
   session integrity validation. Existing historical IDX_I support does
   **not** satisfy this live-feed milestone.
2. Executable bid/ask quote capture, source-bounded six-minute position
   scenarios, real-cost calculations and a historical replay engine.
3. Day-level and horizon-level predictions with strict train/validation/test
   separation, probability calibration, walk-forward evidence and
   per-regime reporting.
4. Position import/synchronization and protective alerts in read-only mode.
   Broker orders are explicitly out of scope until separately authorized,
   reviewed and safety-tested.
