# QuantLab Spread Trading Studio — automatic research workflow

## Two distinct engines

Open **Trading → Liquidity & Spreads**. The workspace now includes:

- **Live Spread Monitor (Bid–Ask Capture)**: automatically inspect source-verified quotes, test lot sizes under your available premium budget, estimate expenses and failed-exit losses, screen and sort research candidates. Opening a candidate starts the execution-cost simulator automatically.
- **Multi-Leg Option Spreads**: automatically construct defined-risk verticals, iron condors and butterflies from original saved Dhan books. Four submodules: Auto Discover, Build & Modify, Payoff & Execution, Research Notebook.
- Existing **Execution Simulator**, **Historical Spread Analysis** and **Spread Strategy Lab** remain available for bid–ask capture research.

This keeps the same Dhan shared market library and recorded original 20-level bid/ask evidence. The option-wide Quote/OI subscriptions are broader than the subset with source-validated 20-level books. No LTP-derived pseudo-books are accepted.

## Bid–ask capture workflow

The liquidity provider attempts a passive buy at a contract's bid followed by a passive sell at its ask. Neither is guaranteed to fill.

The scanner automatically evaluates each validated source option and 1–10 lot sizes. The new research-priority gate requires an exact original-book ID, lot-size verification, budget/depth sufficiency, a receipt age of at most 60 seconds, an unexpired contract, a positive stressed *conditional two-fill upper bound*, and a modeled break-even **conditional sell-fill hurdle at most 75%**. The threshold is a heuristic filter, NOT an actual sell-fill probability.

Ranking favors a lower hurdle, higher stressed *conditional* net per rupee of entry capital and less extreme spread width. Archived/stale source rows remain visible but are not labeled as fresh. Separate columns show the immediate marketable loss, conditional passive bound, stressed bound, failed-exit forced-liquidation loss and break-even sell-fill hurdle. Actual queue/fill data remain unknown.

## Multi-leg auto discovery

The engine constructs **six** equal-lot, same-expiry, defined-risk structures.

| Structure | Ordered legs, all from original Dhan saved books |
| --- | --- |
| Bull call debit | Buy lower CE; sell higher CE |
| Bear put debit | Buy higher PE; sell lower PE |
| Bull put credit | Buy lower PE hedge; sell higher PE |
| Bear call credit | Buy higher CE hedge; sell lower CE |
| Iron condor | Buy low PE; sell higher PE; sell lower CE; buy high CE |
| Iron butterfly | Buy low PE; sell central PE; sell central CE (same central strike); buy high CE |

Automatic discovery rejects incompatible expiry, source-verified lot size, structure ordering, insufficient 20-level depth, mismatched quote timestamps (default maximum skew 10 seconds), risk proxy over budget or nonpositive maximum terminal payoff after entry fees.

No manual contract selection is necessary for the automatic list. The optional exact-leg builder validates every leg server-side. Sort by research priority, max theoretical payoff, terminal reward/risk, smallest maximum loss, immediate crossing costs and quote synchronization. Multi-leg notebook data are browser-local research snapshots, not paper fills; it can export JSON.

## Mathematical and fee definitions

For each marketable illustrative **BUY**, the entry price walks recorded ask levels. For each **SELL**, entry walks recorded bids. Immediate unwind crosses the opposite sides of the same saved book and includes estimated entry and exit fees. Sufficient recorded 20-level quantity is mandatory.

Terminal payoff = signed long/short option intrinsic values × lot units + signed entry premium cashflow − estimated entry transaction fees. Maximum gain/loss are evaluated at piecewise-linear strike knots and extremes, and the chart interpolates these exact payoff segments. This is a **theoretical terminal** payoff, not a prediction or broker's actual settlement. Exercise, expiry settlement, overnight costs and some taxes can change cash results.

Fees are the existing Dhan/Zerodha transaction cost schedule. For a standard single order per leg, 2 legs incur two option-order brokerage charges and 4 legs incur four charges; tax and exchange fees are separately calculated. Actual partial fills, customer-specific tariffs, order counts and contract-note rounding can differ.

Short-option and credit structures require separate Zerodha broker margin verification. **Maximum terminal loss is only a risk-capital proxy**, not initial or final SPAN/basket margin. Even if the risk proxy fits the budget, a multi-leg trade may not be executable. The UI always marks broker margin as UNVERIFIED and no order is placed.

