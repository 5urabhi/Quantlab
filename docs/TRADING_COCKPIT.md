# QuantLab Trading Cockpit — read-only source and audit foundation

This module is a **local-only, read-only, explicitly unvalidated** intraday
research feature on the `feature/intraday-trading-cockpit-20261119` branch.

## Run the current trading acceptance check (implemented)

Open **Trading Cockpit → Connections → Check my trading system → Run local
checks**. This single read-only check reports whether original BANKNIFTY
minute observations exist, whether Dhan's official CE/PE contract master is
fresh, whether the automatic 20-level feed is receiving full books, and
whether original CE/PE sampled book pairs in `dhan_shared` match their
source SHA-256 receipts. The Dhan profile check is a separate authorized
verification call; neither operation places orders. It does **not**
claim 20-level entitlement from a historical Data API subscription.

After running the options backtest, use **Download safe backtest diagnostic**
to share actual signal/reversal causes without sharing raw candles or
account credentials. See [Local trading acceptance — five steps]
(TRADING_LOCAL_ACCEPTANCE.md) for what to click and what each state means.

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
| **Options Backtest — one trading workflow** | Primary screen: choose historical BANKNIFTY minutes, preferred CE/PE premium (~₹300), three lots, starting account, exit strategy and holding period; click **Run options backtest** to compare option P&L. Open **Advanced contract and cost settings** only when needed. Historical index-only directional validation and the recorded forward-signal ledger remain optional collapsed research panels. |
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

**Optional index-only research within Options Backtest.** Choose an original Dhan
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

## Automatic BANKNIFTY CE/PE 20-level recording (opt-in, implemented)

**Open Trading Cockpit → Live Trading → BANKNIFTY option chain & 20-level
depth → Record BANKNIFTY CE & PE order books.**

1. Keep the local QuantLab backend running and configure your Dhan token and
   client ID in its ignored .env file. Verify **full market-depth entitlement**;
   the historical Dhan Data API subscription alone does NOT establish this.
2. The defaults are **target option LTP ₹300**, premium tolerance **±₹75**,
   **2 CE and 2 PE** contracts, **3 lots**, and a persisted sample of at most
   one genuine paired order book every **3 seconds per contract**.
3. Tick the explicit authorization box, then click **Arm automatic 20-level
   recording**. QuantLab remembers that permission on your local machine. If
   the server runs during a regular NSE weekday trading session (09:15–15:30
   IST), it starts the recorder; outside those hours it stays armed without
   issuing vendor requests. Broker holidays and special sessions are not
   guessed—the feed must actually deliver valid packets. If the local
   backend stops, no depth is recorded.
4. QuantLab refreshes the official Dhan BANKNIFTY expiry and option chain
   approximately every **75 seconds**, selecting the closest contracts near
   the target premium by **original Dhan option LTP and positive volume**.
   It only accepts an exact fresh **NSE_FNO** ID, expiry, CE/PE, strike and lot
   from the official Dhan instrument master; it refreshes missing/stale
   master data atomically. If an updated selection changes the real contract
   IDs, the recorder reconnects the 20-depth WebSocket with the updated list.
   At most **six** contracts are subscribed in one connection (Dhan supports
   up to 50 on a 20-depth connection). A little selection hysteresis avoids
   excessive switching. Missing data stays missing.
5. The backend joins Dhan's actual 20 bid and 20 ask levels **by security ID
   and receive time**. Only paired original packets no more than one second
   apart form an accepted snapshot. For each valid sampled packet pair, it
   stores complete original 20-level price/size/order arrays, raw pair SHA
   digests, exact instrument metadata and separate derived research features.
   Samples are keyed by local UTC receive time, **not exchange event time**.
6. Status shows per-contract freshness, spread in bps, 20-level imbalance,
   bid/ask quantities and illustrative weighted average prices for buying
   or selling **3 × the master-verified current lot size** (e.g. 90 units
   only when the master confirms 30 per lot). If the original 20 levels lack
   enough quantity, weighted price is **unavailable**, not guessed.
7. Click **Review saved depth** to inspect the captures in Market Replay.
   Original JSON books go into the existing `live_depth_books` table of
   `dhan_shared`; contract-selection evidence goes into
   `auto_banknifty_depth_selections`; derived numeric book features go into
   `auto_banknifty_depth_features` in the **same shared SQLite database**.
   You can run queries, chart metrics or use original records in future
   offline ML/RL research without creating duplicate historical datasets.
