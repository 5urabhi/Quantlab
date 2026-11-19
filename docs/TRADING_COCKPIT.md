# QuantLab Trading Cockpit — first vertical slice

This module is a **local-only, read-only, explicitly unvalidated** intraday
research feature on the `feature/intraday-trading-cockpit-20261119` branch.

## Open the module

Run `bash run.sh`, browse to http://127.0.0.1:5173, then select
**Trading Cockpit** in the left navigation. The backend is the existing
FastAPI server at http://127.0.0.1:8765.

No synthetic prices are shown. Populate actual one-minute Dhan instrument
history via **Data Library -> Download market data** and build the
one-minute Parquet mirror before using the cockpit. The initial catalog
includes supported NSE_EQ / BSE_EQ instrument identities with prepared
one-minute observations. The Bank Nifty spot index and NSE_FNO option
contracts are **not** connected to this first historical candle catalog.

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
- A manual six-minute reminder timer. It is browser-local, starts only
  when clicked, and **does not place or cancel orders**.

## Critical limitations

- The existing one-minute Parquet store is an **offline prepared source**,
  not a streaming market data connection. The UI refreshes the backend
  snapshot but does not launch a broker live-feed recorder.
- Any source bar older than 120 seconds is shown as historical and cannot
  generate a new prospective prediction. A recent Parquet observation does
  not by itself prove a live quote or executable market.
- The initial chart is an SVG OHLC/EMA implementation rather than the
  future full trading-chart library with drawing tools.
- Session transitions, intraday signal calibration, option-market bid/ask,
  Greeks, transaction-cost simulation, position reconciliation, and
  trade-level win/loss reporting are **not implemented**.
- The prediction history is a local append-only-style journal via
  SQLite inserts and one-time outcome evaluation. It is not a tamper-proof
  or cryptographically signed record. SQLite back-up and source hashes
  are required for stronger audit guarantees.
- The reported directional score is an *operational ledger accuracy*
  over recorded observations. It is not a walk-forward or out-of-sample
  performance study, and it is not evidence of profitable short-term trading.

## API routes

- `GET /api/trading-cockpit/instruments`: prepared source catalog.
- `GET /api/trading-cockpit/snapshot?identity=NSE_EQ:...&limit=500`:
  observed source candles, indicators, and rule label.
- `POST /api/trading-cockpit/predictions`: record a **recent** prospective
  source-bar prediction with an explicit 3- or 6-minute horizon.
- `POST /api/trading-cockpit/evaluate`: update due outcomes using
  source-backed future bars. Missing evidence remains pending/unverifiable.
- `GET /api/trading-cockpit/predictions`: inspect immutable inputs
  and once-resolved evaluation results.

## Test and acceptance

```bash
python -m unittest tests.test_trading_cockpit
bash run.sh check
```

Accept only after these pass and the page is tested with genuine local
one-minute candles. A working interface is **not** a validated trading model.

## Next implementation milestones

1. Authorized Dhan streaming feed (and Zerodha secondary source), with
   instrument master resolution for Bank Nifty index, current futures,
   and option contracts; source freshness and session integrity checks.
2. Executable bid/ask quote capture, source-bounded six-minute position
   scenarios, real-cost calculations and a historical replay engine.
3. Day-level and horizon-level predictions with strict train/validation/test
   separation, probability calibration, walk-forward evidence and
   per-regime reporting.
4. Position import/synchronization and protective alerts in read-only mode.
   Broker orders are explicitly out of scope until separately authorized,
   reviewed and safety-tested.