The research score is a descriptive structural heuristic, NOT measured win probability, calibrated expected profit, Sharpe or executable liquidity.

## Source integrity / execution restrictions

- Original saved Dhan 20-level packets with SHA pairing and master-verified lot size only.
- Multi-leg quote-time skew is bounded; on older recorded dates every result is historical reference, not a live executable quote.
- No broker orders, order acknowledgements, fills, cancellations, queue position, bid/ask future price prediction or realized P&L are asserted.
- No implied zero slippage or atomic simultaneous order placement. Zerodha basket orders are placed sequentially and required margin can differ from final margin.
- No automatic paper fills. A saved browser notebook observation must not be confused with a paper trade.

Official broker references:
- https://support.zerodha.com/category/trading-and-markets/charts-and-orders/basket-order/articles/final-margin-calculated-in-options-basket-orders
- https://support.zerodha.com/category/trading-and-markets/charts-and-orders/basket-order/articles/kite-basket-orders
- https://zerodha.com/margin-calculator/SPAN/

## Acceptance and scope of work

After merging and pulling the branch:

    python -m unittest tests.test_option_spread_studio tests.test_liquidity_spreads -v
    npm run build

Run repository-wide Python and browser CI as well.

To progress from research ranking toward actual profitability evaluation, collect order acknowledgments, cancellations, fills, passive queue estimates, partial-fill events, broker basket margin responses and time-synchronized historical replay, then measure out-of-sample execution P&L. Do not label a large saved spread as guaranteed or expected income.


## 2026-11-23: Shared execution-feasibility negative gate

**Important correction:** In the earlier automatic scanner a ₹1.50/₹2.70
option could rank first because the two-passive-fill counterfactual showed
₹311 profit after fees, while the simulated missed-exit loss was only
₹50.78. This does **not** mean the option can be profitably market-made.
A long option can become worthless; if entry costs ₹473.79, the zero
recovery exposure is approximately **₹473.79**, excluding any additional
expiry costs. The tiny mild-stress loss cannot replace tail risk.

A shared backend module, `spread_execution_gate.py`, is now the decisive
source-quality filter for **both** bid–ask capture and multi-leg options.
Both engines retain *all structurally modeled quotes* for inspection but
only place **PAPER-RESEARCH-QUALIFIED** candidates in the automatic
shortlist. Neither engine can authorize live orders: the global action is
**NO TRADE** until independently verified fills and broker information
exist. High scores are research heuristics, never win probabilities.

### Default bid–ask restrictions

- Saved original book age ≤ **8 seconds** and unexpired contract;
- best bid premium ≥ **₹20** per unit;
- quoted relative spread ≤ **250 bps** (2.5% of mid);
- first-level bid AND ask size at least **2 × intended units**;
- at least **3 saved packet receipts** and **2 distinct packet hashes**
  spanning at least **15 seconds** within the latest **120 seconds**;
- at least **2 distinct Dhan source exchange-trade timestamps** and
  cumulative reported volume growth ≥ **1 verified option lot** in
  the last 120 seconds. These reflect *other market trades*, not our fills;
- long option's full **entry cash debit** (loss-to-zero scenario) ≤
  **25%** of the user-selected capital;
- positive hypothetical cost-adjusted, adverse-stressed two-fill bound
  and a recorded quantity-sufficient failed-exit path.

Lot sizing now prefers a size inside this risk budget when available,
instead of maximizing optimistic absolute rupees. The existing mild
failed-exit hurdle remains visible but must be read next to a
**zero-recovery break-even conditional exit-fill hurdle**:
`premium_cash_at_risk / (premium_cash_at_risk + conditional_stressed_gain)`.
Neither hurdle is a calibrated actual fill probability. A second
illustration is a **50% premium drop exit** with estimated entry/exit
fees. Unknown costs and unobservable queue events remain unknown.

### Default multi-leg restrictions

- Each exact source leg ≤ **8 seconds** old, and maximum receipt-time
  skew ≤ **2 seconds**;
- every leg's bid ≥ **₹5** and relative spread ≤ **1000 bps**;
- each leg has top-of-book bid and ask quantity ≥ **2 × position units**;
- each leg has the same minimum original packet receipt **and source
  trade/volume** history described above;
- theoretical maximum loss after entry fees ≤ **25%** of the selected
  capital;