8. Click **Stop and disarm recording** to stop current and future automatic
   sessions. Captured observations remain available. A persisted opt-in
   resumes only when your local QuantLab server starts.

**Data and safety limits:** Recording is read-only. There are NO order API
calls, automatic trades, synthetic order books, dealer fills, or promises of
historical 20-level data. Order-book freshness depends on original Dhan
packets and your separate market-depth entitlement. Defaults sample (not
archive every tick); there is a hard ceiling of 100,000 persisted depth
snapshots per IST day to prevent unbounded storage. The collector respects
regular NSE clock hours and reconnects on interruptions. Depth VWAP is an
indicative displayed-book liquidity model; queuing, partial fills, latency,
impact, cancels and taxes are not verified. True historical order-book data
starts only **after** the first successful live capture.

Dhan documentation: https://dhanhq.co/docs/v2/full-market-depth/
and https://dhanhq.co/docs/v2/option-chain/.

## Pure 9/21 EMA crossover strategy (read-only option backtest)

**Trading Cockpit → Options Backtest → Strategy signal → EMA crossover ·
9 red / 21 green** tests the original one-minute BANKNIFTY underlying
(index security ID 25). It is **not** the existing EMA+RSI classifier,
which remains available in the adjacent dropdown.

Pure crossover rules:

- 9-EMA (red) strictly crosses **above** the 21-EMA (green) on a fully
  observed completed one-minute candle: emit one **UP** event. Under the
  reversal exit rule, open a long **CE** at the *next* observed option
  candle OPEN; no naked option selling.
- 9-EMA crosses **below** 21-EMA: emit one **DOWN** event. Exit an
  existing long CE and, only if separate genuine put prices and capital
  exist, open long **PE** at that same next original minute's OPEN.
- When there is no actual crossing, emit NO_TRADE (hold or stay flat).
  Never buy a new option merely because 9-EMA remains above/below 21-EMA.
- All EMAs are seeded from original index closes. Reset at each new NSE
  session and any missing one-minute index candle. No lookahead, overnight
  indicator stitching, synthetic contract candles, or same-close fills.
- **Exit rule:** choose *Flip CE ↔ PE on opposite signal* for crossing-only
  reversals; use *Flip on opposite signal or time cap* (maximum 6 minutes)
  to compare with the user's brief holding style; *Hybrid* additionally
  evaluates completed option premium stop/target conditions under
  explicit next-open proxies.
- Underlying crossover signals and historical **option premiums** remain
  separate. Dhan original exact-strike CE/PE contract minute bars drive
  simulated option P&L, subject to source gaps, lot/expiry provenance,
  quoted volume, user-selected slippage and fees.
- The **Live Trading** monitor currently uses the separate EMA+RSI
  baseline. Selecting this historical strategy does **not** authorize
  a live broker trade or install a live EMA alert.

**How to evaluate:** select the model and historical window, keep near
monthly expiry, preferred ₹300 premium and explicit lot size/cost
assumptions, run the read-only options backtest, then inspect CE↔PE flips,
number of *distinct crosses*, skipped real option entries, after-cost
P&L and drawdown. Compare its results to an identical EMA+RSI run on
exactly the same source period and exit rule. Do not rely on simulated
OHLC opens as guaranteed fills. Begin with paper trading.

## One-screen options backtest: BANKNIFTY signals buy historical CE/PE contracts

**Default continuous-reversal research rule.** The fixed-hold selector
is disabled when the selected rule is signal reversal, because 1/3/5/6/10/30/60
minute durations do not determine when a reversal-only position exits. Those
fixed-time scenarios are still independently evaluated in the comparison
table. UP → long CE; at the
first completed DOWN signal close the CE at the next observed minute OPEN
and **buy a newly selected PE at that exact same OPEN**. On the next
completed UP signal, close the PE and buy a newly selected CE at that
same next observed OPEN. Each replacement strike is independently chosen
from that option side's original signal-minute close (~₹300 default),
so the new PE does not inherit the previous CE's strike. NO_TRADE is
neutral and does not close or reverse a position. Reversals do not
overlap positions: closed trade P&L and fees are recorded before buying
the replacement. The buy is allowed only when there is a real historical
entry/exit path, original option volume and sufficient simulated account
balance. If the replacement option lacks data or cannot be afforded,
the previous side still exits, but the next trade remains unscored
until a later eligible signal. For fixed-time, stop/target or time-cap
exits, a coincident opposite signal does not automatically enter at
the same opening; explicit opposite-signal reversal triggers are required.
All transitions are **hypothetical read-only next-open executions**, not
broker orders or verified fills.

