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
- Only an original, market-hours candle between **60 and 180 seconds
  old**, assumed stamped at the *start* of its one-minute interval,
  can generate a new prospective local snapshot. That still does not
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