- hypothetical same-book immediate round-trip drag ≤ **50%** of
  maximum theoretical terminal gain.

The multi-leg source gate is necessary but **not sufficient**:
Zerodha's required and final basket margin, sequential order acceptance,
partial fills and expiry settlement are still unverified. The UI labels
unqualified contracts **NO TRADE**, shows their rejection reasons, and
does not present historical sources as live opportunities. Changing
reference display windows does not loosen these hard requirements.

### Performance and data provenance

Both engines use the existing local database. Two **bounded
GROUP BY** queries obtain per-contract depth receipt counts/distinct
packet hashes and source observed trade-timestamp/volume activity over
the last 120 seconds; these reads do not change live Dhan
subscriptions or stop their recording. Receipt counts are *not exchange fills or independent evidence of queue
priority*. Source trade timestamps and cumulative volume growth are
not fills or profit for our account.

No source quotes, broker acknowledgements, or profits are synthesized.
The new `execution_decision` API object explicitly returns
`live_action=NO_TRADE`, paper-study candidate counts, top rejection
reasons, no calibrated fill probability, and no expected-profit figure.

Run:

    python -m unittest tests.test_spread_execution_gate tests.test_liquidity_spreads tests.test_option_spread_studio -v
    npm run build

Next milestone remains **measured paper/execution event collection**,
with order acknowledgments and fully time-aligned market data. This
change is a risk-rejection and prioritization layer, **not** proof the
strategies make money.

## Original-depth Speed & Viability study
Trading → Liquidity & Spreads is a primary tab. The speed study replays selected exact contracts at fixed 15-minute decision anchors (09:20 onward, all six horizons elapsed), 5/15/30/60/120/300-second holds, configurable reaction delay, first subsequent original book, bounded receipt window, depth participation, slippage and broker fees. Multi-leg analysis offers the same study for the selected basket and strict 2-second leg receipt skew. Results include complete/attempted, target hits, net P&L, worst net, matched-cohort mean, entry and exit decision-to-receipt p90 and total elapsed median. Missing or partial paths are explicitly unscored. Single-option passive bid-entry markout assumes all units entered at the bid, not an observed or estimated fill probability. No actual fill speeds, broker margin, legging risks or profitable execution are established. This selected-contract fixed-clock diagnostic is not a strategy backtest. Actual real order latency needs separately observed broker order acknowledgements and fills. No orders or recorder changes.

### One-second evidence tier
Up to six CE and six PE from existing verified core/opportunity/active subscriptions are given at-most-one-second original-depth sampling. The ₹17,000 research budget uses chain ask, 5 bps modeled adverse slippage and estimated Zerodha buy charges; the configured lot count is preferred, with smaller whole-lot fallback. Stable core subscriptions, recent original paired receipts, tighter relative spreads, existing priorities and traded volume are preferred. The chain affordability estimate is not a depth-execution proof. This is a research selection heuristic, not a trading recommendation. Existing 3-second priorities and 30–60-second broad sampling remain; no additional sockets or changes to the subscription selection. The immutable receipt records requested cadence; actual packets, queue capacity and disk determine achieved coverage. Speed study adds 1s and 2s holds and defaults to a strict 1s post-delay receipt window, with configurable 1/5/15-minute clock anchors. Actual timestamp inventory reports observed seconds, all-leg common seconds, median/p90/max internal gaps and missing elapsed-session seconds. Not verified exchange event cadence, actual fill latency, or independent trials. Existing historical seconds are not recoverable.

### Batched latency sensitivity
The default UI comparison tests 100/250/500/1000/3000/5000ms assumed reaction delays against the eight fixed holds (48 configurations per exact contract/basket). All cells use one cutoff and identical predeclared decision anchors reserved for the longest latency. The comparison matrix uses common scored anchors per hold across all delays; the detail panel uses common scored anchors per delay across holds, and the global common count is also reported. Censored paths, including complete hypothetical entry without observable exit, remain separately counted. Total elapsed p90 is decision-to-final-receipt, not exchange execution time. The subsecond parameters are sensitivity scenarios on recorded local timestamps, not subsecond fill measurements. Batch results omit path arrays to limit memory; individual-delay studies retain them. No orders and no extra provider calls.

