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
Live NSE_FNO option quotes and 20-level books require a separately
subscribed genuine Dhan option Security ID, a running authorized WebSocket,
and original observed packets. The market-status UI never presents stale
historical candle values as live prices.

## Trading Copilot V4 — separate live, replay, strategy and trading tasks

The current navigation is intentionally **not** one scrolling collection of
unrelated modules. Under the application's top-level **Intraday trading
cockpit** heading, a compact status bar shows three distinct facts:
(1) the weekday *regular index spot observation window* in IST,
(2) whether original Dhan WebSocket price observations are **actually fresh**,
and (3) whether the Dhan token is verified/near expiry.
Special exchange holidays are not silently guessed from weekday logic.
When opening the module, regular market hours or an already-running local
live feed prioritize the Live Trading tab; otherwise Market Replay opens.
An explicit manual tab selection is never overwritten by the clock.

| Workspace | Main intended use |
| --- | --- |
| **Live Trading** | Separate **Index Signal Monitor** and **BANKNIFTY Option Chain & 20-Level Depth** views. Select genuine expiry/CE/PE/strike, official master-based lot size and contract ID, preview premium outlay for lots, and connect the selected option to the existing 20-level feed. Actual freshness is independently checked; no broker order is placed. |
| **Market Replay** | Select a real recorded IST session, play/pause/step one minute at a time, choose replay speed and move the timeline slider. Each chart shows observations **only up to the replay cursor**, never future bars. Its **Recorded 20-level books** subtab inspects actual previously saved depth samples. |
| **Signal Backtest (Phase 1)** | Choose historical 1/3/5/6/10/30/60-minute signal horizons; see directional correctness, a clearly labeled non-executable ₹ index-exposure scenario with next-open entry/fixed exit and an equity curve, plus an entry/exit journal. Recorded forward-signal evidence remains a distinct 3/6-minute ledger. |
| **Trade Journal** | Manual options trades, actual entered premiums and exit results, plus a separate prospective index prediction accuracy ledger. Journal evaluations are not coupled to whichever historical chart was last opened. |
| **Connections** | Locally verify/replace Dhan token and client ID, see expiry, review one `dhan_shared` library, and prepare/fetch missing original index/equity minute files. Normal workflow never requires terminal API calls. |

The browser UI uses a shared `tradingCockpitApi` error helper. It converts
structured FastAPI/Pydantic errors (string, object, array, nested details)
into readable text, with source recovery actions. The old generic
`[object Object]` red error card is a defect, not a meaningful market
observation. Browser regression checks deliberately return a structured API
error and assert that the actual source issue is shown.

Replay source: `GET /api/trading-cockpit/historical/series`, bounded to 5,000
genuine local minutes, with per-session summary, original source label and
warnings. This endpoint never calls Dhan on view, does not fill missing
minutes, and cannot be interpreted as live prices.
Live recorded source catalog remains
`GET /api/trading-cockpit/live/capture-catalog`. Both read the same
underlying logical shared market library instead of manufacturing duplicate
named datasets.

## Evaluation workflow: directional skill and illustrative exposure

**Current user experience — Signal Backtest.** Choose an original Dhan
BANKNIFTY spot minute history window of 500, 1,500, 3,000 or 5,000
observations. Choose **1, 3, 5, 6, 10, 30 or 60 minutes (1 hour)** for the
historical signal-evaluation horizon and hypothetical holding period. The
existing live/prospective prediction ledger continues to record and evaluate
**only 3 and 6 minutes**. Adding historical horizons does not make the live
recording pipeline automatically support them.

Press **Run signal + trade simulation**. The first scorecard assesses whether
the fixed causal EMA/RSI UP/DOWN rule was directionally correct at the exact
future *index close* of the selected horizon. NO TRADE, flat, and missing
source observations are reported, never counted as correct hits. Directional
accuracy uses correct/(correct+incorrect); overlapping one-minute predictions
are statistically dependent and should not be treated as independent evidence.

The second scorecard and expanded **Illustrative Investment** view use the
*same original candles* to model a **non-executable signed-index-exposure
scenario** with transparent rules:

1. At the close of an observed source minute, determine UP, DOWN, NO_TRADE
   using only information from that minute and earlier observations. A
   completed candle becomes available at the **next minute boundary**.