### Historical options → research and RL readiness (implemented audit, no training)

The historical options results now include **Signal reversal diagnostics and RL
training readiness**. This is a read-only source audit executed on the same
original Dhan/index candles used by the backtest. It answers these questions
*before* a user is tempted to optimize returns or train an RL agent:

- **How many distinct UP↔DOWN changes actually occurred?** The EMA/RSI
  classifier runs on *every completed minute*. Its 1,000 labels across a
  nine-session sample do not imply 1,000 independent direction reversals or
  entry opportunities. NO_TRADE is neutral and within-day direction changes
  are counted only when a new actionable label differs from the prior one.
- **Was an original CE/PE available near the selected premium at the signal?**
  A source quote must exist at the completed signal candle with positive
  volume, near the chosen ₹300 ± tolerance; the same actual strike/security
  must then have a valid NEXT minute OPEN. The audit reports how often this
  succeeds. This availability measure is separate from the much stricter
  requirement that *every minute* of the eventual trade path is observed.
- **Why did the exit-and-flip strategy show zero flips?** Every selected
  simulated position reports whether it exited because of an opposite signal,
  whether a same-open replacement was attempted, whether it became a scored
  CE or PE, and which rule rejected replacement (missing option near target,
  missing next OPEN, insufficient paper cash, incomplete exact-contract path,
  zero volume, session cutoff, or position still open). Zero flips with zero
  opposite exits is fundamentally different from zero flips with two rejected
  PE/CE replacements.
- **Are we ready to train/validate an RL policy?** The audit counts
  *independent trading sessions*, original index minutes, option
  contract/session identities, real distinct signal runs and aligned
  source observations. Prototype/readiness planning targets of 30 sessions
  and research planning target of 250 sessions, 100 real direction changes,
  and ≥90% option-entry coverage are **project-defined heuristics**, not
  statistical guarantees. Historical option OHLC alone does **not** make
  an execution-grade RL system ready. The API explicitly reports
  `training_performed: false` and `research_grade_rl_ready: false`.

**Proposed future model sequence (not claimed as implemented RL):**

1. **Fix the baseline evidence first.** Validate that the same EMA/RSI
   signals, fixed-horizon and CE↔PE rules all use identical original option
   data, side-specific contract selection, 3 lots, source-matched fees and
   no overnight trading. Reconcile missed trades and unscored reasons.
2. **Supervised prediction baseline.** Train on lagged BANKNIFTY returns,
   EMA/RSI/ATR/realized-volatility, time-of-day and source-dated option
   premium/volume/IV/OI where available; forecast directional *probability*
   or net-after-cost CE/PE outcome, not a certain sign. Evaluate calibration
   and costs on later dates only. Missing source fields are masked rather
   than replaced with fictitious observations.
3. **Contextual bandit/position gate.** Choose among FLAT, CE and PE with
   action masks for an absent contract, a rejected premium, insufficient
   capital or a market/session boundary. Compare with always-flat, fixed
   1/3/5/6/10/30/60-minute exits and opposite-signal switching.
4. **Offline RL only after enough sessions and contract coverage.**
   Prototype discrete-action DQN/QR-DQN or action-masked PPO in an isolated
   *historical paper environment*. State contains only data available when
   decisions were made. Actions are FLAT, BUY CE, BUY PE, HOLD and EXIT/FLIP,
   never undocumented broker orders. Reward is change in paper portfolio
   value minus explicit fees/slippage and risk penalties. Episode boundaries
   are NSE sessions; no overnight positions. Use chronological train /
   validation / untouched test days, multiple seeds, walk-forward
   retraining, and per-regime negative-control comparisons.
5. **Paper-trade live observations** against future index/option tapes,
   timestamped bid/ask, book liquidity and exact lots before considering
   broker execution. Historical OHLC cannot certify fill probability or
   exact intraminute stop orders. Nothing currently authorizes live orders.

A current window of only nine sessions and tens of thousands of
multi-contract minute bars is enough to test the research infrastructure,
but **not enough to claim a trained strategy generalizes**. Prefer expanding
the genuine historical data and preserving source versions over generating
synthetic options returns or fitting a large policy on these nine days.

**Open Trading Cockpit → Options Backtest → Run options backtest.**
The CE/PE simulation is the primary workflow. Index-only directional
accuracy and recorded prospective signal audits remain available under
optional expandable sections, but never have to be run first.
The workflow is now:

1. Use the same **original Dhan BANKNIFTY index 1-minute candle** sequence
   and causal EMA9/EMA21 + RSI signal to decide UP/DOWN/NO_TRADE.
2. An **UP signal means search historical CALL (CE)**; a **DOWN signal
   means search historical PUT (PE)**. NO_TRADE means stay flat.
   **If original BANKNIFTY index minute history is entirely absent**, the
   same authorized one-click run first downloads up to the latest 36 calendar
   days of original Dhan IDX_I candles and prepares the shared library view.
   This is only a missing-source recovery: a SHA-256 mismatch, corrupt
   source or an intentionally selected older series is never overwritten.
   Missing Dhan authorization is reported as an actionable error.
3. The app automatically reads prior Dhan `POST /v2/charts/rollingoption`
   receipts from the local market-data library and fetches missing calls using
   the local Dhan token when you press **Run options backtest · compare exit rules**.
   Default request: `securityId:25`, `exchangeSegment:NSE_FNO`,
   `instrument:OPTIDX`, `expiryFlag:MONTH`, **`expiryCode:1` for near expiry**,
   `interval:1`, `drvOptionType:CALL/PUT`, ATM±3. Each Dhan request
   covers at most 30 calendar days; limits protect against request floods.
   Important: Dhan uses **1=near, 2=next, 3=far** for the expired-options
   `/charts/rollingoption` endpoint, even though its generic API annexure
   uses **0=near, 1=next, 2=far**. QuantLab retains the same 0/1/2 UI
   choices for active contracts, translating them to 1/2/3 only when
   requesting rolling expired options. Dhan support explicitly confirmed
   this endpoint-specific distinction in January 2026. Invalid code zero
   returned HTTP 400/DH-905 on a real connected account.
   The backtest attempts to refresh an absent or stale original Dhan
   instrument master automatically before fetching recently active
   contracts. If Dhan rejects a request, the UI shows a safe vendor error
   code and requested expiry/strike/date context; credentials are never
   exposed. Monthly and near expiry are defaults. Optional weekly/next/far series
   are exposed only as Dhan request selections; absence of vendor data is
   reported, never filled. The endpoint requires the user's own Data API
   entitlement; no credential is sent back to the browser.
4. From the *completed index signal minute*, find a contract of the correct
   option side with **observed historical option CLOSE** nearest ₹300 within
   ±₹50, considering only the requested ATM-relative strikes and positive
   recorded volume. This selects the strike with information available *before*
   the entry. Then assume entry at the **next observed option minute OPEN**,
   with explicit user-controlled slippage. Do not select a strike using
   future exit performance.
5. Convert option units from **three lots × historical assumed lot size**
   (default **30 assumed units per lot** => 90 units). Dhan's rolling
   endpoint does not certify historical lot sizes. Users must verify this
   assumption for their dates. Require sufficient modeled cash to purchase
   the chosen option contract and model brokerage separately.
6. For an opened position, track the **same actual strike, same CE/PE side,
   and same market session** across every minute until exit. When the ATM
   *relative label* moves, matching is by actual `strike` values returned
   by Dhan, NEVER by the moving ATM label. The API gives a rolling expiry
   family rather than immutable expired contract IDs, so a cross-session
   contract identity or exact historic expiry is not proven. Never carry
   positions overnight or silently swap contracts. Contradictory vendor
   duplicates and missing minute paths are excluded. An incomplete opened
   position blocks the remainder of that day's entries.
7. Exit on fixed 1/3/5/6/10/30/60-minute holds, an opposite completed
   BANKNIFTY signal, a reversal/time-cap hybrid, an **option-close-triggered
   +5% / −2.5%** target/stop, or a combination. A signal or option-close
   trigger at minute `t` can only exit at minute `t+1` OPEN. These are not
   real stop-order fills: the price can gap through the trigger. The API
   enforces the observed 15:29 IST opening as the session cutoff.
8. Compare trade counts, option-premium ₹ P&L, selected exit reasons,
   realized-balance return, average hold, conservative no-data exclusions
   and closed-trade drawdown, using the **same original spot signals and
   chosen premium/size/capital/cost settings** for each policy. Quotes and
   source receipts are historical, stored locally with SHA-256 checks;
   results are **hypothetical next-open execution proxies**, not orders.

**Read-only API:** `POST /api/trading-cockpit/options/backtest` with
`confirm_readonly=true` starts a bounded local job. The UI polls
`GET /api/jobs/{job_id}` for progress/results and remembers in-flight
job identifiers across tab switches. No order placement or automatic trading
API calls exist in this workflow.