### Independent spread replay worker
The general research/acquisition worker remains serial. The explicitly allowlisted `spread_speed_study` uses a separate single-worker thread pool and mode=ro original depth reads, with atomic single-study admission and a shared six-active-job cap. Queue positions are lane-specific. Long expired-option downloads therefore do not occupy the spread replay worker; job history writes remain protected by the existing library lock. The first progress stage identifies the saved-depth scan. Local disk/CPU contention and missing observations can still affect completion; no recorder changes or broker calls.

### Adaptive replay workers
The independent speed-study coordinator chooses up to six read-only anchor threads per run using CPU affinity, cgroup v2 CPU quota, available memory and anchor count. Two CPU slots are reserved where possible, along with a 512 MiB memory planning reserve and 256 MiB per thread. Unknown memory falls back to serial. These are sizing heuristics, not hard resource isolation. Each anchor retains its own cache; bounded in-flight tasks and chronological aggregation preserve matched comparisons. Progress includes worker count; cancellation stops scheduling new work and lets current SQLite operations finish. General acquisition remains serial. No provider requests or live execution are added. Actual throughput improvement depends on local storage and CPU contention.

### Budget and data readiness before replay
The speed panel checks the latest verified saved original depth for each selected exact leg before launch. The same marketable entry walk and risk function as replay produces one-lot required capital, requested-lot required capital, and the maximum affordable whole lots up to ten, applying the chosen participation haircut, slippage and fee profile. Latest multi-leg receipts must meet the requested skew before estimating basket cost; broker margin remains unknown. Sparse saved coverage (under 10%, a diagnostic threshold rather than an execution guarantee), missing books and insufficient budget/depth trigger a warning and a deliberate historical-diagnostic override. For single options the user may choose a different affordable saved identity and smaller lot count explicitly, never silently substitute one. Ranked alternatives favor requested size, observed-second coverage and tighter spreads; this is an in-sample research screen, not an out-of-sample signal. A bounded optional scan examines at most 400 ranked identities plus selected identities and shows up to 20 affordable alternatives; large inventories can time out and report a truncated scan. Coverage counts complete elapsed UTC seconds with saved timestamps, not verified fills or continuous subscriptions. Historical replay also exposes actual minimum observed modeled budget and stage-specific missing-receipt counts. No extra Dhan calls, source writes, orders or changes to the socket plan. The updated capture prioritizer applies when the new recorder code runs, not retroactively to missing books.

### Automatic paper decisions
Trading → Liquidity & Spreads → Automatic Paper Decisions. Enable explicitly; pause stops new entries but existing paper paths continue monitoring. Settings persist locally. Directional and defined-risk vertical engines are independent virtual experiments, each with its own budget (not simultaneously allocated real cash). No broker calls or order endpoints are used. Default inputs are ₹17,000 capital, ₹100 conditional net target, ₹4,250 modeled session loss allowance, up to three whole lots, a five-minute maximum hold and estimated Zerodha retail fees. Change these in the panel. Scored losses reduce the session risk allowance; wins do not replenish it. The maximum loss is a modeled sizing/stop constraint, not an actual guaranteed loss cap.

The worker checks every five seconds, evaluates at most one new decision per engine per minute and one outstanding path per lane. It requires fresh completed contiguous index bars, the existing EMA9/21 and RSI rule, a SHA-verified chain receipt within 60 seconds, exact master-matched currently subscribed original depth within 8 seconds, recent depth receipts and actual source trade activity, OI and volume. The bounded candidate universe uses up to 200 subscribed identities and up to 12 eligible contracts per side for vertical pair enumeration. BSM quote-implied Greeks, an ATR-scaled move, ±2 IV-point stresses, estimated fees, 25% displayed-depth participation, 5 bps per-leg slippage, modeled risk and two-second basket skew are used to rank conditional scenarios. No probability, forecast, or calibrated expected return is asserted. Neutral/weak signals produce NO TRADE; passive bid/ask capture is not enabled because queue fills remain unobserved. Only directional long calls/puts and direction-aligned debit/defined-risk credit verticals are automated in this version; four-leg neutral baskets remain in the manual research studio.