2. When flat and UP, assume a hypothetical unleveraged LONG index proxy;
   when flat and DOWN, assume a hypothetical unleveraged SHORT index proxy;
   when NO_TRADE, stay flat. These proxies do **not** represent tradable
   BANKNIFTY index units, calls or puts.
3. Enter at the next **observed minute's open**, not at the historical signal
   candle's closing value. Enter only when that exact opening minute exists.
4. Exit exactly the selected **H minutes after entry**, at the observed open
   of that future minute. Ignore additional signals while the proxy position
   remains open. No overnight positions, no trading through the regular
   end-of-day cutoff, and no synthetic fills if even one source minute on
   the intended entry-to-exit path is missing.
5. Each closed trade hypothetically invests a configurable 1–100% of
   the previous simulated balance. With initial capital `C`, allocation
   `a`, direction sign `s = +1` for UP or `-1` for DOWN and assumed
   per-side cost `b` bps, the modeled cash change is:
   `C * a * [s * (exit_open/entry_open - 1) - 2b/10000]`.
   Trades are nonoverlapping, returns compound after each closed exit,
   and the displayed equity curve uses *only completed exits*. The maximum
   drawdown therefore excludes unrealized/intratrade losses.

The UI defaults to **₹50,000 starting capital**, **100% allocation** and
**0 bps** illustrative costs. These are adjustable scenario assumptions,
not a forecast, order-routing estimate, broker-execution model, or proof of
financial profitability. Fees, taxes, spread, slippage, financing costs,
intraminute execution, and real option price changes are not reproduced.
Where a future open is missing, the incomplete trade is excluded and counted;
the simulated balance must not be mistaken for an investable track record.
The historical accuracy horizon (measured at a future minute close) is
distinct from the hypothetical holding period (measured between two future
minute opens), so their individual outcomes need not match.

**Recorded forward predictions** below remain separate immutable prospective
evidence (3-minute and 6-minute) and are evaluated only against matching
broker-observed live or original prepared-file source data, never fabricated
from retrospective signals.

**Next phase — BANKNIFTY options P&L.** Mapping UP to a CE contract or DOWN
to a PE contract cannot establish ₹ P&L from underlying index price changes.
Actual strike/expiry-specific contract historical bid/ask, executable
premiums, execution times, lot quantities, spreads, fees and stop/target
behavior are required before any options win rate or option-equity curve
can be reported. The current scenario intentionally does *not* claim to
implement those instruments, stops, orders or fills.


## Multiple holding rules and preferred options scalp setup (November 19)

Under **Signal Backtest**, keep the index signal horizon separate from the
exit rule. The **Exit / hold rule** control offers fixed time (1/3/5/6/10/30/60
minutes), **until opposite signal or session end**, and **opposite signal or
time cap** (3/5/6/10/15/30/60-minute controls). After one replay the
**Compare all exit rules** table evaluates every fixed horizon, the pure
opposite-signal policy, and capped reversal at 10 and 30 minutes, plus the
user-selected custom cap. Same original causal EMA/RSI signal events,
historical window, illustrative starting capital, allocation and assumed
costs across the comparison. Policies may take different numbers of
non-overlapping trades; compare exposures and entry opportunity as well as P&L.

A signal at minute t is decided after that bar completes and enters on t+1
OPEN. For a long index-exposure proxy, a DOWN signal is the opposite; for a
short index-exposure proxy, an UP signal is the opposite. NO_TRADE is
neutral. A reversal decided on minute u exits only on u+1 OPEN, never using
the already-known close or later candles for an earlier fill. Capped reversal
exits on the earliest of the opposite-signal next open, the user-selected
time cap, or observed 15:29 IST open. Uncapped reversal requires a valid
opposite signal or an original 15:29 IST opening observation.
Incomplete paths or missing session-end observations are **excluded**, not
filled or carried to the next session. Every simulated trade exposes
`exit_reason` and `actual_hold_minutes`.

**Important:** The comparison is only a non-executable signed BANKNIFTY
index-exposure illustration. It does **not** claim the user could trade
the index directly or that any CE/PE premium gained the same percentage.

Under **Live Trading → BANKNIFTY option chain**, contract rows are ranked
by closeness to a user-editable **₹300 target LTP**, with initial ±₹50
tolerance and an optional "Only show premiums near target" filter. Users
can disable the filter to see every returned real contract. Default size
is **3 lots**, or 90 units **when the verified contract's lot size is 30**;
changing the selected CE/PE contract retains the 3-lot default.
Actual units, total estimated premium paid at the **best ask**, spread
cost and capital affordability use original Dhan instrument-master identity
and lot data. `LTP × quantity` is not an executable entry-price claim.
Broker fill, historical option fills, slippage and real options P&L
are not inferred from the spot index replay. The existing 20-level depth
selection stays read-only and requires a live Dhan F&O subscription.