**Currently active option fallback.** Dhan's expired-options endpoint may
not return a contract that has not yet expired. QuantLab first examines the
original, fresh (<48 hours) Dhan NSE_FNO instrument master for eligible
BANKNIFTY monthly contracts near the observed BANKNIFTY spot and the
selected near/next/far expiry series. It downloads the original individual
active-contract one-minute series from `POST /v2/charts/intraday`,
using the master-provided exact security ID, strike, expiry and lot size.
This active route applies only to recent sessions (30-day bound), never
uses today's master to manufacture past expired contracts, and reuses
SHA-checked cached sources. Active contracts with genuine security IDs are
preferred over rolling strikes when both exist; a trade must remain on
that exact ID throughout. **Never** fall back to the expired-options
endpoint for a session whose chosen monthly contract has not yet expired.
When the original active source is missing/incomplete, QuantLab reports the
missing contracts and stops or marks those signals unscored. It does not
treat Dhan HTTP 400 as proof that current options are expired.

**Historical split and November 2026 fix.** Dhan's rolling endpoint may be
called only for a calendar prefix whose selected contract has passed its
monthly expiry. QuantLab uses the last-Tuesday monthly rule as a conservative
guard, allowing for exchange holiday shifts to an earlier day; it does NOT
replace the master for actual expiry identification. For a BANKNIFTY window
of November 6–19, 2026, the November monthly series has not expired
(November 23 holiday-adjusted), so the simulator must only use current
listed-contract candles. The prior implementation retried
`/charts/rollingoption` on the entire window when even one currently
active contract was missing; this sent a forbidden current-month request and
surfaced Dhan HTTP 400/DH-905 despite an active Dhan data subscription.
That fallback has been removed. Contract matching also uses all official
compact-master symbol columns, including the Dhan custom symbol when the
exchange trading symbol is blank. Users see source and routing counts and a
direct action to refresh the official instrument master when needed.
The exact original 400 cause cannot be certified without the private
vendor response; QuantLab now includes allowlisted error-message details
without exposing token/account data.

Active option IDs support source-certified current lot sizes; expired
rolling history still needs explicit historical lot-size assumptions.

**Evidence and economic limitations:**
- Historical Dhan rolling OHLC/volume/strike observations have no historic
  bid/ask, 20-level book or proved executable fills. Displayed assumed
  per-side slippage and brokerage are user-set, not Dhan-verified fills.
- The rolling expiry code does NOT prove immutable expired contract identity,
  actual per-bar expiry date, or that its series can be treated as a single
  listed contract across multiple sessions. The backtest uses only intraday
  same-strike comparisons and explicitly flags this limit.
- Historical lot size is a user assumption, not a verified exchange record
  for the backtested dates. The ₹300 selection refers to the signal minute's
  last option premium, not a guaranteed entry at exactly ₹300.
- The +5%/−2.5% policy is based on a *completed option candle CLOSE*,
  followed by assumed next-minute OPEN execution. It is not a tick-level
  or intrabar stop/target fill.
- Taxes, statutory levies, impact of the bid/ask spread, broker rejection,
  quote latency and partial fills are not reproduced. Closed-trade drawdown
  does not include intratrade losses. No Dhan plan/credentials or original
  vendor observation has been validated in CI; tests use *offline
  clearly labeled fixtures*, never fabricated production backtest results.
- Missing options data means **unscored**, not zero P&L or a successful
  simulation. Fetch/inspect original Dhan data and lot-size evidence before
  treating results as decision-grade.

Source specification: https://dhanhq.co/docs/v2/expired-options-data/
ExpiryCode semantics: https://dhanhq.co/docs/v2/annexure/

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

**Historical options P&L research now uses Dhan option-minute OHLC**
for the same selected strike and CE/PE side across each simulated
trade; improving historical bid/ask and book-liquidity modeling remains future work. A profitable
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

The **separate historical options backtest is now implemented above the
index-only research panel**. It maps the same original BANKNIFTY signals
to time-aligned Dhan historical option-premium OHLC observations, models
three-lot CE/PE trades with explicit fill and cost assumptions, and
compares exit policies. This is a *paper trading proxy*, not verified
executable broker P&L: historical bid/ask/20-level depth, fill priority,
taxes, exact expired contract identifiers and historical lot sizes remain
limited or unavailable. Never substitute index points for option premiums.

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