A decision is committed before its paper entry window: 1-second assumed reaction, then first original book per leg within 5 seconds, without seeking better future quotes. Recheck original contract terms, available size, receipt skew and modeled budget. Sample subsequent executable close marks; target/loss marks trigger another delayed first-receipt exit attempt, not an assumed fill at the mark. The maximum hold deadline is fixed at entry. Paused monitoring and restart recovery use persisted decision records, not retrospective target/stop discovery. Missing entry evidence is rejected; incomplete conditional entry depth or unobservable exit is censored and blocks the lane for the rest of the session. Censored paths are not assigned zero P&L. Scored results are conditional original-depth simulations, not actual fills. Broker margin, legging, exchange latency and profitability remain unverified. The local SQLite paper journal stores decisions, selected alternatives, timestamps, hashes and modeled outcomes without altering the shared market data or recorder subscriptions.

Offline regression tests: `python -m unittest discover -s tests -p 'test_automatic_paper.py' -v`. Browser and real recorded-data validation are separate acceptance steps.

### Automatic speed-study selection
Speed & Viability defaults to Automatic rather than a manual exact-ID dropdown. One Run speed & viability test action screens recorded identities matching the date, expiry, side and search filters, chooses a verified original book with the highest observed-second coverage (then tighter relative spread, affordable size, latest receipt and deterministic ID tie-break), and selects the largest requested whole-lot size that passes modeled entry capital and displayed entry/exit depth. The requested quantity is a maximum, not a forced size. Today's active depth watchlist is queried by indexed exact identity; historical dates or absent subscriptions use the bounded archive scan. A partial scan and sparse coverage are explicitly displayed; no eligible contract means no replay job is submitted. The selected contract and size are fixed for the configured 48-cell replay, not switched after inspecting outcomes. Selection is in-sample research and does not imply a directional signal, future fill, live margin or profit. Manual mode is still available, with the watchlist sorted by numeric strike, CE/PE, expiry and ID. The continuous Automatic Paper Decisions engine is separate from this one-click execution diagnostic. Tests cover lower-lot fallback, missing close depth, budget, filter constraints, numeric menu order and chosen-ID/lot handoff.

### All-contract batch research and later-session validation
Open Trading → Liquidity & Spreads → Batch Research. The capital, maximum lots (1–3), net target and decision spacing are adjustable; the default is ₹17,000, three maximum lots, ₹100, five-minute anchors and one-second receipt windows. All affordable singles in the bounded recorded universe are evaluated, not just the UI's top twenty. Today uses the current depth watchlist; historical dates use the capped archive scan. A partial universe scan is explicitly disclosed. For each eligible contract, compare each affordable lot count and all 48 reaction-delay/hold cells. Optional vertical research enumerates four neighboring strikes on each side, ranks synchronized pairs by observed coverage and relative spread, screens at most 80 per vertical type and retains at most 12 affordable baskets per type (48 total). It is not an exhaustive spread search, and actual margin/legging is unknown. The shared independent replay lane admits only one single, batch or validation study at a time; one adaptive pool uses at most six read-only workers, reusing first-book queries across lot sizes. Live recorder subscriptions and vendor requests are unchanged. Cancellation checkpoints stop refilling work; numerical results are based on a single cutoff and the shared market archive should not be edited during replay.

Two distinct entry cohorts are evaluated. Fixed-clock is the unconditional diagnostic. The EMA9/21+RSI cohort reconstructs completed minute bars from original index ticks received by each anchor, not revised final bars; if original ticks or contiguous bars are missing, directional evidence is unavailable. Its deterministic random-time control samples the same number of attempted source-valid anchors without replacement and can overlap the aligned cohort. This is not a paired or independent-sample significance test. Each cell retains completed and missing counts, conditional fee-adjusted mean/total/worst net, target hits, fees and missing states. Missing paths are never zero-filled. A ranking requires at least 20 scored paths, 20% completion and four distinct half-hour blocks. The descriptive score is the lesser of mean completed net and the lower-quartile mean of scored blocks. It is not a confidence bound, expected return, or proof of profitability. Negative and insufficient rows remain visible. The complete summary CSV is saved locally under data/research_workspace/speed_batch, with the top 25 per family/cohort in the dashboard. The study does not represent a sequential cash-account backtest; fixed-clock windows can overlap.

At most one positive qualifying configuration per family/cohort (up to four) is frozen at job completion in a SHA-256-addressed local plan. Signal plans additionally require adequate random-control evidence and higher conditional mean than that control. No plan is generated if none qualify. Validation requires a completed weekday IST session strictly after both the discovery and freeze dates. Exact identities, contract terms, lot counts, delays, holds, cohort, fee and depth assumptions are preserved; expired or missing contracts stay unscored. There is no retuning or reselection. This provides later-session conditional quote-replay evidence, not authenticated order executions or proof against data snooping; the local digest detects changes but is not an external timestamp or immutable external registry. Paper-only automatic monitoring remains a separate feature. No actual broker orders are enabled.