## BANKNIFTY option chain, exchange lots and 20-level live depth

**BANKNIFTY is an index level, not a directly purchasable security.**
The index's original spot candles remain the input to the directional
signal. Contract-level execution research uses a real **NSE_FNO option**
with a specific strike, CE/PE type, expiry, official Dhan security ID,
lot size, and actual quote or order-book observations.

Under **Trading Cockpit → Live Trading → BANKNIFTY option chain &
20-level depth**:

1. Connect a valid Dhan access token and client ID under **Connections**.
   No credentials enter the React browser state beyond the secure local
   credential submission form; the chain/stream routes use existing local
   server environment variables. Real data access requires entitlement.
2. Refresh the expiry list from Dhan's read-only
   `POST /optionchain/expirylist` (underlying `IDX_I:25`). Never assume
   weekly BANKNIFTY contracts or generate expiration dates.
3. Load a current expiry's Dhan `POST /optionchain` REST snapshot:
   for each returned CE/PE contract view strike, LTP, best bid/ask,
   top quantities, OI, volume, IV, delta, and original `security_id`.
   REST snapshots are **not** live 20-level WebSocket packets.
   The server throttles provider calls and caches unchanged snapshots
   briefly (10s chain; 5m expiry list), displaying local receipt age.
4. QuantLab independently reconciles the Dhan chain security ID,
   strike, expiry and CE/PE with the locally downloaded official
   Dhan derivative instrument master (`data/dhan/instrument_master.csv`).
   Exact lot size is read from that contract's `LOT_SIZE` /
   `SEM_LOT_UNITS`. For example, the BANKNIFTY 2026 contract
   specification published by NSE is **30 units per lot**; do not
   hardcode that constant for historical or future contracts.
   If the master is absent, outdated or contradictory, the browser
   displays original quote information but **withholds** a verified
   security identity, lot size, premium-cost estimate and depth target.
   Refresh the Dhan master through Data Library.
5. Select **number of lots** and a paper capital budget. The app
   displays quantity = lots × verified contract lot size; estimated
   buy premium = observed best **ask** × quantity; and the immediate
   bid/ask crossing cost = (ask − bid) × quantity. Those are quote
   snapshots, **not actual broker fills**, slippage, brokerage,
   margin, tax or a guaranteed execution price.
6. Click **Use for live 20-level depth** to set that exact
   `NSE_FNO:<security-id>` as the depth target in the existing
   read-only Dhan WebSocket. Grant read-only streaming consent
   and click Start. There is just **one** selected live depth
   instrument at a time, and index spot has no order book.
   A subscription state is not a guarantee of fresh paired
   packets; the screen separately shows live feed status,
   receipt age, best bid/ask, 20 bid and ask levels and the
   underlying index's own freshness. Stop the current feed
   before switching to a different option contract.
7. **Prepare manual journal entry** copies only the exact
   option symbol, CE/PE side and multiple-of-lot quantity
   into the Trade Journal. The actual entry premium remains
   **empty** until you type a broker-confirmed fill. No broker
   order is submitted.

Dhan option chain calls are synchronized and rate-limited on the
local server; no authenticated vendor responses or secrets are logged.
Validated, normalized chain snapshots are persisted at most every
30 seconds to the existing single `dhan_shared` SQLite Market
Library under `option_chain_observations`. This does **not**
retroactively reconstruct historical option prices or every 20-level
book: only actually received observations are saved. The live depth
capture continues to use the pre-existing binary bid/ask packet pairing
and per-second bounded book recorder.

**Future historical options P&L** must use original options price
observations for the exact selected expiry/strike at each entry
and exit (ideally bid/ask and relevant book liquidity). A profitable
underlying-index prediction alone cannot establish a profitable CE/PE
trade. The historical index-exposure cash illustration in Signal
Backtest remains explicitly non-executable and separate.

## Dual-mode operation: historical + real-time Dhan

Trading Copilot now exposes **two independent data paths in one logical
Market Library (`dhan_shared`)**:

- **Historical:** original, SHA-locked Dhan minute candles, canonical shared
  stock-price history, deterministic 3/6-minute directional replay.
- **Live:** original Dhan WebSocket **ticker** updates on BANKNIFTY/NIFTY 50
  price index (`IDX_I`, identifiers 25/13), optionally together with a
  separate authenticated WebSocket for **20-level bid/ask order books**
  on a specific NSE equity or F&O contract. Only the selected contract has
  a 20-level order book: an INDEX itself is not an order-book instrument.
- **Persistent capture:** actual received ticker packets are deduplicated,
  source-labeled, grouped into 1-minute OHLC **without inventing missing
  observations or traded volume**, and stored alongside sampled original
  paired 20-level books in the existing `data/dhan/shared_market.sqlite3`.
  Original historical vendor files remain unchanged.

### In-app live workflow

1. Open **Trading Copilot → Connections**. Enter/replace your Dhan token and **numeric
   client ID** in the one-time local connection form. The backend verifies
   that the provided client ID matches the authorized Dhan broker profile
   before storing either in the private, gitignored `.env`. Neither
   credential is sent to user-facing reports, broker logs, GitHub, saved
   market evidence, or frontend localStorage.
2. Under **Live Trading → Configure live feed**, choose BANKNIFTY (default) or NIFTY 50 as
   your underlying signal source. To add real 20-level data, search a
   currently listed contract in the original Dhan instrument master and
   select its exact `NSE_FNO:<SecurityId>`, or enter an exact
   `NSE_EQ:<SecurityId>`. You may omit the depth identity if you only
   need the index's live price. The underlying and the option order book
   are separate subscriptions.
3. Approve read-only recording and click **Start live feed**. The Python
   backend opens the sockets and reconnects with bounded backoff. Server
   Sent Events push latest status/quotes/books to the React panel without
   refreshing unrelated controls.
4. The index LTP and market depth display actual packet arrival time and
   stale badges. A connected socket alone is **not** proof of fresh market
   data; stale/unavailable or non-market-hour packets do not receive
   a live-ready label. A 3/6-minute index rule requires **30 consecutive
   completed** observed 1-minute bars. Automatic predictive audits must be
   opted into separately. Manual trades remain manual and unverified.
5. Click **Stop streams** to stop; closing your browser tab does **not**
   interrupt the backend capture while the local Python server is running.
   Stopping the QuantLab server stops the capture. Previously recorded
   ticker minute observations and source-backed depth history remain.
6. Open **Market Replay → Recorded 20-level books** to run a source-
   limited directional replay against captured minute bars or inspect archived
   paired 20-level depth evidence. **Signal Backtest → Historical signal backtest**
   remains available while streaming is stopped.

### Real data / execution limitations

- **Do not** interpret an index-direction signal as a predicted or
  executable CE/PE premium. You continue selecting your option and
  entering actual filled prices manually.
- A historical Dhan minute-candle response does **not** include historical
  20-level order books. Only live books recorded since the user enabled
  recording, or separately imported *authorized original* order-book
  archives, are replayable. The live book is displayed from the newest
  paired original packets; storage samples at most one per second and
  retains no more than 30,000 per live session.
- Live ticker LTP updates are not necessarily every market transaction.
  Tick-derived OHLC is labeled accordingly, volume is not inferred,
  gaps are never forward-filled and invalid timestamp/price data is
  rejected. The Dhan v2 protocol also defines a separate **index
  response packet (code 1)** without a documented payload layout in
  the cited live feed reference. The decoder deliberately excludes
  unknown packet formats rather than interpreting arbitrary bytes as
  an index price. A broker-session smoke test during market hours is
  needed to confirm that the subscribed IDX_I ticker sends supported
  price packets on this account.
- Capture and replay are **read-only**. No Zerodha/Dhan order placement,
  automated exit, fill claim, realized option backtest, commission,
  historical Level 3 order book reconstruction or calibrated probability
  is implied. Genuine minute and depth market entitlements may differ.
- Live feed server and credential endpoints are intended **strictly for
  local loopback**. Never expose the local API through a public tunnel.
  Tests only use offline fixtures and mocks; they cannot certify account
  entitlements, current exchange hours or a real broker connection.

Official protocol reference: DhanHQ v2 Live Market Feed and Full Market Depth
documentation. These establish WebSocket authentication, ticker code 2,
20-level code 41/51 packet framing, subscription scope and limitations.

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
