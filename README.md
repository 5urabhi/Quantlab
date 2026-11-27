# QuantLab — Canonical project guide

**Last consolidated: November 27, 2026.** This README is the single maintained human-readable project document. Before implementing, researching, reviewing, planning, or merging QuantLab changes, **read this file first**. Update the relevant section here whenever scope, commands, verified evidence or priorities change. Do not create parallel roadmaps, status files, or general-purpose guides. Source code, tests, machine-readable configurations and generated local research artifacts remain separate. If the code, a dated data audit, or current tests contradict an older description, report the discrepancy and correct this README rather than claiming completion.

## Contents

1. [Mission and scope](#mission-and-scope)
2. [Current evidence and priorities](#current-evidence-and-priorities)
3. [Five-year candle forecasting plan](#five-year-candle-forecasting-plan)
4. [Run and verify](#run-and-verify)
5. [Architecture and workstation workflows](#architecture-and-workstation-workflows)
6. [Market data and source contracts](#market-data-and-source-contracts)
7. [Model laboratory and factor research](#model-laboratory-and-factor-research)
8. [Forecast research and completed experiments](#forecast-research-and-completed-experiments)
9. [Trading and execution research](#trading-and-execution-research)
10. [Acceptance, security and maintenance](#acceptance-security-and-maintenance)
11. [Historical documentation and recovery](#historical-documentation-and-recovery)

## Mission and scope

QuantLab is a local-first quantitative research workstation (React/Vite + FastAPI/Python) for multi-factor equity index construction, stochastic processes, portfolio risk, market data, forecasting and execution research. It is a research showcase and a practical BANKNIFTY research workstation, not a broker order router.

**The immediate product objective, reaffirmed on November 27, is to learn from approximately five years of verified BANKNIFTY history and predict the next candle continuously as completed candles arrive.** Build an underlying-price forecast first, then decide whether any trading policy and option contract selection have an independently demonstrated advantage. Do not replace that objective with a handful of fixed-time daily predictions, a new data-provider integration, a spread scanner, or more strategy rules. Those may be useful secondary experiments, not the primary deliverable.

The forecast should give direction probabilities, coherent expected OHLC/return and useful uncertainty for the next 1/5/10/15/30-minute horizons (start with the existing 5-minute implementation; other horizons require explicit label definitions and validation). A rolling five-minute forecast at each minute is not the same as a forecast on non-overlapping five-minute clock boundaries; identify the mode in results. Distinguish predicted price direction from probability of profitable option execution. No live model promotion or broker orders are authorized by a research result.

Other existing product capabilities must remain usable: Guided Research; mathematical model laboratory; equity index/factor and risk studies; Data Centre/Market Library; saved experiments, charts and results; read-only live and historical Trading Cockpit; separate directional, spread and paper-research workflows. Use existing modules rather than build a second application.

**Rules for future work:** prediction first, strategy second, execution third. Reuse the canonical market store and supported models. Start with a small verifiable change, measure the result, and expand only if it materially serves the current goal. Do not promise a trading edge, claim a complete dataset from a requested range, or report synthetic results as actual evidence.

## Current evidence and priorities

This is a dated evidence register, not a new independent acceptance run. Local output provided by the operator and checked repository code are distinct from CI and empirical validation.

| Area | Evidence / current state | Limits / remaining work |
| --- | --- | --- |
| BANKNIFTY minute history | Prior five-year local preparation audit: 1,190 complete regular comparison sessions, 52 partial sessions, 6 repair windows; roughly 446,250 complete-session candles before filtering | Re-audit the exact current store; 375-slot comparison window is not every exchange session or full derivative session |
| Indian equity history and peer indices | Original verified receipts and dated membership loaders exist; prior audited exact 16-stock union; NIFTY 50 and other indices available with differing coverage | Do not assert five years of complete constituent or peer data; audit per identity/session, including corporate actions and incomplete files |
| Dated BANKNIFTY membership | Reconstructed archive documented through 2026-10-13 in the reported local audit | 29 evaluation dates lacked membership in the previous 365-day sequence experiment; no dated weight snapshots found in that audit. No guessed members or weights |
| Historical options | Prior local sample: 90 sessions, rolling near-month ATM +/-3, 461,927 bars with OI/IV, 924 verified receipts | Not a complete one-year exact-contract option archive, quote book, or bid/ask fill history |
| Daily global | FRED and Alpaca configured; prior inventory seven US ETF proxy series with 1,441 rows each starting November 2021; Nikkei/FRED and other macro archive observations starting March 2024 | Archive assumptions differ from historical live receipt; no exact global intraday index substitution |
| Overnight global | Existing authorized Alpaca BOATS feed: operator's 90-calendar-day run (2026-08-29 to 2026-11-27 exclusive) returned 18,178 observed five-minute bars across ten ETFs | US-listed proxy trades, not Asian cash indices or GIFT NIFTY; delayed and often sparse; automatic collection configured, continuous operation not yet verified |
| Live recorder | Dhan quotes, OI, option chains, depth, stock context and storage guards implemented | Check actual packet age, drops, entitlements, storage and session boundaries; no historical depth reconstruction |
| Forecast engines | Rolling next-five-minute OHLC and optional PyTorch multi-asset sequence research already implemented; source-aware, chronological evaluation | Both current run entrypoints enforce a 120-400 calendar-day study range; **five-year continuous multi-horizon model is not complete** |
| Opening experiments | Pre-open global and post-open selective baseline scripts implemented and local tests passed in the global-opening-context branch | Exploratory only; not a substitute for rolling forecast, not approved strategies |
| Software | Local workstation and prior software/browser acceptance documented; latest global-opening-context branch unit tests reported passing for its scoped experiments | Re-run full CI and local acceptance at the actual commit; local data readiness and model performance are separate |
| Live trading | Read-only research, manual workflow, simulation/paper and modeled costs | No automated broker orders. No validated production model or independently reproduced profitable strategy |

**Priority register (the next tasks, in order):**

- **P0 — Forecast dataset and existing engine audit.** Inspect the existing rolling OHLC/sequence code, source manifests, local five-year audit and model results. Verify actual distinct eligible completed bars, source hashes, time ranges, missing groups, memory/IO bounds, and prior examined evaluation dates. Reuse the five-year original receipts; no fresh mass download merely because a shorter model loader currently rejects a longer range.
- **P0 — Extend existing core forecast to five years.** Build bounded/session-partitioned or streaming input assembly, train/evaluate core index-only on the verified long history, and retain shorter optional context lanes. Benchmark simple training-only baselines and existing ridge/hist-gradient/logistic methods first. Add a supported tree/sequence model only when justified. No indiscriminate grid search, unbounded option extraction or all-or-nothing full-feature intersection.
- **P0 — Define causal targets and assessment.** Every eligible completed candle, explicit clock and horizon, no lookahead, no cross-session target unless separately studied. Whole-session chronological development/calibration/test, purging/embargo where required, date-weighted results and uncertainty; genuinely new sessions for prospective confirmation. Save original predictions and outcomes.
- **P1 — Incremental context lift.** Compare on matched dates/anchors: core vs bank breadth/relative volume; peer indices; eligible daily/overnight macro; options/OI/IV; actual receipt-time depth where available. Use masks/fallbacks, not fabricated inputs or five-year imputed live-book history. Do not make full-history training wait for shorter sources.
- **P1 — Continuous research inference.** Integrate a validated frozen model into the existing UI with per-horizon forecasts, calibrated probabilities, uncertainty, current timestamps, source coverage and abstention. Record outcomes and monitor drift; keep stale/unvalidated models visibly unavailable. No auto-order path.
- **P1 — Later execution research.** Only after predictive evidence, test CE/PE contract selection, actual quote sides, lot sizes, fees, delay and fills, with funding/risk constraints and a separate spread experiment.
- **P2 — Deferred unless needed.** New external provider onboarding (including JForex), five-year foreign intraday data, deep/RL expansion, additional fixed-time strategy grids, speculative architecture rewrites. Keep authorized existing collectors running; focus on predictive performance. Repair material data-quality gaps and protect live capture, but do not make peripheral infrastructure a prerequisite for the core study.

## Five-year candle forecasting plan

### Definitions and information clock

For each eligible decision at time t, use only completed original observations whose availability is known at or before t. For a next-horizon interval, derive open from the first future bar, high/low from the exact future span, close from the final future bar; direction is sign of future close relative to the last known close (record flat separately or use a prespecified deadband). Keep target intervals, timestamps, availability lag and horizon in the report. A directional probability and an OHLC forecast are different outputs; evaluate both. The live receipt clock is not the exchange event clock. Historical archive assumptions are not live receipt evidence. Skip missing required anchors, holidays, incomplete bars, and crossing the end of the regular research window. Do not use the future bar open, current incomplete candle, future option price, final session close, future membership or a revised macro print to construct the decision feature.

### Layers and data support

| Layer | Planned support | Candidate features |
| --- | --- | --- |
| Core price | Five-year verified BANKNIFTY minute history | OHLC, normalized past returns, candle shape/ranges, volatility, EMA/ATR/RSI/MACD, opening range, previous-session pivots/CPR, time-of-day |
| Constituent/peers | Only supported dated and mapped periods | Bank returns, unweighted breadth/dispersion, past-only relative volume, peer index moves; verified weights only if available at decision |
| Global | Existing FRED/Alpaca archive and BOATS data | Publication/receipt-correct prior returns, volatility/macro levels and changes, delayed overnight ETF proxies, explicit age and missing flags |
| Derivatives | Supported rolling option or exact contract windows | Near-ATM CE/PE premiums, OI changes, IV, straddle, volume; exact expiry where known |
| Depth/liquidity | Prospective recorded data | Actual quote-side spread/depth, imbalance, freshness, packet provenance; no fake historical LOB |

Train core on its long valid history. A short-history context model compares against a core model on the same matched samples. Use a calibrated ensemble/fallback only if out-of-sample evidence warrants it. Fit imputation/scalers, feature selection and calibration on training/validation only. Avoid leakage from overlapping horizon windows, cross-sectional membership reconstruction, data vintages, adjusted prices, repeated testing or post-hoc threshold choices.

### Required result and acceptance

For each horizon, report train/validation/evaluation dates, eligible and skipped decisions by reason, source coverage, baseline scores, close/OHLC MAE, return error, direction/confusion metrics, balanced accuracy, Brier/log loss and calibration reliability, interval coverage/width, day-block uncertainty and regime/stability breakdown. Compare training base rate, persistence/no-change and volatility-adaptive baselines; simple regression/classifier/tree models before optional neural models. Keep per-prediction timestamps, probabilities, actuals, source/feature versions and model checkpoint metadata. Dates already examined are exploratory even if they were chronologically held out originally. A claimed deployable predictor requires a frozen protocol tested on new untouched sessions, data and code validation, and receipt-time live shadow checks; profit requires separate execution evidence. A model may legitimately fail or abstain.

## Run and verify

Supported Ubuntu checkout, local-only dependencies and one-command start. Do not switch branches or restart an active recorder without a safe capture boundary.

    cd ~/Desktop/codes/quantlab
    git switch main
    git pull --ff-only origin main
    bash run.sh

Open http://127.0.0.1:5173; Python API normally http://127.0.0.1:8765. Run setup when needed; the launcher starts both services, not three manual terminals. Keep the local .venv and ignored .env. Python and Node installation requirements follow run.sh, scripts/start.sh, requirements.txt and package.json. Use the actual launcher help for the current command inventory.

    bash run.sh setup
    bash run.sh --help
    bash run.sh check
    bash run.sh audit-models --dataset dhan_shared
    bash run.sh verify-saved --dataset dhan_shared

| Command | Use |
| --- | --- |
| bash run.sh check | React build, regression/math checks, source-aware doctor; software success does not imply empirical readiness |
| bash run.sh evaluate | Labeled synthetic assessment and reports |
| bash run.sh audit-models --preflight-only | Missing real inputs without model execution |
| bash run.sh verify-saved --strict | Nonzero exit if original inputs remain missing |
| bash run.sh verify-v3 --scientific | Existing isolated scientific environment and local source health checks |
| bash run.sh python-packages check / install | Inspect/install approved optional research packages; local approval for install |
| .venv/bin/python scripts/quantlab_finish.py doctor | Local source readiness and actionable generated evidence reports |
| bash run.sh archive-market --day YYYY-MM-DD | Non-destructive off-hours archive |
| bash run.sh archive-market --verify PATH | Check archive hashes and row counts |
| bash run.sh validate-trading | Saved-source trading acceptance, off-hours; no broker requests |

Fresh checkout updates may require setup. Engine Offline: check local API and terminal error; Dhan 401: renew the local token using the supported credential workflow, never paste credentials into a report; 400: inspect exact instrument/exchange/interval/request window; 429: respect provider cooldown and existing scheduler. Diagnose actual data availability rather than repeatedly fetching everything. Use an isolated worktree with --shared-root pointing to the original checkout for read-only research when supported. Do not duplicate the live recorder or database.

## Architecture and workstation workflows

- **React/Vite frontend** (src/) communicates with the local **FastAPI/Python engine** (workstation_api/); index_research/ contains factor/index/risk research, quantlab_sdk/ provides Python access, scripts/ contains CLI/acceptance helpers, tests/ contains numerical, regression and browser checks. run.sh is the supported workstation entry point. web/ and original notebook/CSV outputs are retained legacy evidence, not current UI or validated performance.
- **Guided Research:** Select data -> Choose model -> Run -> Analyze -> Save. Use exact supported datasets and readiness diagnostics, transparent formulas/assumptions, charts, and evidence bundles. The Model Laboratory registry in code is authoritative; show runnable versus unsupported rather than claiming every available model has empirical inputs.
- **Data Centre / Market Library:** one canonical shared store, per identity coverage, source/interval/counts, first/last observed timestamps, partial and complete sessions, receipt/source provenance, jobs, gaps, activity, storage and recovery. Display read-only inventory independently of live feed state. Avoid full-page overflow and separate long lists/detail views.
- **Trading Cockpit:** distinguish historical, live capture, paper simulation, option-chain/Greeks, directional research, and separate liquidity/spread research. Never conflate delayed quotes, modeled spreads and fills. Prefer local token once, existing worker maintenance, automatic lot/fee lookup where supported, clear stale/missing status.
- **Research Workspace and Results Studio:** saved presets, custom Python research in isolated execution, notebooks, charts, comparable results, chronological diagnostics, and reproducible export. Ask QuantLab is a deterministic explanation of archived results and source evidence, not a validated trading agent or autonomous execution system.
- **Public presentation:** educational synthetic visuals unless an explicitly reviewed local export exists; no broker tokens, raw holdings, licensed source data or unreviewed empirical performance in public/data. No publication from a successful model run alone.

## Market data and source contracts

### Canonical storage and permissions

Keep credentials and original/derived market files local and ignored. The shared Dhan database is data/dhan/shared_market.sqlite3; original source files/receipts, dated mappings, raw OHLCV, checksums and observed timestamps remain canonical. Derived DuckDB/Parquet mirrors may accelerate verified source-locked reads; stale/corrupt caches fail closed, never replace original evidence. Reuse existing data before downloading; no second store, synthetic missing-price fill, unexplained duplicate or deleted historical file. Data deletion is separate, explicit, warned, and never part of documentation cleanup.

Dhan is the existing read-only domestic provider; optional authorized Zerodha daily equity fallback is not assumed to supply full intraday/expired options. Existing FRED and Alpaca credentials are local; optional Twelve Data mappings require exact reviewed symbols/exchanges and entitlement. Official NSE exports and notices require applicable data rights; use authorized/manual/public-source workflows, no challenge bypass or unauthorized scraping. Credentials in ignored .env only; never display tokens or commit them.

The maintenance worker is bounded, resumable and respects recorder/storage pressure, live priority, token renewal, provider rate limits and cooldown. Do not run concurrent independent history writers. Earlier worklist reports two in-flight historical requests, minimum 0.35-second spacing and process-local rolling 24-hour 80,000-start budget; these are internal implementation settings, not a vendor-certified quota, and reset/accounting across restarts remains a gap. See current code for operative policy.

### Domestic calendar and data preparation

    .venv/bin/python -m scripts.prepare_banknifty_data \
      --shared-root "$HOME/Desktop/codes/quantlab" \
      --years 5 --option-days 365 --context-days 1825 --wings 10 --audit-only

This audits actual saved evidence without provider writes. For bounded authorized acquisition (only if a material gap warrants it), use the existing running local workstation and the same command with --confirm-reviewed instead of --audit-only; review provider data rights first. Range ends before today's Indian session; requested 1825 days is not certified retention. Option scope is rolling near-month ATM +/-10, not all exact contracts. A one-pass report lists gaps and failures; it is not a data-readiness certificate. During 08:30-16:00 IST weekday priority hours bulk history normally defers to authorized maintenance; follow current priority guards, avoid recorder restarts and overlapping jobs. A canceled polling command may leave an already submitted server task running.

Research comparison uses 09:15-15:30 IST, 375 one-minute slots on a regular index session. The dated NSE policy in workstation_api/nse_session_policy.py models identified bank cash closing-auction eligible securities as 360 continuous minutes from Aug 3 through Dec 6, 2026, and 375 from Dec 7; prior 375. Derivatives segment maximum: 375 minutes before Aug 3, 385 through Dec 6, 390 from Dec 7; index contracts expiring on the day from Dec 7 stop at 375. Need exact expiry for a full-session denominator after the revision. This is not a full historical holiday/special-session or CAS eligibility calendar. Do not mark scheduled missing minutes or expiry cutoffs wrong by assuming all instruments share the same clock. Sources: NSE/CMTR/74466, NSE/FAOP/74467, NSE/CMTR/77355, NSE/FAOP/77356; https://www.nseindia.in/static/products-services/closing-auction-session .

Point-in-time membership comes from verified pinned intervals or a documented, nonconflicting reconstructed archive within its coverage, or exact reviewed same-day receipts retrieved by 09:15 IST; don't infer membership from saved prices or today's universe. Weight evidence is independent of member identity; no fabricated weights or claimed index reconstruction. Original stock and index bars, nominal expired rolling options, live quote and depth observations are distinct. Use actual observed stock/option quantities, not a synthetic volume field for spot index.

### Global data (existing feeds only by default)

Global daily configuration and inventory:

    .venv/bin/python -m scripts.global_market_data enable-existing --confirm-reviewed
    .venv/bin/python -m scripts.global_market_data inventory

Current 90-day BOATS run already exists. Do not rerun merely to collect more data. If a bounded approved repair is necessary:

    .venv/bin/python -m scripts.global_market_data backfill-boats \
      --days 90 --to-date 2026-11-27 --max-windows 16 --confirm-reviewed
    .venv/bin/python -m scripts.global_market_data enable-boats --confirm-reviewed
    .venv/bin/python -m scripts.global_market_data features --date 2026-11-24 --cutoff 09:10

The authorized context worker requires QuantLab running. Stop BOATS collection using disable-boats. Overnight NY 20:00-04:00 reference clock respects DST; historical BOATS has documented 15-minute delayed access (https://docs.alpaca.markets/us/docs/245-trading-for-trading-api). This study assumes 20 minutes after bar completion for archive availability; live receipt uses actual later import. Observed-window receipts are reused, missing bars remain missing, and empty responses are not proof of closed sessions. Unique source identities and hashes are recorded in global_market_bars/global_market_receipts in the shared database. SPY 5,443; QQQ 5,824; EWY 4,623; FXI 1,172; EWJ 427; EWT 658; EWS 8; EWH 9; EWA 10; KBE 4 in reported 90-day window. Prior daily ETF observations do not prove same-day Asian open; FRED uses conservative vintage assumptions. Do not label US ETFs as actual local indices or GIFT NIFTY.

Dukascopy/JForex is **optional and deferred**. Existing JForex exporter integrations/jforex/QuantLabGlobalExport.java and direct approved BID CSV import are retained; actual Java compilation/provider coverage remains unverified. Free website access alone does not grant database rights. Only if terms/written authorization permit local storage and research, use reviewed GMT/UTC bar-start, exact symbol, side and resolution and original bytes. CLI import-export supports exact reviewed file, instrument, minutes, mode, optional archive-lag-minutes and confirm-reviewed; inventory lists proxies. See the pinned original global guide in the historical section for full optional setup. No new accounts required for verified Alpaca access.

### Equity index research input contract

All real prices/benchmark/fundamentals must be source-dated and internally consistent. These are local CSVs, not public artifacts:

| File | Required format and semantics |
| --- | --- |
| prices.csv | date, then stable security-ID columns; month-end strictly positive adjusted CLOSE levels. Total-return benchmark requires compatible adjusted prices. Missing held prices block simulation; never backfill delistings. |
| membership.csv | date,ticker,eligible (true/false); effective-dated changes and state for every security on/before first price date; no current-universe reconstruction. |
| benchmark.csv | date,return (decimal monthly simple returns); exact matched calendar; first return unused. |
| fundamentals.csv | ticker,period_end,available_at,value,quality,size; available_at not before period end; strictly prior publication to decision; value/quality higher is better by documented score; size positive cap, smaller ranks higher; explicit revision versions. |
| sectors.csv | date,ticker,sector; effective-date events, all held/selected names classified when constraints require; no modern label substitution. |
| corporate_actions.csv | date,ticker,event_type,event_source; evidence only, does not transform prices or model delisting payouts. |

Real benchmark TRI, investable historical membership, publication-dated fundamentals and weights, adjusted corporate actions and delistings remain essential for defensible factor backtests. A matching hash proves identity, not vendor accuracy or a license. The existing data_audit/source acceptance/research release pipeline reports blockers; use authentic approved exports. Research outputs include returns, weights, concentration, exposure, turnover, factor IC, risk/cost sensitivity, manifests, local reports and explicit evidence class.

## Model laboratory and factor research

Retain working mathematical catalog and existing studies, not just BANKNIFTY. Distinguish theoretical/seeded simulations from historical calibration, in-sample fits and genuinely held-out forecasts. The live registry and run.sh audit-models determine actual current model counts and inputs; the earlier CI audit expects 35 model result rows, and the older catalog of 26 was foundational only. No model is empirical merely because its code runs.

| Family | Foundational implementations / purpose |
| --- | --- |
| Stochastic processes | GBM, Ornstein-Uhlenbeck, Heston full-truncation approximation, Merton jump-diffusion; seeded simulation unless separately calibrated |
| Volatility/econometrics | GARCH, covariance, PCA, rolling volatility forecasts; prior-window evidence and fit diagnostics |
| Derivatives | Black-Scholes-Merton, CRR binomial, implied volatility, antithetic Monte Carlo, Greeks and theoretical option surface; actual premiums require verified quote input |
| Portfolio optimization | Minimum variance, risk parity, maximum diversification, CVaR, Black-Litterman, efficient frontier; long-only constraints and sample estimators |
| Risk and inference | Historical/Gaussian/Student-t VaR/ES, EVT, Newey-West, block-bootstrap Sharpe and correlation stress surface |
| Multi-factor index | Momentum, value, quality, size, low volatility, sourced yield; dated selection, target/held weights, constraints, benchmark relative risk, turnover, costs and capacity |
| Research models | Historical and prospective constituent alpha, candle patterns, cross-index, anomaly/volatility studies, CPR, OHLC forecast and optional temporal sequence models; research support and results vary |

Use Guided Research and the source-aware input diagnostics. Charts and numerical outputs should be linked to actual parameters, available data and assumptions. Model source/run/input readiness, numerical correctness and investment viability are independent. Do not publish old notebook optimized Sharpe 3.34 or 132.86% annualized return as verified results.

Existing release workflow (local .venv):

    .venv/bin/python scripts/research_release.py \
      --data-dir data/research_v1 --config config/research_multifactor.json \
      --output-dir results/release_check_001

Add --execute and a fresh output directory only when source prerequisites are genuinely met. The three studies are factor index construction, benchmark-relative risk attribution, and robustness/source-integrity counterfactuals. Doctor/release create generated reports and missing-source actions, which are not additional maintained repo docs. Review the actual machine-readable independent review template in docs/INDEPENDENT_REVIEW_TEMPLATE.json and do not remove it as prose. See archived model reference, metric definitions, empirical data guide and research protocol for exact formulas and older procedural detail.

## Forecast research and completed experiments

### Existing rolling forecast commands (reuse before adding anything)

    bash run.sh banknifty-ohlc --days 365 --wings 3
    bash run.sh banknifty-sequence --days 365 --wings 3 --epochs 6 --batch 96
    bash run.sh cross-index-research --sessions 90
    bash run.sh cross-index-research --list-sources
    bash run.sh candle-research --help

Actual files: workstation_api/banknifty_candle_forecast.py, banknifty_forecast_features.py, banknifty_sequence_data.py, banknifty_sequence_models.py, banknifty_sequence_forecast.py, historical_alpha.py; CLI scripts/run_banknifty_candle_forecast.py and scripts/run_banknifty_sequence_forecast.py. Both existing OHLC and sequence run functions reject --days beyond 400; **do not instruct the user to pass 1825 until the implementation and tests support it**. This is the specific gap to address first.

Existing OHLC v1: every eligible minute forecasts next five complete minutes from previous 60 contiguous minutes. Encode OHLC relative to prior close with coherent nonnegative wick structure; index, bank, peer and option feature groups; optional context not fabricated. Whole-session 60/20/20 split; training stride five, assessment each eligible minute, day weighting. Last-close/range baselines, ridge, histogram gradient and direction models; training-only support/normalization, validation-only model selection, later metrics and CSV predictions. No global inputs in v1. Existing source loader bounded; inspect actual data volume before extending.

Optional sequence research: PyTorch from requirements-sequence.txt (not required by live workstation); CPU default or explicit supported CUDA. Compact normalized per-session OHLCV windows with masks/identity embeddings; CNN, GRU, Transformer candidates with 15/30/60/120-minute lookbacks, default six configurations, common 120-minute support excludes early morning before 11:15 IST. Five-minute OHLC, direction and tail/quantile outputs; validation early stopping, held-out comparison against adaptive and fixed tree baselines. Existing 365-day study had 245 sessions, 29 evaluation membership gaps. Convergence mode uses a longer validation-controlled schedule, not new information; no need to optimize epochs until core long-history baseline exists. Review old JSON and CSV evidence before asserting a neural gain.

### Global and fixed-time experiments (November 27, exploratory)

On the global-opening-context branch, operator reported local tests passing for global archive (9), Alpaca overnight (8), pre-open benchmark (4) and post-open benchmark (4). These are scoped unit tests, not a full release acceptance or investment claim.

    .venv/bin/python -m scripts.benchmark_global_open
    nice -n 15 ionice -c 3 .venv/bin/python -m scripts.benchmark_intraday_selective

Pre-open study: 60 observed dates, 56 paired dates, 27 out-of-sample sessions; decisions 09:10 IST. Opening gap accuracy domestic/global/combined 40.74%/51.85%/44.44%; first 15 minutes 48.15%/40.74%/40.74%; first 30 minutes 44.44%/44.44%/37.04%. Combined Brier/log loss worse than domestic in all three. No demonstrated global lift in this sample; no justification to purchase more intraday global data. Local report results/global_open_baseline_2026-08-29_2026-11-27.json.

Post-open study: 124 observed dates, 83 index and 54 matched constituent out-of-sample dates, 10 clock/horizon cells. Fixed 60% uncalibrated directional threshold, one-minute delayed index-open reference and hypothetical 5 bps cost. Selected after looking at results: 09:20 / 30m selective index took 13/83 opportunities, 9 directional successes (69.2%), +7.835 bps mean net proxy; 09:30 / 30m selective constituent took 23/54, 65.2% direction, +1.164 bps proxy; primary 09:30 / 15m was negative. These are small, post-hoc candidates, not proof of edge. Do not sum overlapping cells or deploy. Local report results/intraday_selective_2026-06-01_2026-11-27.json.

These two experiments are **closed as exploratory** pending genuinely new evidence. The next work is the five-year continuous forecast, not more fixed-time tests. All original historical strategy/membership reports and exact older instructions remain available in the pinned Git history below.

## Trading and execution research

The user's research target is BANKNIFTY options; other markets are context, not additional trading targets. Existing read-only/manual cockpit and paper research are separate from core forecasting. Preserve directional and separate spread panels, live versus historical modes, latency and source age. Do not route orders.

Existing commands (use --help and the actual code before running; no additional trade approvals):

    bash run.sh banknifty-math --sessions 90 --capital 17000 --budget 12000 --lot-size 30 --max-lots 3 --wings 5
    bash run.sh banknifty-sector --sessions 90 --capital 17000 --budget 12000 --lot-size 30 --wings 10
    bash run.sh banknifty-capped --sessions 90 --capital 17000 --budget 12000 --lot-size 30 --max-lots 3 --wings 10
    bash run.sh cpr-research --help

These are specific historical research parameters, not current guaranteed lot sizes or recommended positions. The math/sector/capped studies have modeled +10% net premium target and -5% net mark stop; INR 30/order flat all-in assumption (INR 60 per completed roundtrip) superseded older 35/75 bps scenarios only in specified research versions. Other models/fee modules have their own conventions. Not actual Zerodha tariff, executable quote or guaranteed stop. CPR, EMA, momentum/reversal, option selection, target-capped and supervised correction, offline-Q exits and spread research remain exploratory; refer to saved result evidence and archived protocols. Fixed target/stop, delayed/gap recovery, ambiguous OHLC touch, funding, lot size and loss caps require explicit treatment. No hiding unfilled/unresolved/censored outcomes.

A future real-execution benchmark must use the correct exact instrument, expiry, lot/units, premium and feasible timestamps; buy at ask/sell at bid (or documented conservative execution model), actual fee schedule including taxes and exchange charges, realistic latency, book/depth quality, liquidity, missing fills and risk limits. Bid-ask spreads can consume apparent arbitrage. Report traded and abstained decisions, net returns, drawdown, costs and sample uncertainty; separate index direction from options profit. Paper/retrospective outcomes do not authorize live orders. Never present a theoretical price or rolling expired strike history as an executable quote.

## Acceptance, security and maintenance

- **Code status:** inspect actual current branch/commit, pending PR and workflows; do not treat mergeable as merged, a previous CI pass as a new commit pass, or unit tests as end-to-end acceptance. Check current browser workflow, build, Python tests and targeted tests at a safe time. Keep main as stable release; no force push or deletion of user data.
- **Evidence status:** report exact observed counts/intervals, SHA and date spans; data stored vs independently validated vs sufficient for a model. Code-ready/theoretical/seeded/observed are different. Preserve missing input reasons; no automatic fabricated recovery, invented event time or historical depth.
- **Empirical status:** date-block split, source/clock provenance, model/label versions, baseline comparisons, calibration, missingness and independent confirmation; never optimize on the held-out set then call it untouched. Save original outputs, predictions and failures. A negative or no-trade result is acceptable.
- **Operations:** bounded worker concurrency, checkpoint and journal recovery, process-local credentials, non-destructive archives, local-only capture, rate/pressure guards, token rotation; inspect actual provider responses without leaking secret bodies. No heavy model runs competing with live data. Explicit approval for paid/licensed collection, deletion or changes to live configuration.
- **Documentation:** amend this README for accepted changes, with dated evidence, remaining blockers, commands and next priority. Keep generated reports in ignored results/ and source files in their proper locations. Do not create a new roadmap or duplicate prose status. Original detail remains pinned below. Future agents must start here and check actual implementation and saved evidence rather than treating old archived instructions as current.

## Historical documentation and recovery

The 85 superseded prose files were removed from the active working tree and the root README was replaced by this guide. Original contents, including exact historical mathematical equations, commands, audit details, acceptance matrices, research protocols and source references, remain in immutable pre-consolidation commit 9e0767dda26153a0b4b8c7cfb143e598f4023737. This is an intentional consolidation, not a claim that every historical experiment is current. The archived documents can conflict with later decisions; use them only for original details/provenance, never as a competing roadmap. No market data, notebook, result CSV, source code, model or machine-readable review template was removed by the documentation cleanup. Two old public documentation links were redirected here.

- [Full previous repository](https://github.com/5urabhi/Quantlab/tree/9e0767dda26153a0b4b8c7cfb143e598f4023737)
- [All previous docs/](https://github.com/5urabhi/Quantlab/tree/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs)
- [Previous quickstart](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/GETTING_STARTED.md) and [React guide](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/REACT_WORKSTATION.md)
- [Detailed model equations and API](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/MODEL_LABORATORY_GUIDE.md) / [metric reference](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/METRIC_REFERENCE.md) / [math acceptance](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/MATHEMATICAL_ACCEPTANCE.md)
- [Previous implementation register, forecast details and known limits](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/QUANTLAB_CURRENT_WORKLIST.md) / [release evidence](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/QUANTLAB_STATUS.md)
- [Historical data preparation](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/BANKNIFTY_DATA_PREPARATION.md) / [dated NSE clocks](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/NSE_SESSION_POLICY.md) / [optional global integrations and original experiment protocol](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/GLOBAL_MARKET_DATA.md)
- [Constituent studies](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/CONSTITUENT_ALPHA_RESEARCH.md) / [CPR studies](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/CPR_HYBRID_RESEARCH.md) / [Trading Cockpit](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/TRADING_COCKPIT.md) / [spread studio](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/SPREAD_TRADING_STUDIO.md)
- [Original empirical data guide](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/EMPIRICAL_DATA_GUIDE.md) / [research protocol](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/RESEARCH_PROTOCOL.md) / [reproducibility](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/QUANTLAB_REPRODUCIBILITY.md) / [local CSV contract](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/data/README.md)

Recover or inspect old text without restoring extra files into the active tree:

    git show 9e0767dda26153a0b4b8c7cfb143e598f4023737:docs/QUANTLAB_CURRENT_WORKLIST.md
    git ls-tree -r --name-only 9e0767dda26153a0b4b8c7cfb143e598f4023737 -- docs

### Archive inventory

For completeness, every replaced or removed human-readable source is accessible at the pinned revision:

- [GETTING_STARTED.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/GETTING_STARTED.md)
- [REACT_WORKSTATION.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/REACT_WORKSTATION.md)
- [README.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/README.md)
- [data/README.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/data/README.md)
- [docs/ADVANCED_OPTIONS_ANALYTICS.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/ADVANCED_OPTIONS_ANALYTICS.md)
- [docs/ADVANCED_SELECTION_VALIDATION.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/ADVANCED_SELECTION_VALIDATION.md)
- [docs/ALL_MODELS_REAL_DATA_AUDIT.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/ALL_MODELS_REAL_DATA_AUDIT.md)
- [docs/ANOMALY_DETECTOR_AND_EVIDENCE_INVESTIGATION.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/ANOMALY_DETECTOR_AND_EVIDENCE_INVESTIGATION.md)
- [docs/BANKNIFTY_CONSTITUENT_INTELLIGENCE.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/BANKNIFTY_CONSTITUENT_INTELLIGENCE.md)
- [docs/BANKNIFTY_DATA_PREPARATION.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/BANKNIFTY_DATA_PREPARATION.md)
- [docs/BANKNIFTY_DEPTH_RECEIPT_DIAGNOSTICS.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/BANKNIFTY_DEPTH_RECEIPT_DIAGNOSTICS.md)
- [docs/BANKNIFTY_DHAN_ACTIVITY_COVERAGE_AND_SPREAD_FEASIBILITY.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/BANKNIFTY_DHAN_ACTIVITY_COVERAGE_AND_SPREAD_FEASIBILITY.md)
- [docs/BRANCH_RECONCILIATION_AND_LOCAL_ACCEPTANCE.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/BRANCH_RECONCILIATION_AND_LOCAL_ACCEPTANCE.md)
- [docs/CASE_STUDY_NIFTY_MULTIFACTOR.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/CASE_STUDY_NIFTY_MULTIFACTOR.md)
- [docs/CODE_STATUS.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/CODE_STATUS.md)
- [docs/CONSTITUENT_ALPHA_RESEARCH.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/CONSTITUENT_ALPHA_RESEARCH.md)
- [docs/CONSTITUENT_PROSPECTIVE_CLOSEOUT.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/CONSTITUENT_PROSPECTIVE_CLOSEOUT.md)
- [docs/CPR_HYBRID_RESEARCH.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/CPR_HYBRID_RESEARCH.md)
- [docs/DATA_MANAGER_MODEL_ACQUISITION.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/DATA_MANAGER_MODEL_ACQUISITION.md)
- [docs/DHAN_20_DEPTH_STACKED_FRAME_FIX_20261123.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/DHAN_20_DEPTH_STACKED_FRAME_FIX_20261123.md)
- [docs/DHAN_ALL_BANKNIFTY_OPTIONS_ADAPTIVE_COVERAGE.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/DHAN_ALL_BANKNIFTY_OPTIONS_ADAPTIVE_COVERAGE.md)
- [docs/DHAN_API_SETUP.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/DHAN_API_SETUP.md)
- [docs/DHAN_BANKNIFTY_FULL_UNIVERSE_MONITOR.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/DHAN_BANKNIFTY_FULL_UNIVERSE_MONITOR.md)
- [docs/DHAN_CANBK_TIMESTAMP_RECOVERY_20261121.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/DHAN_CANBK_TIMESTAMP_RECOVERY_20261121.md)
- [docs/DHAN_DEPTH_RECEIPT_DIAGNOSTICS.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/DHAN_DEPTH_RECEIPT_DIAGNOSTICS.md)
- [docs/DHAN_NOV23_SOURCE_QUALITY_AUDIT.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/DHAN_NOV23_SOURCE_QUALITY_AUDIT.md)
- [docs/EMPIRICAL_DATA_GUIDE.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/EMPIRICAL_DATA_GUIDE.md)
- [docs/FINAL_STUDY_HANDOFF.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/FINAL_STUDY_HANDOFF.md)
- [docs/FULL_SAVED_DATA_MODEL_VERIFICATION.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/FULL_SAVED_DATA_MODEL_VERIFICATION.md)
- [docs/GITHUB_BRANCH_HYGIENE.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/GITHUB_BRANCH_HYGIENE.md)
- [docs/GITHUB_RENAME_AND_MORE_TOOLS_NAVIGATION.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/GITHUB_RENAME_AND_MORE_TOOLS_NAVIGATION.md)
- [docs/GLOBAL_MARKET_DATA.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/GLOBAL_MARKET_DATA.md)
- [docs/INDEX_BUILDER_V2_WORKFLOW.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/INDEX_BUILDER_V2_WORKFLOW.md)
- [docs/INSTITUTIONAL_MODELING.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/INSTITUTIONAL_MODELING.md)
- [docs/LEGACY_MOMENTUM_README.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/LEGACY_MOMENTUM_README.md)
- [docs/LIQUIDITY_SPREADS_RESEARCH_WORKSTATION.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/LIQUIDITY_SPREADS_RESEARCH_WORKSTATION.md)
- [docs/LOCAL_ACCEPTANCE.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/LOCAL_ACCEPTANCE.md)
- [docs/LOCAL_RUN.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/LOCAL_RUN.md)
- [docs/MANUAL_OPTIONS_WORKFLOW.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/MANUAL_OPTIONS_WORKFLOW.md)
- [docs/MARKET_DATA_WORKSPACE.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/MARKET_DATA_WORKSPACE.md)
- [docs/MARKET_PATTERN_INTELLIGENCE.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/MARKET_PATTERN_INTELLIGENCE.md)
- [docs/MATHEMATICAL_ACCEPTANCE.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/MATHEMATICAL_ACCEPTANCE.md)
- [docs/MATHEMATICAL_MODELS.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/MATHEMATICAL_MODELS.md)
- [docs/MATH_CATALOG.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/MATH_CATALOG.md)
- [docs/METRIC_REFERENCE.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/METRIC_REFERENCE.md)
- [docs/MODELS_DATA_CENTER_REDESIGN.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/MODELS_DATA_CENTER_REDESIGN.md)
- [docs/MODEL_CATALOG_V3_WORKFLOW.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/MODEL_CATALOG_V3_WORKFLOW.md)
- [docs/MODEL_LABORATORY_GUIDE.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/MODEL_LABORATORY_GUIDE.md)
- [docs/NIFTY_SOURCE_COMPLETION.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/NIFTY_SOURCE_COMPLETION.md)
- [docs/NSE_AUTOMATED_SOURCE_WORKFLOW.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/NSE_AUTOMATED_SOURCE_WORKFLOW.md)
- [docs/NSE_DATA_ACCESS_REQUEST.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/NSE_DATA_ACCESS_REQUEST.md)
- [docs/NSE_SESSION_POLICY.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/NSE_SESSION_POLICY.md)
- [docs/ONE_CLICK_HISTORICAL_COMPLETION_AND_RUN.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/ONE_CLICK_HISTORICAL_COMPLETION_AND_RUN.md)
- [docs/OPTION_FEED_STORAGE_RECOVERY.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/OPTION_FEED_STORAGE_RECOVERY.md)
- [docs/PAPER_EXECUTION_AND_DEPTH_REPLAY.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/PAPER_EXECUTION_AND_DEPTH_REPLAY.md)
- [docs/QUANTLAB_COMPLETION_AUDIT.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/QUANTLAB_COMPLETION_AUDIT.md)
- [docs/QUANTLAB_CURRENT_WORKLIST.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/QUANTLAB_CURRENT_WORKLIST.md)
- [docs/QUANTLAB_RELEASE_AND_SHOWCASE_20261113.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/QUANTLAB_RELEASE_AND_SHOWCASE_20261113.md)
- [docs/QUANTLAB_REPRODUCIBILITY.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/QUANTLAB_REPRODUCIBILITY.md)
- [docs/QUANTLAB_RESEARCH_COMPLETION_GUIDE.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/QUANTLAB_RESEARCH_COMPLETION_GUIDE.md)
- [docs/QUANTLAB_ROADMAP_ACCEPTANCE_20261113.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/QUANTLAB_ROADMAP_ACCEPTANCE_20261113.md)
- [docs/QUANTLAB_STATUS.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/QUANTLAB_STATUS.md)
- [docs/QUANTLAB_USER_GUIDE.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/QUANTLAB_USER_GUIDE.md)
- [docs/QUANTLAB_V2_SCREEN_CONTRACTS.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/QUANTLAB_V2_SCREEN_CONTRACTS.md)
- [docs/QUANTLAB_V2_UX_BLUEPRINT.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/QUANTLAB_V2_UX_BLUEPRINT.md)
- [docs/RECORDER_STORAGE_RELIABILITY.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/RECORDER_STORAGE_RELIABILITY.md)
- [docs/RESEARCH_ANALYTICS_CLOSEOUT.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/RESEARCH_ANALYTICS_CLOSEOUT.md)
- [docs/RESEARCH_ASSISTANT.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/RESEARCH_ASSISTANT.md)
- [docs/RESEARCH_INTEGRITY_AND_LEARNING.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/RESEARCH_INTEGRITY_AND_LEARNING.md)
- [docs/RESEARCH_METHODS.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/RESEARCH_METHODS.md)
- [docs/RESEARCH_PROTOCOL.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/RESEARCH_PROTOCOL.md)
- [docs/RESEARCH_WORKSPACE_GUIDE.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/RESEARCH_WORKSPACE_GUIDE.md)
- [docs/RESULTS_PRESENTATION.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/RESULTS_PRESENTATION.md)
- [docs/SHOWCASE_AND_VIDEO.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/SHOWCASE_AND_VIDEO.md)
- [docs/SPREAD_TRADING_STUDIO.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/SPREAD_TRADING_STUDIO.md)
- [docs/START_HERE_RESEARCHER.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/START_HERE_RESEARCHER.md)
- [docs/THREE_STUDIES_RESEARCH_ACCEPTANCE.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/THREE_STUDIES_RESEARCH_ACCEPTANCE.md)
- [docs/TRADING_COCKPIT.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/TRADING_COCKPIT.md)
- [docs/TRADING_LOCAL_ACCEPTANCE.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/TRADING_LOCAL_ACCEPTANCE.md)
- [docs/UI_V3_IMPLEMENTATION.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/UI_V3_IMPLEMENTATION.md)
- [docs/V2_DATA_RESULTS_JOURNAL_UI_SIMPLIFICATION.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/V2_DATA_RESULTS_JOURNAL_UI_SIMPLIFICATION.md)
- [docs/V2_TRADING_PROJECTS_SETTINGS_UI_ACCEPTANCE.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/V2_TRADING_PROJECTS_SETTINGS_UI_ACCEPTANCE.md)
- [docs/archive/CODE_STATUS_legacy_20261113.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/archive/CODE_STATUS_legacy_20261113.md)
- [docs/archive/README_legacy_20261113.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/archive/README_legacy_20261113.md)
- [docs/archive/SHOWCASE_AND_VIDEO_legacy_20261113.md](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/docs/archive/SHOWCASE_AND_VIDEO_legacy_20261113.md)
- [public/data/README.txt](https://github.com/5urabhi/Quantlab/blob/9e0767dda26153a0b4b8c7cfb143e598f4023737/public/data/README.txt)

**End of canonical guide.**