Offline tests: `python -m unittest discover -s tests -p 'test_spread_batch.py' -v` and `python -m unittest discover -s tests -p 'test_job_queue_actions.py' -v`. Browser acceptance uses explicitly synthetic fixtures; actual saved-data throughput and live viability require local verification.

### Execution realism and concurrent market recording (batch policy v2)
The current speed and batch screens default to zero **additional** slippage. Buying still consumes the saved asks, selling consumes saved bids, displayed quantity is haircutted by the participation assumption, and brokerage, exchange charges, SEBI fees, GST, STT and stamp duty remain in the modeled debit/credit. The published Zerodha retail NSE-options tariff was checked against https://zerodha.com/charges and https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/exchange-transaction-charges on 26 November 2026 IST. It uses ₹20 per executed option order (₹40 under the specified account condition), 0.15% sell STT from 1 April 2026, 0.03553% transaction charges including IPFT, ₹10/crore SEBI, 0.003% buy stamp, and 18% GST on brokerage/transaction/SEBI. Contract-note aggregation/rounding, actual executed order counts, account-specific levies and earlier historical tariffs may differ; do not describe these estimates as actual charges. No income tax, forced liquidation, expiry settlement or exercise cost is simulated.

Batch rows now attribute conditional midpoint movement, bid–ask crossing, displayed-depth impact, additional adverse-price allowance and individual estimated fees. A rounding reconciliation keeps the bridge consistent with modeled net P&L. +1/+5/+10 bps above the chosen baseline are evaluated automatically on the same baseline-completed receipts and displayed allocations, with new hypothetical turnover, fees and entry budget checks. These are adverse-price sensitivity scenarios, not separately observed fills or empirical slippage calibration. Rejected stress paths stay unscored and are counted, never silently discarded. Freeze requires positive conditional mean under every stress, with no stress attrition among baseline-scored paths, in addition to the original sample/block and signal-control gates. v1 plan manifests are preserved on disk but not silently validated under v2.

Use Costs & cash on a ranked configuration to inspect average fee/cost attribution, matched stress results, and the first scored example (not the best outcome). Its modeled buy/sell VWAP, quantity, original bid/ask, receipt timestamps, fees and cash flow are shown; for single long options, continuous modeled break-even and target exit VWAPs are computed before tick rounding. Neither quote receipt delay nor these thresholds certify broker latency or achievable fills. The separate sequential-account diagnostic uses one hypothetical open position at a time, skips overlapping anchors and over-budget entries, stops recycling capital after an observed partial basket or unobservable exit, and displays unknown entry observations. Full-account net stays unavailable when entry evidence is missing or exposure unresolved; the scored subset is not a real broker balance or full-session equity curve. Margin for short legs is unverified. Actual broker order acknowledgements, fills, fees and margin evidence are still necessary for real-life calibration.

The canonical local shared-market SQLite database is switched to persistent WAL at API startup, before armed market recording resumes. No journal migration or forced checkpoint is performed by replay readers; no source tables or sidecar files are deleted. Readers use mode=ro/query_only and a bounded busy timeout/retries for market queries. Exhausted retries fail explicitly rather than becoming missing-price samples. The batch falls back to one worker if WAL is unavailable; the UI reports the observed journal mode. Job-history SQLite errors cannot abort a numerical job. This addresses identified contention mechanisms, but competing processes, storage constraints and local throughput must still be checked. Stop/restart the local API outside the recording session if possible; after startup run the WAL inspection and regression tests. Never delete -wal/-shm files to fix a lock.

### Dynamic strategy research and live paper trading
Trading → Liquidity & Spreads now separates the fixed-clock **Batch Research / Speed & Viability** execution diagnostics from **Strategy Research** (chronological policy comparison) and **Live Paper Trading** (prospective automatic paper monitoring). Strategy Research has no decision-spacing parameter. Compare fixed 1/2/5/10/15/30-minute hold caps (up to the selected maximum), target/stop, trailing, EMA reversal and adaptive policies. All retain the modeled stop-loss and a maximum hold/near-close guard. Target/stop attempts an exit at a target mark; trailing and adaptive arm after the target and attempt an exit on the specified observed net-profit retracement (floor at least zero before subsequent execution uncertainty). Reversal uses the opposite fresh completed EMA9/21 relation; a stale, missing or equal EMA is not reversal. Adaptive also attempts an exit after sustained missing/invalid close evidence or spread above 250 bps. A trigger is not a fill. Use the subsequent first original receipt window and count incomplete paths as censored. Actual trigger processing time is used, not a retroactive exit after a delayed cycle. A missed session close is censored.

The new default research settings are ₹17,000 capital, ₹4,250 modeled session loss allowance, ₹100 target net, ₹250 stop mark, ₹50 trailing retracement, 20-second liquidity grace and zero extra slippage. These are editable research assumptions, not calibrated risk recommendations. The full premium/defined-risk proxy must fit the remaining modeled budget; the stop mark alone is not maximum loss. Live defaults to a 15-minute cap; historical comparison defaults to 30 minutes. Existing stored legacy paper settings keep their target/stop exit and 5 bps extra-slippage assumptions until changed; already open paths retain their stored config. Entry selection uses a five-minute ATR scenario horizon independent of the exit policy, not a profit forecast. The live worker coalesces committed original depth, chain and BANKNIFTY observation notifications into approximately five-second checks, with external-process polling fallback. It may reconsider a no-trade gate within a fresh completed signal minute, while permitting at most one actual paper entry attempt per lane per minute. No calculation runs in a recorder callback. No-trade decisions are logged compactly. Pausing stops new entries, not ongoing exit monitoring.

Historical Strategy Research reconstructs the causal signal from original received index ticks. At each eligible five-second observation, it chooses from up to 200 nearest contracts in the contemporaneous SHA-checked chain, with original fresh depth, OI/volume and source trade-activity gates. It does not use today's subscriptions or final-day affordability. The live selector uses its current subscriptions instead, so the universes need not match exactly. Independent policy/lane virtual accounts advance chronologically through the same entry/mark/exit functions as live paper monitoring. Cash is not reused while a position is pending; completed gross losses reduce session risk, and censored paths halt the lane. Source snapshots and book reads are shared where possible across policies; the chronological coordinator is intentionally single-threaded and shares the exclusive cancellable replay lane. Intraday cutoff leaves pending paths open. Completed-subset cash and P&L are not full-session performance if evidence is missing. The CSV includes applied config, original chain and book evidence, exact legs, observed receipt times, modeled fees, hold time, trigger, state and conditional net. No strategy is automatically promoted from in-sample historical performance. Original receipt timing, margin, actual fills, fee reconciliation and out-of-sample performance remain unverified; live order execution stays disabled.

Offline tests: `python -m unittest discover -s tests -p 'test_dynamic_strategy.py' -v` and `python -m unittest discover -s tests -p 'test_automatic_paper.py' -v`. Browser fixtures test strategy launch and result rendering separately from numerical replay. Local recorded-data acceptance is still required.

### Strategy entry evidence diagnostics (chronological v2)
Historical selection intersects the contemporaneous chain with recorded original depth received within the preceding eight seconds before taking at most 200 matching identities. Up to 4,000 unique chain IDs are considered, sorted by contemporaneous strike distance with deterministic ties; truncation is explicit. Indexed identity/time queries never use a later receipt. This addresses the mismatch between the premium/liquidity-oriented recorder watchlist and the former nearest-strike-first historical cap. The original book, chain, activity, risk, fees and scenario gates remain required. The live watchlist selection is unchanged.

Strategy Research reports the number of scans containing evidence-qualified contracts, source-level rejection reasons and separate directional/spread selection outcomes. Lane counts cover unique per-observation lane/risk-budget evaluations; identical-policy evaluations reuse a result. Gate counts are rejected observations, contract/lot combinations or basket/lot combinations, not independent trades. A chain that passes initial checks but yields no qualified contracts is explicitly distinguished from a source-valid candidate that fails sizing or scenario checks. An IV-stress rejection indicates the unstressed favorable scenario reached the target but the minimum stressed scenario did not; neither is a return forecast. The unchanged trade journal contains only actual paper attempts. Download Entry Diagnostics CSV for the run summary plus source and lane evidence at each scan, even if the trade journal is empty. No extra risk allowance, target relaxation, or automatic live trading is enabled. Previously completed v1 jobs cannot retroactively recover these omitted gate counts.
