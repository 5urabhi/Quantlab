# QuantLab — Canonical project guide

**Last consolidated: November 27, 2026.** This README is the single maintained human-readable project document. Before implementing, researching, reviewing, planning, or merging QuantLab changes, **read this file first**. Update the relevant section here whenever scope, commands, verified evidence or priorities change. Do not create parallel roadmaps, status files, or general-purpose guides. Source code, tests, machine-readable configurations and generated local research artifacts remain separate. If the code, a dated data audit, or current tests contradict an older description, report the discrepancy and correct this README rather than claiming completion.

## Contents

1. [Mission and scope](#mission-and-scope)
2. [Current evidence and priorities](#current-evidence-and-priorities)
   - [Live research checklist](#live-research-checklist)
   - [End-to-end option decision research roadmap](#end-to-end-option-decision-research-roadmap)
   - [Implemented capability inventory](#implemented-capability-inventory)
   - [Experiment and evidence register](#experiment-and-evidence-register)
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

**The final product objective, reaffirmed by the project owner on November 27, 2026, is an intelligent BANKNIFTY options decision-support and research system.** At each eligible decision, determine whether to enter, which exact CE/PE contract or supported defined-risk spread to select, at what price and size, how long to hold, whether to continue holding or exit/adjust as conditions change, and when to abstain. Optimize net option returns subject to risk, liquidity, funding, cost and evidence constraints; a correct underlying direction alone is insufficient. The user wants a minutes-scale research edge rather than a speed competition with institutional market makers.

**The immediate P0 research priority is reliable, actionable BANKNIFTY direction forecasting for eventual real manual options trading.** The project owner explicitly requires directional evidence before proceeding to option selection, premium prediction or execution policies. A completed negative experiment is not a qualified predictor. The intended product is practical decision support, with a visible UP / DOWN / NO TRADE state and source freshness; not a purely academic result. It is the foundation for option-premium forecasting and the decision policy, NOT the finished product. Train on approximately five years of verified core history and update predictions as completed candles arrive. Then estimate the distribution of actual option premium changes and execution costs using shorter, supported option/depth histories; integrate existing contract selection, sizing, paper management and execution evidence. Do not replace this goal with fixed-time daily predictions, endless new provider onboarding, more infrastructure, or another unvalidated strategy grid. Preserve existing mathematical, index and risk research tools as secondary capabilities.

The intended deliverable is a research-validated recommendation/decision workflow and prospective paper simulator, not authorization to send live broker orders. Actual returns are uncertain; a valid research result may conclude that no net edge is demonstrable.

The forecast should give UP/DOWN/FLAT probabilities (with an explicit flat definition), coherent expected OHLC/return, volatility, relevant first-passage/price-level probabilities and useful uncertainty for the next 1/5/10/15/30/60-minute horizons (start with the existing 5-minute implementation; other horizons require explicit label definitions and validation). A rolling five-minute forecast at each minute is not the same as a forecast on non-overlapping five-minute clock boundaries; identify the mode in results. Distinguish predicted price direction from probability of profitable option execution. No live model promotion or broker orders are authorized by a research result.

Other existing product capabilities must remain usable: Guided Research; mathematical model laboratory; equity index/factor and risk studies; Data Centre/Market Library; saved experiments, charts and results; read-only live and historical Trading Cockpit; separate directional, spread and paper-research workflows. Use existing modules rather than build a second application.

**Rules for future work:** prediction first, strategy second, execution third. Reuse the canonical market store and supported models. Start with a small verifiable change, measure the result, and expand only if it materially serves the current goal. Do not promise a trading edge, claim a complete dataset from a requested range, or report synthetic results as actual evidence.

## Current evidence and priorities

This is a dated evidence register, not a new independent acceptance run. Local output provided by the operator and checked repository code are distinct from CI and empirical validation.

| Area | Evidence / current state | Limits / remaining work |
| --- | --- | --- |
| BANKNIFTY minute history | Prior five-year local preparation audit: 1,190 complete regular comparison sessions, 52 partial sessions, 6 repair windows; roughly 446,250 complete-session candles before filtering | Re-audit the exact current store; 375-slot comparison window is not every exchange session or full derivative session |
| Indian equity history and peer indices | Original verified receipts and dated membership loaders exist; prior audited exact 16-stock union; NIFTY 50 and other indices available with differing coverage | Do not assert five years of complete constituent or peer data; audit per identity/session, including corporate actions and incomplete files. The previous Nov 27 inventory of 60 original equity minute histories (5,081,826 manifest-reported rows, about a one-year range) and later five-year PIT bank audit are different source scopes. |
| Dated BANKNIFTY membership | Reconstructed archive documented through 2026-10-13 in the reported local audit | 29 evaluation dates lacked membership in the previous 365-day sequence experiment; no dated weight snapshots found in that audit. No guessed members or weights |
| Historical options | Prior local sample: 90 sessions, rolling near-month ATM +/-3, 461,927 bars with OI/IV, 924 verified receipts | Not a complete one-year exact-contract option archive, quote book, or bid/ask fill history |
| Daily global | FRED and Alpaca configured; prior inventory seven US ETF proxy series with 1,441 rows each starting November 2021; Nikkei/FRED and other macro archive observations starting March 2024 | Archive assumptions differ from historical live receipt; no exact global intraday index substitution |
| Overnight global | Existing authorized Alpaca BOATS feed: operator's 90-calendar-day run (2026-08-29 to 2026-11-27 exclusive) returned 18,178 observed five-minute bars across ten ETFs | US-listed proxy trades, not Asian cash indices or GIFT NIFTY; delayed and often sparse; automatic collection configured, continuous operation not yet verified |
| Live recorder | Dhan quotes, OI, option chains, depth, stock context and storage guards implemented | Check actual packet age, drops, entitlements, storage and session boundaries; no historical depth reconstruction |
| Forecast engines | Rolling next-five-minute OHLC and optional PyTorch multi-asset sequence research already implemented; source-aware, chronological evaluation | The OHLC runner completed a local 1,825-calendar-day index-only ridge/logistic run over 1,231 observed sessions; all 10 scoped tests passed. No confirmed close/direction improvement; contextual and sequence runs remain capped at 400 days. **Five-year continuous multi-horizon model is not complete** |
| Opening experiments | Pre-open global and post-open selective baseline scripts implemented and local tests passed in the global-opening-context branch | Exploratory only; not a substitute for rolling forecast, not approved strategies |
| Software | Local workstation and prior software/browser acceptance documented; latest global-opening-context branch unit tests reported passing for its scoped experiments | Re-run full CI and local acceptance at the actual commit; local data readiness and model performance are separate |
| Live trading | Read-only research, manual workflow, simulation/paper and modeled costs | No automated broker orders. No validated production model or independently reproduced profitable strategy |

**Priority register (the next tasks, in order):**

- **P0 — Forecast dataset and existing engine audit.** Inspect the existing rolling OHLC/sequence code, source manifests, local five-year audit and model results. Verify actual distinct eligible completed bars, source hashes, time ranges, missing groups, memory/IO bounds, and prior examined evaluation dates. Reuse the five-year original receipts; no fresh mass download merely because a shorter model loader currently rejects a longer range.
- **P0 — Extend existing core forecast to five years.** Build bounded/session-partitioned or streaming input assembly, train/evaluate core index-only on the verified long history, and retain shorter optional context lanes. Benchmark simple training-only baselines and existing ridge/hist-gradient/logistic methods first. Add a supported tree/sequence model only when justified. No indiscriminate grid search, unbounded option extraction or all-or-nothing full-feature intersection.
- **P0 — Direction qualification gate (CURRENT).** The five-year binary close/OHLC, matched domestic and crossover first-passage studies did not qualify. The owner now requests a custom model that discovers relationships from synchronized multi-instrument histories, rather than restricting learning to predefined events. Use the fixed MarketDynamics study below: all eligible minutes, six horizons, early-session support, delayed open-to-open outcome, explicit flat class, calibrated confidence and abstention. Do not prioritize premium forecasting until a useful directional signal has retrospective and prospective evidence. If it fails, report no qualifying signal and investigate a genuinely different information hypothesis, not a threshold/model search on the same holdout.
- **P0 — Define causal targets and assessment.** Every eligible completed candle, explicit clock and horizon, no lookahead, no cross-session target unless separately studied. Whole-session chronological development/calibration/test, purging/embargo where required, date-weighted results and uncertainty; genuinely new sessions for prospective confirmation. Save original predictions and outcomes.
- **P1 — Incremental context lift.** Compare on matched dates/anchors: core vs bank breadth/relative volume; peer indices; eligible daily/overnight macro; options/OI/IV; actual receipt-time depth where available. Use masks/fallbacks, not fabricated inputs or five-year imputed live-book history. Do not make full-history training wait for shorter sources.
- **P1 — Continuous research inference.** Integrate a validated frozen model into the existing UI with per-horizon forecasts, calibrated probabilities, uncertainty, current timestamps, source coverage and abstention. Record outcomes and monitor drift; keep stale/unvalidated models visibly unavailable. No auto-order path.
- **P1 — Later execution research.** Only after predictive evidence, test CE/PE contract selection, actual quote sides, lot sizes, fees, delay and fills, with funding/risk constraints and a separate spread experiment.
- **P2 — Deferred unless needed.** New external provider onboarding (including JForex), five-year foreign intraday data, deep/RL expansion, additional fixed-time strategy grids, speculative architecture rewrites. Keep authorized existing collectors running; focus on predictive performance. Repair material data-quality gaps and protect live capture, but do not make peripheral infrastructure a prerequisite for the core study.

### Live research checklist

Read this at the beginning of every task. Update this same checklist on each evidence-backed change; no separate roadmap. GitHub task boxes distinguish **implemented**, **attempted** and **accepted**. A checked attempt can have a negative result. A checked code change is not a passed local test. Pending work is unchecked, not concealed as a success. Record report paths, source scope, dates and limitations in the evidence register. Work in phase order; do not jump to speculative new experiments.

**Phase 0 — Data and project direction**
- [x] Define the BANKNIFTY options decision-support end goal and canonical documentation.
- [x] Implement read-only shared storage, original receipt verification, market library, resumable history and live collection.
- [x] Attempt five-year historical BANKNIFTY acquisition and report complete/partial sessions; prior local audit: 1,190 complete, 52 partial.
- [x] Attempt authorized global data pilot (30/90-day BOATS, existing daily archive); keep provider/coverage caveats.
- [x] Implement dated bank membership, option history, depth recording and current-session policy.
- [ ] Verify current exact five-year local audit, verified source identities/date spans and expected-session gaps; distinguish requested and observed coverage.
- [ ] Reconcile live recorder freshness, option and bank coverage, calendar and source gaps that actually block later phases. No unnecessary new provider.

**Phase 1 — Five-year rolling forecast and directional qualification (CURRENT P0; acceptance blocking)**
- [x] Audit existing OHLC/sequence code: five-minute OHLC target, 60-minute inputs, chronological session split, current contextual and sequence limits 400 calendar days; reuse original index receipt loader.
- [x] Implement original shorter-history rolling OHLC and optional CNN/GRU/Transformer engines.
- [x] Attempt prior shorter-history model/sequence study (245 sessions reported); original metrics still need reconciliation.
- [x] Implement explicit bounded index-only long-history mode for the existing OHLC runner, up to 1,827 calendar days. Avoid bank/peer/options loads, reuse core features, preallocate core matrix, record actual date span and matrix size. Context and sequence runners retain 400-day bounds.
- [x] Pass new and existing OHLC unit tests on 3cabad7: 10/10 passed locally (0.274s). Five-year core matrix built (510,912,220 bytes; not total process peak RAM).
- [x] Full software CI at d85dc92: Verify React quant research workstation and QuantLab Ubuntu browser acceptance both succeeded. Previous guide regression resolved; this is software acceptance, not model approval.
- [ ] Measure peak memory/IO and verify local end-to-end operational acceptance; core matrix size alone is not peak RAM.
- [x] Attempt the frozen five-year core ridge/logistic baseline on saved data; completed on 3cabad7 with 1,231 observed sessions, 44,433 train windows, 76,817 evaluated predictions. Result: no_confirmed_ohlc_improvement. Record in experiment ledger.
- [ ] Independently reconcile original forecast JSON/CSV, receipt hashes, eligible dates, prediction counts and peak resource usage against current local audit (console output alone does not establish full provenance).
- [x] Attempt five-year ridge vs histogram-gradient comparison on 7f1944f; same 1,231 observed sessions and 76,817 evaluation rows. Validation selected histogram gradient; evaluation state no_confirmed_ohlc_improvement. Record prior examined dates, OHLC and probability scores below.
- [x] Implement explicit index-only 1/5/10/15/30/60-minute horizon labels with horizon-sized training stride; implement training-only volatility-adaptive comparator, descriptive reliability bins and paired 5-session block uncertainty. All 14 scoped tests passed on d85dc92 (0.345 s); All six horizon runs subsequently completed; see the closed benchmark below.
- [x] Pass updated multi-horizon regression tests (14/14) and attempt the 15-minute comparison on d85dc92. Result: no_confirmed_ohlc_improvement; volatility-adaptive and constant-prior comparators outperform the selected ML model.
- [x] Attempt remaining fixed core horizon comparisons (5m adaptive, 10m, 30m, 60m, 1m) on bac7f53. All six horizons rejected: selected ML loses to adaptive range and constant-prior probability comparators; report below. Actual peak RAM not measured.
- [ ] Extend early-session coverage, explicit UP/DOWN/FLAT and movement/volatility/first-passage probability distribution (current horizon extension retains 60-minute input and binary up-vs-not-up label).
- [x] Implement the fixed five-year material-direction benchmark using the existing three-class protocol, 16 completed input bars, one-minute delay, 5m outcome, +/-5 bps deadband, validation-only temperature calibration and 60% confidence abstention. All 3 scoped tests passed and the five-year run completed on 8a3b138; qualification failed.
- [x] Pass directional benchmark tests (3/3) and run fixed five-year protocol. 87,191 evaluation anchors, 38 calibrated calls across 17 days; day-weighted material hit 40.29%, mean net proxy -2.981 bps/called opportunity. State direction_not_qualified; see ledger.
- [x] Implement a fixed matched EMA 9/21 and level-event hypothesis after the owner's observation of BANKNIFTY breakouts/reversals near prior OHLC/CPR and today's ranges. The new optional direction mode seeds one-minute EMAs from the preceding complete weekday, computes prior-day levels and causal developing levels, and encodes breakouts, retests/rejections and one-bar failed breakouts. Original 16-minute direction comparator retained; 5/5 tests passed and matched five-year run completed on fa691f7. Qualification failed.
- [x] Pass EMA/CPR tests (5/5) and attempt matched five-year study: 81,543 evaluation anchors across 231 supported sessions, 63 calls across 14 sessions, 49.86% day-weighted material hit, -1.70 bps mean proxy per call. Conditional sign Brier worsened vs matched core; not qualified.
- [x] Implement descriptive five-year fresh EMA 9/21 crossover-to-opposite-crossover path audit: variable duration, favorable/adverse excursion, time to extreme, giveback, CPR zones, censoring and separately delayed open proxy. All 4 scoped tests passed and five-year audit completed on 8934004.
- [x] Run EMA path audit: 19,431 paths, 18,316 complete, 1,115 censored, 16,821 delayed index-open references. Median complete favorable excursion 30.55 points, time to extreme 4 minutes, opposite cross 13 minutes, giveback 60.05 points. Only 17.96% of delayed scored references positive after assumed 5bps. Descriptive result, not qualified.
- [x] Implement descriptive frozen-level EMA path audit requested by owner: previous OHLC, CPR/pivots, developing current OHLC and opening range; per-direction touch/breakout/failure counts, time to breach, first rejection/failed-break follow-up depth and reclaim time, censoring and explicit denominators. All 5 tests passed; five-year study completed on ebff6e4.
- [x] Run level-path audit: 19,431 crossovers x 20 frozen levels = 388,620 rows, matching original path counts. Five tests passed. High rates of subsequent recross after confirmed level break; report in ledger. Descriptive, not qualified.
- [x] Implement cross-instrument replication using existing peer indices and dated bank constituent sources, matched dates and scheduled comparison prefixes, all 20 levels and normalized bps. All 13 related tests passed and all 23 lanes ran on b0e731c.
- [x] Run cross-instrument replication: 9 peers x 228 matched sessions, 14 bank lanes x 181-202 sessions; 82,283 comparison-instrument crossovers, all 23 lanes assessed. Descriptive only; no synchronized predictive evidence.
- [x] Implement synchronized BANKNIFTY crossover first-passage benchmark with separate matched bank, peer/VIX, rolling-option, global daily and overnight ETF lanes; exact EMA/level states, no invented weights or future outcome features. Four tests and both CI workflows passed; both historical runs completed at 790f302.
- [x] Run fixed first-passage screens: five-year 19,431 crossovers, 5,129 favorable-first / 17,693 resolved; one-year 3,877 crossovers, all supported domestic/daily lanes yielded zero >=60% calls. Overnight 52 sessions below 75 gate. No qualification. See ledger.
- [x] Implement one custom MarketDynamics model and unified bounded minute feature grid with synchronized individual asset OHLC/volume/EMA/CPR levels, earlier daily summaries, options and global context, masks, all-minute predictions and six delayed horizons. Compare fixed matched index-only neural, joint neural, latest-snapshot logistic and calibrated historical priors; separate observed excursions from fill claims. Code committed, tests/runs pending.
- [x] Attempt initial 365-day MarketDynamics on 715fd80: 4 data/scoring tests passed, 2 neural tests skipped (PyTorch not installed in existing .venv); training did not start. User requested GPU and all available timestamped data rather than the 365-day/5-minute-stride restriction.
- [x] Implement full-history MarketDynamics v2: earliest original BANKNIFTY receipt, every eligible observed minute, all earlier training history, latest-year chronological validation/evaluation; discover original local equities including nonmembers/PSU, all verified rolling family/offset streams with train support, all available timestamped global factors, completed multi-timeframe OHLC, prior/last-observed levels, EMA crossover state, and disk-backed scratch. CUDA is the full-mode CLI default; original raw data unchanged. New tests pending.
- [x] Complete V2 full-history GPU run at 98550eb: all 13 scoped tests passed, 72 instruments, 1,231 dates, 420,202 training and 18,228 each validation/evaluation anchors; all six horizons evaluated, zero >=60% neural direction calls. Both CI workflows passed. See ledger; full local JSON and CSV not independently inspected.
- [x] Implement V3 larger factorized movement/sign model, two attention/GRU/Transformer layers, completed intraday blocks and 60 prior-session sequence, instrument-specific pretraining, primary underlying-only lane and separate options ablation, matched V2/V3 journal comparison. Implement separate GPU OptionDynamics premium and IV research. Tests/runs pending.
- [x] Initial V3 operator run at bfc44c1: 18/19 MarketDynamics tests passed (including masked-loss, CUDA pretrain/fine-tune and tiny training); one synthetic test incorrectly required the 30-minute target from minute 4 to be present despite the missing minute 20. Corrected test to verify valid 5m, missing 30m, both missing across the gap, both recovered afterward and unaffected index targets. No model or missing-data policy change. Training and separate option tests did not start because the shell stopped on the failure.
- [x] V3 underlying-only full-history GPU protocol completed at c46f65f: 19/19 MarketDynamics tests, 2/2 OptionDynamics, 2/2 legacy premium tests; both GitHub CI workflows passed. 1,142,952 joint parameters, 5,264,491 observed asset-horizon pretraining labels per epoch; 420,202 training anchors, 18,228 each validation/evaluation. Overall Brier lower than V2 at all six horizons by console point estimates; directional qualification failed. See ledger.
- [x] Completed direct V2/V3 saved-journal comparison at 51d5a25: 103,733 matched scheduled outcomes, identical split definitions, decision/entry/exit keys and actual outcomes across all six horizons and 49 evaluation sessions. V3 core overall and movement Brier paired intervals favor V3 at all six; V3 joint overall at 5/10m and movement at 5/10/15/30/60m. No sign interval excludes zero for either lane. No directional qualification; no rerun required.
- [x] Separate fixed OptionDynamics premium/IV GPU study completed: 17,482 scored evaluation candidates over 47 sessions; both neural models beat corresponding linear exit-premium MAE but neither establishes improvement over no-change or base-rate direction. Option-only IV MAE small exploratory improvement over zero-change. No trading use until prospective execution qualification.
- [x] Predeclare and implement one causal first-passage crossover study (see current commands). Distinguish whether a fresh cross is likely to produce a material favorable move BEFORE an adverse move or reverse signal; calculate from delayed entry, not hindsight signal-price extreme. Compare against training-only event priors and a simple exit rule; explicitly retain unfinished/ambiguous outcomes. Proposed initial research design below; parameters require freezing before fitting. No threshold grid or prospective claims.
- [ ] If first-passage evidence warrants, learn earlier exit decisions using running favorable/adverse excursion, EMA slope/separation, level proximity and completed bars, compared with fixed opposite-cross and simple trailing exits on paired observations. Do not optimize to known peaks.
- [ ] Audit exact exchange-session continuity, official holiday/special-session gaps and wider multi-day regime context. The new mode conservatively rejects unverified missing prior weekdays and current gaps; do not claim complete multiday sequence coverage.
- [ ] Establish retrospective directional qualification against simple matched comparators; if no signal qualifies, remain in Phase 1 rather than claim success.
- [ ] Freeze a qualifying candidate and confirm it on new receipt-time shadow sessions (proposed minimum 60 new sessions and 100 calls, subject to predeclared power/support review); check calibration, coverage, both directions, stable performance and latency. No live use before qualification.
- [ ] Validate out-of-sample directional and price skill, probability calibration and prospective stability before claiming a core model is usable.

**Phase 2 — Incremental context (domestic matched benchmark closed; no established incremental skill)**
- [x] Implement bank, peer-index, options, volatility and global context inputs and original provenance.
- [x] Attempt historical constituent/peer/volatility and fixed-time global/post-open baselines; no demonstrated robust trading edge.
- [ ] Verify original local reports and dated membership/weights; compare matched causal feature ablations without shrinking the core history.
- [x] Implement separate matched five-minute bank, peer and rolling-option context ablations using existing source loaders, fixed ridge/logistic models, per-lane supported-session chronological split, equal training/evaluation anchors, adaptive comparator and validation-only sigmoid calibration. All three lanes ran on 7ab3125; 16/16 tests and both CI workflows passed.
- [x] Pass matched-context regression tests and attempt all three lanes. All failed to establish incremental forecast skill; see experiment ledger. Calibration improved raw Brier but did not establish context lift.
- [ ] Evaluate calibrated combination/fallback only if useful incremental evidence is later demonstrated (deferred after negative matched study); reserve new sessions for prospective confirmation.

**Phase 3 — Option response (independent descriptive research permitted; execution remains deferred)**
- [x] Implement original rolling option history, theoretical Greeks/IV and BSM scenarios; existing predictive_option_research and forecast_depth_research.
- [x] Attempt mathematical premium-target, sector-confirmed, capped utility and supervised correction research.
- [ ] Audit actual local option coverage, price/IV/OI/volume and exact contract identity vs rolling family.
- [x] Implement fixed direct rolling monthly premium-response benchmark using original receipt loaders, delayed five-minute open-to-open labels, option-only and option-plus-index ridge/logistic, no-change and historical bucket baselines, validation-only sigmoid calibration and matched day-block diagnostics. Implementation committed; tests and run pending.
- [x] Passed premium-response/OptionDynamics tests and ran fixed 365-day independent descriptive benchmark; documented coverage, unresolved outcomes and paired premium/probability/IV scores in ledger. No downstream V3 forecast conditioning or executable net P&L claim until direction and execution qualify.
- [ ] Fit and evaluate premium/IV response distributions conditional on supported underlying predictions; compare simple baselines and calibrate uncertainty without future option information. IV forecasts, first-passage, exact contract and execution evidence remain pending.

**Phase 4 — Contract and entry decision**
- [x] Implement option-chain inspection, liquidity/stress ranking, modeled fees, funding/whole-lot selection and separate spread scanner.
- [x] Attempt EMA/CPR, ranked-entry, conditional profitability and spread research. Earlier results negative or inconclusive.
- [ ] Connect validated frozen forecasts to causal exact-contract selection; compute expected net INR, downside, probability of net gain where supported, entry price cap and no-trade.
- [ ] Compare against simple affordable contracts and cash, use dated fees/lots/margin and realistic latency/liquidity; preserve rejected and unfilled attempts.

**Phase 5 — Holding and exits**
- [x] Implement fixed, target/stop, trailing, reversal, adaptive and pinned forecast-adaptive paper exits.
- [x] Attempt rule/ML/offline-Q exit comparisons and dynamic replay.
- [ ] Validate integrated entry/hold/exit policy on observed later paths; enforce funding, risk, liquidity, expiration, hard cutoff and unresolved-position rules.
- [ ] Show source-aware position recommendations and evidence in existing cockpit; no unrestricted averaging down.

**Phase 6 — Execution and account-level validation**
- [x] Implement original-depth replay, separate directional/spread research, cost/fee models, risk and execution stress, paper accounts.
- [x] Attempt spread and timing viability screens; no demonstrated executable net edge.
- [ ] Verify exact receipt timing, realistic bid/ask, quantity, slippage and incomplete baskets/fills; reconcile actual dated fee and margin evidence.
- [ ] Evaluate net P&L, drawdown, loss distribution and abstentions after all costs; compare no-trade, not just conditional completed trades.

**Phase 7 — Prospective paper and controlled learning**
- [x] Implement immutable candidate registry, prospective ledger, paper engine and opt-in research retraining.
- [ ] Verify actual ledger support; freeze validated model/policy and log shadow predictions/decisions against strictly new sessions.
- [ ] Confirm calibration, drift, net risk-controlled paper performance and operational integrity. A no-edge conclusion is valid; do not promote automatically.
- [ ] Only after baseline evidence, evaluate controlled offline retraining, contextual bandits or RL versus simpler policies; keep live order routing disabled.

**Completed matched V2/V3 evaluation comparison (no GPU training; reproducibility only):**

    .venv/bin/python -m scripts.compare_market_dynamics --baseline results/banknifty_market_dynamics_c13afc6a249a457e9bc5bfcaed2d9f60.json --candidate results/banknifty_market_dynamics_cc1e2cd0bf8749ecadaa6b2b8cf5d54b.json

The c46f65f V3 underlying and independent OptionDynamics runs and 51d5a25 matched comparison completed. Do not rerun merely to collect comparisons. No direction candidate qualified. Next research should isolate the conditional material sign objective and predeclare a directional diagnostic using training/validation dates only, followed by genuinely new frozen receipt-time shadow forecasts; do not choose width, thresholds, horizons or features based on the repeatedly inspected historical evaluation period. No live orders, model promotion or claimed profitability.

**Completed V3 and separate OptionDynamics commands (reproducibility only):**

    .venv/bin/python -m unittest discover -s tests -p 'test_market_dynamics*.py' -v
    .venv/bin/python -m unittest discover -s tests -p 'test_option*dynamics*.py' -v
    .venv/bin/python -m unittest discover -s tests -p 'test_option_response_benchmark.py' -v
    .venv/bin/python -m scripts.benchmark_market_dynamics --all-history --v3 --width 128 --pretrain-epochs 2 --epochs 8 --batch 32 --accumulate 4 --device cuda --to-date 2026-11-27
    .venv/bin/python -m scripts.benchmark_option_response --neural --days 365 --epochs 12 --device cuda --to-date 2026-11-27

V3 is a fixed exploratory architecture revision after the V2 negative directional result. Primary input explicitly excludes rolling options (no receipt scan needed). Same full-history split and original observed minute grid, all 83 individual asset features plus availability masks. Local 30-minute raw sequence in six ordered 5-minute patches, width 128, eight attention heads, two BANKNIFTY-query cross-asset attention layers, two GRU layers, two temporal Transformer encoder layers over up to 25 completed 15-minute current-session tokens and 60 earlier observed complete-session tokens plus local patch sequence. Long tokens are index state and observed cross-sectional feature means, dispersion and coverage; not all raw instrument candles or learned per-asset long histories. Prior dates only and completed intraday blocks only. Train shared encoder/pretrain head on instrument-specific 5/30-minute delayed returns and observed excursions at five-minute decision anchors from training dates; report actual used and available counts for each instrument. Fine-tune all eligible observed resolved BANKNIFTY minutes at six horizons; separate movement and conditional material sign BCE, coherent signed return/excursion Huber loss. Flat outcomes do not train sign; masks preserve missing outcomes. Validation rank equal average of movement and conditional sign Brier over horizons, fixed patience3, temperature calibration on validation only. Day weights, seed42, AdamW 0.0005 pretrain and 0.0003 fine-tune, 2 fixed pretrain epochs and <=8 fine-tune epochs, batch32 accumulation4. BF16 autocast projections if CUDA supports it, FP32 recurrent arithmetic, otherwise float32; no CPU fallback for requested CUDA. Gradient accumulation averages per-microbatch normalized loss. Fixed streaming SGD baseline with smaller constant learning rate to address V2 poorly performing snapshot comparator; additionally report raw-prior comparison and movement Brier. All previously examined dates exploratory. No automatic capacity grid; --width 64/256 available for separately declared future validation studies, not holdout-driven selection. Report exact model parameter counts, training/validation curves, predictions and research-only weights. Optional fixed ablation same V3 command with --include-options; train options lane separately and compare matched predictions, no claims until run.

Compare saved V2 and V3 reports without retraining V2 using:
    
    .venv/bin/python -m scripts.compare_market_dynamics --baseline results/banknifty_market_dynamics_c13afc6a249a457e9bc5bfcaed2d9f60.json --candidate results/banknifty_market_dynamics_cc1e2cd0bf8749ecadaa6b2b8cf5d54b.json

This requires identical training/validation/evaluation dates, target definition, scheduled decision keys and observed actual values; reports paired session-block differences for multiclass, movement and conditional sign Brier and return/excursion MAE. V2 versus V3 changes several architectural/training/input factors jointly, so does not isolate the effect of width/pretraining. V3 underlying versus options ablation isolates the input change more directly but remains one fixed seed. Use actual paths printed by each run.

OptionDynamics is independent, not a downstream trading decision or a V3 forecast conditioned model. Reuse verified original all-offset near-month rolling option receipts, same observed side/strike/family within day, three nearest positive-volume candidates per side within 2% and premium >=5, every fifth decision after 60 completed index minutes, fixed delayed 5m premium label. Compare neural option-only and option-plus-index (all 83 causal index features) against fixed matched ridge/logistic, no-change and bucket references. Two 128-unit MLP layers, optional masked observed vendor-IV change at exit candle close, validation-only selection/calibration, train-only scaling, prediction journal retains unresolved candidates. Exact expiry identity, historical bid/ask, fills, validated Greeks and cost-controlled P&L remain unestablished. No RL/orders or automatic model promotion. CUDA tests and empirical runs completed at c46f65f; see ledger.

**Completed full-history GPU MarketDynamics V2 (reproducibility only):**

    .venv/bin/python -c "import torch; assert torch.cuda.is_available(); print(torch.__version__, torch.cuda.get_device_name(0))"
    .venv/bin/python -m unittest discover -s tests -p 'test_market_dynamics*.py' -v
    nice -n 15 ionice -c 3 .venv/bin/python -m scripts.benchmark_market_dynamics --all-history --to-date 2026-11-27 --epochs 8 --batch 64 --device cuda

The owner explicitly requests all available time-aligned information, not just an EMA event or the shortest common archive. Full-history v2 discovers the earliest target receipt (120–3660-day explicit safety bound) and loads all verified observed BANKNIFTY dates through the exclusive requested date; every earlier eligible observed minute with an observed training outcome is used (stride 1), including after gaps; earliest completed minute at 09:16 IST with masked padding. Reserve the latest 365 calendar days' observed dates in chronological 60/20/20 portions; all earlier observed dates train. Never train on held-out labels. The model still has a 30-minute raw sequence plus causal 5/20/60-session summaries, not a single uninterrupted multiyear raw sequence. Every asset supplies relative and log-normalized one-minute OHLC, observed volume, returns/volatility, EMA9/21/50/200 distances, 9/21 separation, slope, crossing direction and time since cross, previous complete weekday OHLC/CPR/pivots, developing current OHLC/CPR, opening range and completed 5/15/30/60-minute OHLC. Separately aged last-observed complete-session OHLC avoids inventing a previous trading day on holidays/gaps. Current gaps reset EMA and mask unknowable running levels, but later observed minutes remain eligible; no labels cross missing bars. All local original 1m equity caches (NSE/BSE; <=120 explicit identity bound) are verified and included as individual streams when training supported. This includes saved PSU bank equities beyond the index membership where present, not synthetic sector membership. Only dated actual active BANKNIFTY members affect weighted or unweighted bank aggregates. Equity/rolling identities appearing only in held-out dates are audited and excluded from learned embeddings/channels. All known saved peer index/VIX histories use existing verified loaders. Original canonical BANKNIFTY rolling option receipts are inspected for all supported WEEK/MONTH, near/next/far, side and saved ATM±0..10 families; retain strike distance, normalized OHLC, volume, OI, IV and same-observed-strike changes, plus near-month aggregate. Conflicts masked, source receipts audited; no exact historical contracts, historical fill or Greeks invented. All stored supported daily/intraday global factors as of completed minute, all observed BOATS ETF proxies as of 09:10 (frozen thereafter); missing or stale factors masked. Other data such as raw live tick/depth, exact contracts, unrelated daily-only equity sources and post-09:10 BOATS updates are not yet model channels. Data are not manufactured to extend short archives. Grid uses temporary disk-backed float32 memmaps (16 GiB total bound and free-space check), not persistent copies of raw data. Option scan has explicit 12 GiB input and 2 GiB raw-array bounds. Original loader per-source read limits still apply; report failures or stop explicitly. Training-only streaming feature scaling retains short-source support; fixed logistic SGD snapshot comparator uses three passes over same resolved training rows with bounded memory. GPU training uses existing cross-asset attention/GRU, fixed six delayed horizons and validation-only selection/calibration; CPU prepares data and computes references. Session-shuffled batches preserve disk locality and use each resolved training row once per epoch. No CPU fallback if CUDA is unavailable. Research checkpoint and prediction journal, complete audit of masks/date coverage, no approved trading signal. Prior fixed short experiment retained below for reproducibility only. V2 GPU run completed at 98550eb; console evidence in ledger below.

**Earlier 365-day custom benchmark command (blocked at missing PyTorch on the first attempt):**

    .venv/bin/python -m unittest discover -s tests -p 'test_market_dynamics.py' -v
    nice -n 15 ionice -c 3 .venv/bin/python -m scripts.benchmark_market_dynamics --days 365 --to-date 2026-11-27 --epochs 8 --batch 128

The owner requested autonomous pattern discovery rather than only predefined crossover labels. Reuse the existing receipt-backed source loaders, temporal-model library, and all 20 named level definitions. One bounded in-memory feature grid over synchronized original sessions, no additional data store/download. Individual instrument channels: relative OHLC, observed volume and relative log volume, returns at 1/5/15/30/60 minutes, RMS volatility, EMA9/21/50/200 and crossing, prior-day OHLC/CPR/R1/R2/S1/S2, current developing levels/opening range, and earlier 5/20/60 observed-session daily summaries. Use complete preceding weekday EMA seed where available (otherwise explicit prior-missing flag and local seed); earlier daily summaries require complete observed source closes and are not a certified full exchange calendar. Per-instrument dated bank membership and reviewed cash hours; training-known identities only; unknown later members masked, no invented weights. Synchronized auxiliary minute context: dated bank coverage/breadth/dispersion and actual weights if available, rolling monthly options OI/IV/volume and same-strike context, pre-open daily and overnight archive-as-of 09:10 factors. India VIX is volatility context. Missing fields remain masked. Raw source grids end at the last completed minute; no final-day OHLC or future peaks in input. One fixed custom MarketDynamics architecture in the existing neural model module: five-minute ordered patch encoder, learned instrument identity, BANKNIFTY-query cross-asset attention, auxiliary context projection and GRU, joint multi-horizon classification and coherent signed return/up/down excursion heads. Use 30-minute sequence, earliest after 15 completed minutes with explicit padding, no fixed EMA event trigger. Gap terminates supported prefix; predictions for scheduled unresolved future horizons retained. Fixed horizons 1/5/10/15/30/60, one-minute delay, open-to-open return and observed extrema through exit open (exclude later exit candle extrema), +/-5 bps flat definition. Fixed 60/20/20 whole-session chronology, training stride 5 (longer targets overlap within partition), day weights, AdamW, seed42, up to eight epochs, validation Brier early stopping patience3 and validation-only temperature calibration. Compare identical anchors for index-only neural and joint neural, fixed same-scope latest-snapshot logistic, calibrated unconditional/clock priors and adaptive excursion/no-change return. Report all horizons, paired session-block Brier and material sign loss, MAE, 60% calls, cost-proxy diagnostics and unresolved outcomes; no claim of exact option P&L or trading qualification. Checkpoint explicitly research only. First run 365 days because joint archives are shorter; optional fixed long-history core run: same command with --index-only --days 1825. CPU by default, optional --device cuda only on supported local hardware. No RL yet: it requires credible exact-contract execution and risk environment. Earlier inspected dates remain exploratory. No architecture grid, post-hoc threshold selection, live deployment or auto-orders.

**Completed synchronized first-passage crossover study commands (reproducibility only):**

    .venv/bin/python -m unittest discover -s tests -p 'test_ema_first_passage.py' -v
    nice -n 15 ionice -c 3 .venv/bin/python -m scripts.benchmark_ema_first_passage --index-only --days 1825 --to-date 2026-11-27
    nice -n 15 ionice -c 3 .venv/bin/python -m scripts.benchmark_ema_first_passage --days 365 --to-date 2026-11-27

The cross-market replication is finished. Freeze the previously proposed first-passage thresholds (+10bps favorable / -5bps adverse), a one-minute delay and fixed 60% probability gate; these are illustrative research values, not option breakeven levels. At each fresh 1m EMA 9/21 BANKNIFTY signal, use current and previous-session levels, all 20 named frozen distances, nearest ahead/behind level, completed returns/volatility and cross direction. Label whether the favorable barrier touches first from the delayed entry reference open, before or within the next opposite cross candle; adverse first or opposite cross without either barrier is resolved nonsuccess. Same-bar dual touches ambiguous, known early reversals canceled, unobserved entries/gaps/end-of-session retained. No fixed holding period or future peak exit. Fit fixed ridge-family logistic only, day weighted, training-only feature support, validation-only sigmoid calibration. Predict on every context-supported evaluation event including unresolved outcomes; scores conditional on resolvable paths, report actual and possible favorable fractions over all selected candidates and outcome counts. Compare with matched calibrated training and direction/30-minute clock priors. Each context lane reserves its own 60/20/20 dates based on available signal-time events before filtering outcomes (>=75 supported dates, >=40/15/15 resolved sessions and both classes); refit index-only comparator on exactly the same rows. Banks: dated membership, returns, relative volume, breadth, scheduled open, same-clock exact EMA9/21 and prior level distance for each member. Peers: returns, volatility, VIX context and same-clock equity-index EMA and levels. Options: original rolling monthly ATM +/-3 receipt context with same completed candle stamps and earlier same-strike reference; not exact contracts. Global daily and overnight ETF lanes: read-only archive-as-of 09:10 IST, separate availability gates (>=4 known daily factors / >=1 observed overnight proxy); short coverage may prevent an assessment, do not loosen gate. All source and outcome coverage logged. No new downloads, combined search, actual execution, P&L or live promotion. A favorable retrospective probability comparison is not sufficient for trading; separately validate first-passage execution and prospective predictions. Actual level-approach/rejection-event predictors and adaptive exits remain open. Earlier dates already inspected; no untouched test claim.

**Completed cross-market replication command (reproducibility only):**

    .venv/bin/python -m unittest discover -s tests -p 'test_ema_cross_paths.py' -v
    .venv/bin/python -m unittest discover -s tests -p 'test_ema_level_paths.py' -v
    .venv/bin/python -m unittest discover -s tests -p 'test_cross_market_levels.py' -v
    nice -n 15 ionice -c 3 .venv/bin/python -m scripts.benchmark_cross_market_levels --days 365 --to-date 2026-11-27

Owner clarified that pattern discovery must not use BANKNIFTY alone. The completed five-year index-only audit remains the reference, not the final model. Use original receipt-backed peer equity index histories (all existing peers except India VIX, which is volatility context) and stocks that are documented BANKNIFTY members on each study date. No new provider or history downloads. Use a bounded 365-day window because the prior contextual study established shorter support; report actual supported dates/coverage instead of pretending every source has five years. For each instrument, match full observed common current and preceding weekday prefixes against BANKNIFTY. Respect the existing reviewed dated cash-session policy; when a stock has a 360-minute regular session, both comparison sources use that same current/prior scheduled length for that lane, without synthesizing candles. Other lanes use 375. Reject missing/unverified prior weekday and incomplete prefix; membership unavailable is an exclusion, not assumed current membership. Apply identical EMA9/21 and frozen 20-level definitions independently to each instrument's own crossovers. Report separate directional level counts, conditional touch/break/failure rates, distance and extension in bps, first rejection and failed-break adverse excursion and duration/reclaim/censor, matched dates and source evidence, and the latest chronological evaluation-date subset. Output compact per-lane summaries, not millions of duplicate per-path CSV rows; original detailed BANKNIFTY journal retained. This is pattern replication, NOT synchronized lead/lag, transfer learning, incremental forecasting or executable profit. Compare common dates per lane; different instruments produce different event clocks, and correlated/overlapping markets cannot be pooled as independent samples. Next separate experiment must compare causally synchronized context at BANKNIFTY event times against the same index-only event labels, with options/global lanes subject to their actual shorter archive/receipt clocks and missing data. Do not infer a weight from current index weights or tune to observed failure rates. No trade routing or deployment.

**Completed level breakout and failure path audit command (reproducibility only):**

    .venv/bin/python -m unittest discover -s tests -p 'test_ema_level_paths.py' -v
    nice -n 15 ionice -c 3 .venv/bin/python -m scripts.benchmark_ema_levels --days 1825 --to-date 2026-11-27

Reuse the exact original EMA 9/21 path clock and verified historical receipts, one-minute candles, preceding complete weekday seed and contiguous current prefix. Freeze previous open/high/low/close, standard CPR bottom/pivot/top, R1/R2/S1/S2, today's open/running high/running low/developing CPR and first 15-minute high/low/close (only after completion) at each fresh cross; today's current close is the signal price, not a separate ahead level. Do not use final current-day OHLC or moving target levels. Reserve one row per cross/level (20 levels; coincident levels remain separate named comparisons, not independent events). Only a level strictly ahead in the cross direction is an opportunity. Record no touch, first touch state, first confirmed strict close beyond, subsequent strict near-side close (failed breakout) before/on opposite cross, or unresolved incomplete leg. Equality is neither a break nor failure. Distinguish initial touch rejection from later break; follow the first strict near-side close after touch and before a confirmed break independently, even if a later breakout succeeds. Also report rejections with no confirmed breakout in the observed leg as a descriptive subset. Report all observed counts plus completed-leg conditional rates (touch/ahead, break/ahead, break/touch, failure/break), separately for bullish and bearish, all dates and chronological partitions. Do not hide unfinished legs or conflate already-beyond levels with successful breaches. Track time to touch/break, confirmed breakout extension, time from break to failure, after-failure adverse move in points and bps relative to level and failure close, time to adverse extreme, close changes at 1/5/10/15/30/60 minutes before/at reclaim, and time to strict close reclaim of the frozen level or censor at gap/session end; follow-up can extend beyond opposite EMA cross. Missing/unfinished durations are censored, not zero; report reclaimed-only times and observed lower bounds separately. Extrema after the completed confirmation/failure exclude the earlier portion of its candle; subsequent OHLC intrabar order remains unknown. The audit is descriptive, not a fitted ML model or trade simulator. Report all groups; no new data, options fills, hindsight target optimization or trading promotion. Review this before first-passage model work.

**Completed EMA crossover-to-opposite-cross path audit command (reproducibility only):**

    .venv/bin/python -m unittest discover -s tests -p 'test_ema_cross_paths.py' -v
    nice -n 15 ionice -c 3 .venv/bin/python -m scripts.benchmark_ema_paths --days 1825 --to-date 2026-11-27

The owner wants to see how far BANKNIFTY rises after a fresh bullish EMA 9/21 crossover, or falls after a bearish crossover, and how much it retraces before the next opposite crossover. This is a variable-horizon descriptive study, not another fixed five-minute classification grid. Use one-minute completed closes, previous complete weekday EMA seed, strict opposite nonzero spread signs (equality touches do not duplicate same-direction crosses), prior OHLC/CPR zone and current running levels. Use subsequent OHLC bars through the opposite signal candle inclusive to measure favorable and adverse price excursions (MFE/MAE), minutes to the extreme, total duration, signed close-to-close move, points given back and capture/giveback fraction. The intrabar exact time/order and future peak are not known at decision time. First nonzero sign after an exactly equal prior EMA seed establishes state rather than inventing a cross. No overnight holding: censor last open path at regular session end or first missing bar, do not treat its truncated extreme as a complete outcome. Reject unverifiable preceding weekdays, including unverified holidays; this is not a complete calendar. Report bullish/bearish and prior CPR zone distributions, point and basis-point magnitudes, percentiles, and separate 60/20/20 chronological summaries; report all paths and coverage including exclusions. Separately model a one-minute delayed entry and opposite-cross exit at original index opens, cancel if the reverse signal is already known by entry, and report missing references and an illustrative 5bps roundtrip proxy. Neither peak-to-peak hindsight nor index open proxy is an executable options fill, sequential account P&L or a qualified predictor. Save JSON and per-path CSV. No new data downloads, training, threshold tuning or live orders. Review these observed path distributions before designing the next causal ML exit/first-passage hypothesis.

**Completed EMA/CPR context command (reproducibility only; not qualified):**

    .venv/bin/python -m unittest discover -s tests -p 'test_direction_gate.py' -v
    nice -n 15 ionice -c 3 .venv/bin/python -m scripts.benchmark_direction_gate --ema-cpr --days 1825 --to-date 2026-11-27

The owner observed that BANKNIFTY breakouts and reversals often occur around EMA 9/21, previous-session OHLC/CPR and today's ranges. Test this observation as a new information hypothesis, not an assumed profitable rule. Use the existing 1m decision clock (EMA 9/21 of completed one-minute closes; a different chart timeframe would be a separate experiment), seed both EMAs with the immediately preceding complete weekday, and reject unverifiable prior weekdays and missing current prefixes. The standard daily CPR uses prior H/L/C; today's developing high/low and provisional CPR use only completed bars; opening range is first 15 completed minutes. Include EMA separation/cross direction/age, prior open/close/pivot/CPR width/R1/S1, opening gap, running high/low/range, provisional CPR, and distance, crossing, same-side touch/rejection and immediate failed-breakout features at prior high/low, CPR boundaries, and opening-range boundaries. Add event/EMA alignment features. Compare fixed regularized three-class logistic with and without these features on identical context-qualified rows and chronological reservations. Report simple EMA-cross/CPR and unambiguous level-event rule comparators, calibration, called coverage, signed index proxy after assumed cost and paired day-block losses. Add a conditional sign Brier diagnostic on actual material moves (scoring only, never use future nonflat labels to choose calls) so improved FLAT classification alone cannot qualify the new feature set. Require paired improvement over matched core for both multiclass and conditional material-direction Brier in addition to prior screening gates. Report all predefined event groups, which may overlap. No new download, changed confidence threshold, additional model grid, actual option P&L or live promotion. Earlier inspected dates remain exploratory. Run after pulling the new code and report even if negative.

**Completed direction qualification command (reproducibility only; do not repeat or tune the failed test):**

    .venv/bin/python -m unittest discover -s tests -p 'test_direction_gate.py' -v
    nice -n 15 ionice -c 3 .venv/bin/python -m scripts.benchmark_direction_gate --days 1825 --to-date 2026-11-27

This is a single fixed historical screen, not another model/horizon grid. Reuse the original five-year BANKNIFTY receipts and chronological 60/20/20 reservations. The hypothesis is that forecasting an economically meaningful move with explicit flat/abstain and early-session coverage is more useful than predicting every positive close. Earliest decision after 16 complete one-minute candles (09:31 IST); fixed five-minute holding interval after one full minute delay; delayed open-to-open return >+5 bps UP, <-5 bps DOWN, otherwise FLAT. Five bps is a material-move research threshold, not a verified options break-even. Fixed compact completed-bar features (returns, recent RMS volatility/range, body and clock), regularized three-class logistic, every fifth decision for nonoverlapping fit and every eligible minute for retrospective evaluation. Training-only unconditional and 30-minute clock priors, validation-only temperature calibration for each, fixed 60% directional probability gate reusing existing constituent_alpha protocol; simple 5m momentum and no-trade comparators. Report missing input/outcome counts, raw and calibrated multiclass Brier/log loss/reliability, class accuracy, called coverage and day-weighted material hit/opposite/flat rates, signed return less an illustrative 5bps index roundtrip proxy. Compare on exact paired observations with descriptive five-session block intervals. Overlapping opportunities are not independent trades or account P&L. Retrospective screen requires both paired Brier intervals strictly favor model over both calibrated priors, >=100 directional calls over >=30 sessions, both directions represented and positive lower interval for net index proxy per eligible opportunity. These are proposed fixed screening requirements, not a guaranteed trading edge or a replacement for prospective qualification. No options P&L, new downloads, orders, position sizing, live model or promotion. If result is negative, explicitly stop this hypothesis; inspect existing report evidence and consider a distinct causal feature/market-regime hypothesis using available recorded data, without retuning this historical test. Do not force signals or claim an accuracy target in advance.

**Deferred option-response protocol (preserved; do not run as current priority):**

    .venv/bin/python -m unittest discover -s tests -p 'test_option_response_benchmark.py' -v
    nice -n 15 ionice -c 3 .venv/bin/python -m scripts.benchmark_option_response --days 365 --to-date 2026-11-27

The index-only and domestic context directional/OHLC benchmarks are completed with negative results. Do not keep changing underlying model families or fit a combined model after failed ablations. After the direction gate is met, this is Phase 3: this exploratory fixed benchmark directly forecasts observed future premium response, not a new strategy grid. Reuse the original rolling monthly family (ATM +/-3 receipt offsets), observed BANKNIFTY price history and same-strike positive-volume bars. Every aligned five minutes after 60 completed minutes, choose at most three closest observed strikes per CE/PE using only signal-time data, premium >=5 and within 2% of spot. Decision after completed bar, one whole minute delay, entry/exit reference opens five minutes apart; no cross-session outcomes. Score terminal premium and delayed gross change (both normalized by known signal premium), and probability of positive gross change. Fixed option-only and option-plus-index ridge/logistic on identical scored candidates, no-change and fixed training-only side/moneyness/clock historical median/prior comparators. Validation-only sigmoid, paired observed-day bootstrap, no test-based tuning. Chronologically reserve all observed index dates 60/20/20 before option availability filtering; at least 40/15/15 scored sessions. Preserve missing entry/exit counts and unresolved evaluation candidates. Conditional observed bars are not broker fills or exact contract IDs. No fees, net P&L, ranking, actual entry recommendation or IV outcome yet. Do not interpret positive gross-change probability as profit. First-hour support, explicit flat/first-passage, actual peak RAM and prospective acceptance remain open. No new downloads, paid data, orders or deployment.

### End-to-end option decision research roadmap

**Research objective:** compare policies that map the current causal information set and position state to action. A research objective is expected net INR P&L (after spread, market impact/slippage, commissions, exchange fees and taxes), penalized for downside/tail risk, subject to cash/margin, whole-lot and loss limits. Use no-trade as a real zero-return comparator. The exact risk penalty, funding and loss budget must be declared before the experiment, not chosen from the final test. Do not use forecast accuracy as a substitute for net utility; model-based expected profit is not a realized fill.

| Phase | Deliverable | Current status and next acceptance gate |
| --- | --- | --- |
| 0. Data | Shared source-verified clock-aligned histories, provenance and maintenance | Substantial collection exists; re-audit coverage and material gaps, particularly exact contract, dates, member IDs and available-at clock. Avoid optional provider expansion. |
| 1. Core forecasts (P0) | Rolling next-candle OHLC/direction/uncertainty from five-year BANKNIFTY minute data, starting with 5m then 1/10/15/30/60m | Existing 5m OHLC code extended to explicit 1,827-day index-only mode; scoped tests and a 1,825-day ridge/logistic run passed execution but not predictive acceptance; contextual and sequence studies remain 400 days. Reuse previous code and compare against no-change/adaptive/training-prior baselines. Freeze chronology and evaluate by session. |
| 2. Context (P1) | Incremental lift from bank returns/volume, Indian peers, global data and derivatives | Existing constituent, peer, global and option features; shorter histories must not shrink core training. Matched ablations and true calibration; retain fallback when unavailable. |
| 3. Option response (P1) | Distribution of future premium and IV/Greek response conditional on underlying forecast, time to expiry, strike, OI, IV, volume and liquidity | BSM scenario repricing, rolling option path analogs, empirical response research and IV stress exist. Need trained/tested premium/IV forecasts and uncertainty on actual supported contracts/paths, benchmark vs pricing-only/last premium, and distinguish rolling historical families from exact contract IDs. |
| 4. Contract and entry (P1) | For each source-qualified exact contract, expected net P&L, loss distribution, chance of net gain, cost and funding. Choose strike, expiry, CE/PE, whole lots, entry time/price or no-trade | Existing chain/depth scanners, Greeks, fees, funding, predictive option and paper selectors. Need integrate frozen calibrated forecasts rather than optimistic scenario assumptions or EMA-only rules; evaluate ranked selection against affordable simple and cash baselines on matched dates. |
| 5. Position and exits (P1) | Reassess as new completed bars/quotes arrive; hold, exit, or safe defined-risk adjustment; target, loss, reversal, time/expiry and liquidity guardrails | Fixed, trailing, target/stop, reversal, adaptive and forecast-adaptive paper exits already coded. Need validated forecast-driven policy including entry and exit, not only exit; account for censoring and pending fills. No unrestricted adjusting/averaging down. |
| 6. Execution (P1) | Realistic net P&L simulation using contemporaneous quote sides, original depth, explicit delay, actual lot/expiry, fees, funding and conservative incomplete-fill rules | Existing replay, fee and stress engines; historical minute proxies lack bid/ask, true fills and broker acknowledgments. Measure fresh receipt-to-decision and receipt-to-modeled-fill timing, calibrate adverse scenarios, reconcile real tariff/margin evidence; never claim queue priority or exchange fills. |
| 7. Prospective validation (P1) | Frozen model and policy, live shadow forecasts and paper decisions, reconciled labels and risk-adjusted net results on strictly later sessions | Candidate registry, prospective ledger, paper engine and opt-in research retraining exist. Need confirm enough actual recorded sessions, live timing/coverage, calibration, full-account and separate-lane results, operational stability and independent validation. |
| 8. Adaptive learning (P2) | Controlled retraining from recorded outcomes, possibly contextual bandit/offline RL after simpler baselines qualify | Earlier supervised and tabular Q research exists; no production RL validated. Keep research candidate versions immutable, retrain offline, require new independent evidence, and never automatically promote or send orders. |

**Decision contract (target UI/output, not current validated inference):** at time t report decision/source timestamps, forecast horizons and distribution, source/model version and freshness; candidate exact expiry/strike/side/ID and quote bid/ask, lot/units, premium and available quantity, expected net INR and downside, probability of net profit and uncertainty (only if calibrated), entry conditions/price cap, capital/risk budget, hold/exit/timeout/invalidation conditions, and a reasoned ENTER/HOLD/EXIT/ABSTAIN state. Keep position context and pending-order assumptions separate from predictions. Long options first; defined-risk verticals only when both legs, margin and execution are supported. Uncovered short exposure is not a default. Make clear whether an output is theoretical, modeled replay, paper, or an actual user-entered execution record.

**Evidence tiers:** (1) observed index/equity minute forecasts; (2) observed rolling option OHLC response with explicitly assumed delay/cost; (3) exact contract and contemporaneous recorded quote/depth conditional execution; (4) prospective frozen shadow/paper comparison and independently reconciled records. Do not promote an earlier tier as a later one. Avoid using future underlying/option prices, exact expiry hindsight, stale quotes, or available-at-unknown context for entries. Prevent cross-session or cross-expiry leakage. Distinguish directional win rate from probability of positive net INR. A modeled stop is not a guaranteed maximum loss.

### Implemented capability inventory

This is a source inventory at the consolidation branch, not a statement that every implementation has been fully run against the current local market library. Use the named existing files rather than create parallel modules.

| Component | Existing implementation and evidence level | Outstanding integration or verification |
| --- | --- | --- |
| Original data intake, calendar and coverage | Dhan workspace, checkpoint, shared_market_data, market_library, market_inventory, session_coverage, data_maintenance, options_history_sync, nse_session_policy, intraday_parquet/columnar_cache; optional Zerodha fallback. Local receipts and gap audits exist. | Final exact current local five-year scope/quality audit, holidays/special sessions, provider budget persistence, actual feed/storage health. |
| Live options & market depth | full_option_feed, option_chain_live, auto_option_chain, auto_option_depth, wide_option_depth, market_depth, recorder_storage; original quote/OI and book capture with age and activity gates. | Actual subscription coverage, quote continuity, pressure/loss and storage limits. Historical candle data cannot reconstruct depth. |
| Underlying forecasting | banknifty_candle_forecast, banknifty_forecast_features, banknifty_sequence_data/models/forecast; candle_pattern_research, cross_index_research, historical_alpha, fitted_alpha; ridge/logistic/HGB, patterns/random forest, CNN/GRU/Transformer. | Long-history and multi-horizon extension; existing models not a fully trained five-year predictor. Verify actual saved forecast metrics; do not repeat previously inspected holdout. |
| Bank/context/volatility | banknifty_constituents, banknifty_membership_fallback, constituent_prospective/alpha/calibration/derivatives, context_alpha/cohort/events/feeds, market_context, global_market_archive, alpaca_overnight, volatility_evidence, market_patterns. | Dated membership/weights, supported peer/option/global spans, matched feature lift, forward-only context and probability validation. |
| Option valuation/Greeks | advanced_options, option_market, option_quotes, recorded_chain_model_quotes, conditional gamma UI and IV analysis. BSM scenario repricing with chain inputs and explicit units; no inherent directional or profitability forecast. | Empirical option premium and IV response forecast, realistic conditional distributions and execution-adjusted calibration. |
| Historical forecast-to-option | predictive_option_research (5/10/15/30/60m, long CE/PE and debit verticals), forecast_depth_research, expired_options_backtest, cpr_* utilities, banknifty_math_target/sector_momentum/target_capped_ml. | Reuse existing delayed-open and exact-book research, connect validated long-history forecasts with matched option outcomes; confirm net edge after realistic costs. |
| Selection and sizing | auto_paper_selection, spread_scanner, option_spread_studio, liquidity_spreads, zerodha_basket_margin. Source-qualified exact contracts, whole lots, funding, scenario and stress screens. | Calibrated net utility rather than favorable hypothetical scenario ranking; actual current lot/expiry and fee/margin verification; no unverified trades. |
| Entry/exit and paper accounts | auto_paper_engine, auto_paper_selection, dynamic_exit_policy, dynamic_strategy_research, paper_execution, paper_forecast, manual_options_workflow, manual_trade_journal. Separate virtual directional/spread lanes. Existing adaptive/forecast-adaptive exit and adverse trigger handling. | Validated forecast-driven entry, sequential position management, unseen-session whole-account P&L, reconciliation of unresolved exits. |
| Spread and execution feasibility | spread_batch/core, spread_speed, spread_execution_gate, spread_readiness, depth_replay, execution_realism/stress, scalping_validation, year_scalping; zerodha_execution_costs and existing fee functions. | Empirical viability, timing and legging; simulated depth fills not exchange fills; fees and margin depend on current verified profile. |
| Candidate lifecycle | alpha_model_registry, alpha_retraining, constituent_prospective, paper_forecast, frozen_study; immutable logistic candidates, calibration, monitored later sessions, opt-in five-new-session research retraining. | Validate actual receipt support, drift, frozen candidate promotion gates and connect new multi-horizon forecasts without assuming schema compatibility. |
| Workstation | TradingCockpit, AdvancedOptionsAnalytics, OptionChainLive, PredictiveOptionResearch, ConstituentAlphaResearch, HistoricalAlphaResearch, AlphaCandidateRegistry, AutomaticPaperPanel, DynamicStrategyResearch, LiquiditySpreadsWorkspace, SpreadOpportunityScanner, MultiLegSpreadStudio, PaperTradingWorkspace, MarketLibraryPanel, DataManager, ModelLaboratory and ResultsStudio. | Verify current user-facing flows against actual API/data; consolidate within existing UI instead of duplicating screens; mark unsupported/stale predictions clearly. |

### Experiment and evidence register

Use this ledger to avoid repeating research or confusing code existence with demonstrated success. **Local results are not committed;** named report paths refer to the operator's checkout. Entries with numbers from earlier run summaries are explicitly prior-reported, not newly independently reproduced in this documentation edit. Reopen original local JSON/CSV and verify source hashes before using exact values for a publication, model selection or promotion. If no saved outcome was available to this review, write "outcome not reverified" rather than invent results. The initial dated full register and prior protocols are recoverable in the archive below.

| Study / period | What has been tried / measured | Decision and remaining evidence |
| --- | --- | --- |
| Legacy NIFTY multi-factor / momentum | Original notebooks and static-universe results; factor, benchmark-risk, robustness, mathematical model and synthetic acceptance routes developed. | Legacy optimized numbers not independently reproduced; retain as research evidence only. TRI, PIT membership, corporate actions and honest out-of-sample replication remain. |
| Saved model audit, reported Nov 26 | Operator reported 35/35 models executed using saved inputs; BANKNIFTY minute source and 1,320 CE / 1,320 PE contracts reported. | Code/data execution check, not predictive accuracy or profitable strategy. Rerun on current source scope and compare manifest. |
| EMA crossover, CPR/previous OHLC, RSI and directional backtests | Strategy Lab, expired-options replay, CPR rule baseline and no-stop/fixed-stop/trailing/reversal variants. Supervised logistic/random forest entry filtering and offline tabular Q hold/exit, with fixed training/validation/holdout and no-trade baseline. | Historical rolling-family delayed-open proxies, not broker fills. Earlier CPR report summaries negative or inconclusive; no validated policy. |
| CPR expanded experiments v4-v9 | Daily/regime scan, ranked entries, contextual Q, global/fixed five-bank/directed constituent inputs, morphology, first-passage, volatility regime, direct utility, forward reservation, long option vs debit vertical. | Existing examined evaluation dates exploratory. Never relax gates or re-label same holdout independently. |
| CPR execution-evidence screen, prior Nov 27 run summary | 90-session scope, 176/180 option pairs checked, zero expired gaps in that check, 711,063 positive-volume observations, 97.76% coverage. Reported conditional INR P&L across three compared lanes: 5m -3,634/-2,483/-3,539; 15m -5,712/-1,247/-2,936; 30m -4,535/-1,197/-3,707; 60m -6,875/-1,445/-3,374. All rejected. | Prior conversational run summary; reopen original cpr-next report for exact lane names, support, cost scope and values. No successful deployment candidate; more entry grids not the P0 task. |
| Candle morphology and first passage | Completed-candle patterns, empirical shrunk lookup, class prior, logistic and shallow random forest; 1/5/15/30-minute grids, future color vs direction kept separate. Prior 90-session summary reported 668 anchors, 4,658 option paths, 30 evaluation sessions, candle accuracy 38.85–44.07% and multiclass Brier 0.5669–0.6362. | Reopen original candle/sequence reports for method-specific results. Not evidence of a profitable option trade, and not the rolling five-year continuous predictor. |
| Historical constituent/peer and regime alpha | Point-in-time breadth/dispersion/relative-volume, index-only vs matched bank/peer models, logistic/boosting, GMM/HMM forward regime work, 5/10/15/30/60m and near-close forecasts. | Existing tools and source gates; earlier dates not untouched. Prior 90-session context summary indicated volatility Brier modestly improved with banks (5m .63878 to .63175; 15m .63280 to .61733; 30m .58526 to .57943); directional lead/lag inconclusive. Reopen original report and confirm definitions. |
| Mathematical option selection (banknifty-math, banknifty-sector, banknifty-capped) | Historical spot paths and BSM/IV scenarios, momentum vs reversal with peer confirmations, capped target utility, liquidity proxies, IV stress, optional logistic/ridge correction; flat INR 30/order in these specific v2 studies. | Implemented exploratory methods; exact run outcome not reverified here. No proof of +10% net target, true fills, exact historical lot or calibrated profit. Reuse reports, not new variants before P0. |
| Rolling five-minute OHLC v1 / v2 core extension | 60-minute causal features, last-close/range baseline, ridge/hist-gradient, bank/peer/options optional groups, 60/20/20 chronological sessions, stride-five fit, rolling assessment. | Five-year index-only ridge run completed; see exact console results below. Nonlinear comparison and original report/receipt reconciliation remain. |
| Multi-asset temporal sequence | CNN/GRU/Transformer, multiple lookbacks, OHLC/direction/tail/quantile losses and validation selection, 365-day run used 245 sessions, 29 missing evaluation membership dates. Prior validation-selected 15-minute-lookback Transformer motivated an optional convergence experiment (up to 20 epochs); 5m output target. | No claim of positive neural skill without original report. 120-minute common-support gate excludes early session; no repeated epoch tuning on known test. Core five-year forecast and early-session/multi-horizon support remain. |
| Overnight global pilot | 30-day 6,575 bars; 90-day 18,178 bars, SPY/QQQ/EWY most liquid. | Keep existing collectors; official Asian cash/GIFT and five-year foreign intraday not mandatory for core. |
| Pre-open global baseline, Nov 27 | 27 matched out-of-sample dates; combined worsened Brier and log loss for gap/15m/30m. Exact accuracy and result path in forecast section below. | No demonstrated incremental lift. Do not expand provider integrations merely because of this study. |
| Post-open selective baseline, Nov 27 | 124 sessions, 83 index /54 matched constituent out-of-sample dates; 9:20 30m 13/83 trades, 69.2% direction, +7.835 bps hypothetical net, 9:30 30m matched constituent 23 trades, 65.2%, +1.164 bps; primary 9:30 15m negative. | Small post-hoc candidates, not deployable; no more fixed-clock grids. Do not infer actual option profitability or sum overlapping lanes. |
| Live bid-ask capture / spreads, prior Nov 23 summary | 452 contracts screened; none cleared complete profitability/evidence gate. Example 63,200 PE gross ₹34.50/lot vs modeled charges ₹65.70, net -₹31.20; stressed -₹50.52. | Keep separate spread execution feasibility lane. Quoted spread alone is not captured profit; no passive fill evidence. |
| Dynamic entry/exit and replay, prior Nov 26 summary | 61,352 ticks, 4,501 checkpoints, 15,653 qualified observations, 62 scored trades (6 winners/56 losers) reported; directional fixed 1m -₹1,760.19, 2m -₹1,515.13, 10m -₹1,141.62, adaptive -₹1,212.56; spread variants -₹147.43 to -₹242.47. | Prior report summary; confirm exact cohorts and cost model before reuse. No demonstrated replay edge, much less actual broker profit. Preserve rejection/censoring accounting. |
| Original-depth forecast-to-option and adaptive paper | Predictive rolling CE/PE and debit spread research; forecast-depth original-book replay, calibrated logistic registry, forecast-adaptive exits, opt-in rolling research retraining. | Software exists, actual qualification/recorded prospective coverage and whole-account profitability not reverified. Earlier Nov 26 ledger was reported 0/60 because disabled; check current state before running a 60-session study. |

**Research completion:** use the live task checklist below. A checked experiment means it was attempted and its result is recorded, not that it succeeded. A checked implementation is not an empirical acceptance claim.

**Local evidence to recover before repeating an old experiment:** inspect results/ in the original checkout (not a clean clone): banknifty_data_preparation_b22fcb6817ba4c48ba76769b3c0bc107.json, candle_patterns_*.json, cpr_hybrid_*.json, trading_validation_*.json, previous OHLC/sequence JSON plus prediction CSV/checkpoints, global_open_baseline_2026-08-29_2026-11-27.json and intraday_selective_2026-06-01_2026-11-27.json. Retrieve the precise mathematical/sector/capped and execution screen report names from their CLI outputs rather than guess. Record hash, scope, split, selected method and metrics when an original report is actually reviewed.

## Five-year candle forecasting plan

The immediate work is an extension of the existing forecasting engine, not a new model family. Proposed initial long-history chronology: approximately first three years training, next year validation/calibration, last year retrospective evaluation (whole-session 60/20/20 or explicit equivalent dates). Freeze exact dates, eligible anchor definition and metrics before fitting; earlier examined periods remain exploratory, and reserve truly new sessions for independent confirmation. A five-year request is not five years of verified observations. Re-audit current source span, use session-blocked processing and preserve memory/IO limits; if full source audit reveals gaps, document the actual usable span rather than invent bars or block on unrelated data. Start with core index-only and then shorter matched context cohorts.

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

    bash run.sh banknifty-ohlc --index-only --days 1825 --to-date 2026-11-27 --ridge-only
    bash run.sh banknifty-ohlc --days 365 --wings 3
    bash run.sh banknifty-sequence --days 365 --wings 3 --epochs 6 --batch 96
    bash run.sh cross-index-research --sessions 90
    bash run.sh cross-index-research --list-sources
    bash run.sh candle-research --help

Actual files: workstation_api/banknifty_candle_forecast.py, banknifty_forecast_features.py, banknifty_sequence_data.py, banknifty_sequence_models.py, banknifty_sequence_forecast.py, historical_alpha.py; CLI scripts/run_banknifty_candle_forecast.py and scripts/run_banknifty_sequence_forecast.py. The OHLC runner now permits --days 1825 only with explicit --index-only (maximum 1,827); its normal contextual mode and the sequence runner retain the 400-day cap. All 10 OHLC regression tests passed locally and the five-year ridge-only run completed on 3cabad7. Nonlinear comparison and independent report/hash reconciliation remain. Do not increase context/sequence limits by assumption.

Existing OHLC v1: every eligible minute forecasts next five complete minutes from previous 60 contiguous minutes. Encode OHLC relative to prior close with coherent nonnegative wick structure; index, bank, peer and option feature groups; optional context not fabricated. Whole-session 60/20/20 split; training stride five, assessment each eligible minute, day weighting. Last-close/range baselines, ridge, histogram gradient and direction models; training-only support/normalization, validation-only model selection, later metrics and CSV predictions. No global inputs in v1. Existing source loader bounded; inspect actual data volume before extending.

Optional sequence research: PyTorch from requirements-sequence.txt (not required by live workstation); CPU default or explicit supported CUDA. Compact normalized per-session OHLCV windows with masks/identity embeddings; CNN, GRU, Transformer candidates with 15/30/60/120-minute lookbacks, default six configurations, common 120-minute support excludes early morning before 11:15 IST. Five-minute OHLC, direction and tail/quantile outputs; validation early stopping, held-out comparison against adaptive and fixed tree baselines. Existing 365-day study had 245 sessions, 29 evaluation membership gaps. Convergence mode uses a longer validation-controlled schedule, not new information; no need to optimize epochs until core long-history baseline exists. Review old JSON and CSV evidence before asserting a neural gain.

### Five-year rolling index-only ridge baseline (November 27, 2026)

Operator console at commit 3cabad7b68c1d4eeb79ffc6d95147442dfaae4ec: 10 tests passed (0.274 s); requested 1,825 calendar days, end exclusive 2026-11-27. Observed span 2021-11-29 to 2026-11-26, 1,231 observed weekday sessions; chronological reservations 738/246/247 train/validation/evaluation, 44,433 nonoverlapping training windows, 76,195 validation rows over 245 eligible sessions, 76,817 evaluation rows over 247 eligible sessions. 343 retained features, core matrix 510,912,220 bytes (not total peak RAM); optional banks/peers/options deliberately disabled, not missing-data acquisition failures. Sixty completed input minutes; rolling next-five-minute target. Earlier observed dates are not a fresh prospective holdout.

| Day-weighted evaluation metric | Training-only last-close/typical-range baseline | Ridge OHLC / logistic direction |
| --- | ---: | ---: |
| Open MAE (points) | 2.1033 | 1.9859 |
| High MAE (points) | 22.3027 | 20.6596 |
| Low MAE (points) | 22.0657 | 20.5690 |
| Close MAE (points) | 31.1306 | 31.3945 |
| Full OHLC mean MAE (%) | 0.0341674 | 0.0328256 |
| Range MAE (points) | 35.8814 | 26.6524 |
| Balanced OHLC close-direction accuracy | 50.0000% | 50.8987% |
| Direction probability Brier (training-rate comparator) | 0.2500454 | 0.2518315 |

Validation OHLC skill +2.9781%, close skill -1.0692%; evaluation OHLC skill +3.9272%, close skill -0.8428% (relative MAE, not accuracy). Logistic Brier worse than training-rate comparator in both partitions. Nominal 80% validation-residual interval covers 75.7710% of evaluation outcomes, mean width 87.5926 points. Direction accuracy 50.9679% refers to OHLC point forecast sign, not classifier accuracy. Report state: no_confirmed_ohlc_improvement. Interpretation: improved conditional range estimates but no demonstrated close/direction probability advantage or option P&L. Do not deploy.

Local files: results/banknifty_ohlc_forecast_2d69dcd19ca14b0dbf21c960c1c943d5.json and results/banknifty_ohlc_forecast_2d69dcd19ca14b0dbf21c960c1c943d5_predictions.csv. Console establishes completion and printed results; full original reports, source digests, skipped-session details and peak resource usage not independently inspected. The planned default comparison completed on 7f1944f; see the next entry. No new tuned grid.

### Five-year rolling nonlinear comparison (November 27, 2026)

Operator console at 7f1944fbbb77cea7d5a4515b4c9e38edf4595e96: 12/12 Model Laboratory tests passed, including the canonical documentation route (0.743s). The same five-year index-only study ran both ridge and histogram gradient (44,433 fit windows, 343 retained features, 76,195 validation rows, 76,817 evaluation rows over 247 sessions). Validation selected histogram gradient by OHLC mean relative MAE (0.02960558% vs ridge 0.02967848%). Evaluation is retrospective, not an untouched independent test following the earlier ridge-only run.

| Day-weighted evaluation metric | Last-close / typical-range or training class prior | Gradient OHLC / classifier |
| --- | ---: | ---: |
| Open MAE (points) | 2.1033 | 2.0639 |
| High MAE (points) | 22.3027 | 20.8120 |
| Low MAE (points) | 22.0657 | 20.6669 |
| Close MAE (points) | 31.1306 | 31.1784 |
| Mean OHLC relative MAE (%) | 0.0341674 | 0.0328769 |
| Range MAE (points) | 35.8814 | 28.6771 |
| Balanced OHLC close-direction accuracy | 50.0000% | 50.9463% |
| Classifier Brier | 0.2500454 | 0.2506312 |

Validation OHLC skill +3.2164%, close skill +0.0159%; evaluation OHLC skill +3.7768%, close skill -0.1549%. Nominal 80% interval covers 75.6799% (mean width 86.6637 points). Point-forecast direction accuracy 51.0434% is not classifier accuracy. Both five-minute models improve high/low estimates against the fixed typical-range comparator; neither beats the naive close forecast or constant prior probability on evaluation. No evidence of a tradable signal; need stronger volatility-adaptive comparator and horizon-specific tests. Do not infer option P&L. State no_confirmed_ohlc_improvement.

Local reports: results/banknifty_ohlc_forecast_914a2ab5309e419195d0165b4a141f52.json and results/banknifty_ohlc_forecast_914a2ab5309e419195d0165b4a141f52_predictions.csv. Console results are recorded; exact file hashes and peak process memory have not been independently inspected.

### Multi-horizon core forecast extension (all six horizons attempted)

The same core runner supports --horizon 1, 5, 10, 15, 30 or 60 for explicit index-only mode. Five-minute default and contextual/sequence clocks remain unchanged. Forecast targets are next complete horizon wholly inside one session, never future bars in features; 60 completed input minutes, horizon-sized nonoverlapping training stride and every eligible minute evaluated. Added training-only volatility-adaptive range baseline, paired observed-session loss intervals, classifier accuracy and probability reliability/log-loss diagnostics. Prior fixed-baseline skill state remains descriptive; adaptive comparisons and Brier differences must also be assessed before accepting a predictor. No probability calibration, first-passage or flat class yet. Local 14/14 regression tests passed and both full software CI workflows succeeded at d85dc92; all six empirical horizon runs completed. This does not certify forecasting skill.

### Five-year rolling 15-minute comparison (November 27, 2026)

Operator console at d85dc9265ce380b01e7b26b13b77b9649cf0652c: 14/14 regression tests passed (0.345s). Same 1,231 observed sessions and 738/246/247 chronological reservations; 14,803 nonoverlapping training windows, 73,745 validation rows across 245 eligible sessions, 74,347 evaluation predictions across 247 sessions, 343 features, core matrix 494,407,060 bytes (not peak process RAM). Validation selected histogram gradient (0.04999931% OHLC relative MAE vs ridge 0.05075053%). No fresh prospective holdout.

| Day-weighted evaluation metric | Fixed typical-range baseline | Volatility-adaptive baseline | Gradient boosting |
| --- | ---: | ---: | ---: |
| Open MAE (points) | 2.1166 | 2.1166 | 2.0785 |
| High MAE (points) | 38.7529 | 34.8626 | 35.9938 |
| Low MAE (points) | 38.3434 | 35.1010 | 36.0128 |
| Close MAE (points) | 54.5711 | 54.5711 | 54.7818 |
| Mean OHLC relative MAE (%) | 0.05894027 | 0.05574087 | 0.05672706 |
| Range MAE (points) | 61.0771 | 36.1474 | 47.7761 |
| Balanced point-forecast close direction | 50% | 50% | 50.3890% |

Evaluation Brier 0.25127324 vs training class prior 0.25014718; paired five-session block mean difference +0.00112607, descriptive 95% interval [+0.00027311,+0.00211360]. Classifier accuracy 50.9193%; log loss 0.69575311 vs prior 0.69344155. Reliability bin [0.6,0.7): 2,874 rows, 226 sessions, weighted probability 0.622554 vs observed up rate 0.522269. Model-minus-adaptive paired OHLC relative MAE difference +0.00098619 percentage points (interval [+0.00075175,+0.00126598]); mean high/low absolute error difference +1.02146 points (interval [+0.78406,+1.29123]); close MAE difference +0.21062 points (interval [+0.11424,+0.33148]). Nominal 80% residual interval covers 75.0938%, mean width 148.4581 points. The stronger simple comparator outperforms the selected nonlinear model; probability confidence is overstated in the 0.6-0.7 group. State no_confirmed_ohlc_improvement. Do not promote ML; preserve adaptive range as a comparator, not a proven option-premium or profitability model.

Local files: results/banknifty_ohlc_forecast_d4ccd040e8174731bbc95224bd875b4b.json and results/banknifty_ohlc_forecast_d4ccd040e8174731bbc95224bd875b4b_predictions.csv. Console verifies the run and printed metrics, not file hashes or complete local data provenance. The remaining fixed horizon comparisons completed; see below. No extra providers, new model grid, deployment or orders.

### Closed five-year six-horizon core benchmark (November 27, 2026)

Operator console at bac7f5365afb38875f6b3319fcb9ce69fd1e03b5 completes the five remaining horizons; 15m was run at d85dc92. All use 1,231 observed sessions from 2021-11-29 through 2026-11-26 and reserved 738/246/247 train/validation/evaluation sessions, 343 retained features, 60-minute inputs and horizon-sized stride. Each evaluation covers 247 sessions; anchors overlap across horizons and cannot be summed as independent observations. Validation selects ridge at 1m and histogram gradient at other horizons. All report no_confirmed_ohlc_improvement.

| Horizon | Fit rows | Evaluation rows | Balanced point direction (%) | Adaptive / ML range MAE (points) | Adaptive / ML full OHLC MAE (%) | Prior / ML Brier |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1m | 222217 | 77805 | 50.3791 | 9.6370 / 12.9316 | 0.01483390 / 0.01497574 | 0.24997678 / 0.25052160 |
| 5m | 44433 | 76817 | 50.9463 | 20.7420 / 28.6771 | 0.03226728 / 0.03287695 | 0.25004543 / 0.25063124 |
| 10m | 21864 | 75582 | 50.5727 | 29.4687 / 40.0783 | 0.04543357 / 0.04626624 | 0.25007803 / 0.25088573 |
| 15m | 14803 | 74347 | 50.3890 | 36.1474 / 47.7761 | 0.05574087 / 0.05672706 | 0.25014718 / 0.25127324 |
| 30m | 7050 | 70642 | 49.1143 | 52.2331 / 67.6382 | 0.07908755 / 0.08079633 | 0.25043134 / 0.25292654 |
| 60m | 3523 | 63232 | 50.1836 | 77.6322 / 92.8904 | 0.11316690 / 0.11605097 | 0.25041331 / 0.25385220 |

Selected ML has worse close MAE, full OHLC MAE, high/low MAE, range MAE and Brier than the corresponding stronger simple comparator at every horizon. The evaluation paired descriptive 95% five-session block intervals for model-minus-adaptive full OHLC loss and model-minus-prior Brier are entirely positive in all six cases; not multiplicity-adjusted or prospective evidence. Nominal 80% close intervals cover only 73.61-76.33% across horizons. Do not interpret weak directional point accuracy or raw confidence as contract profitability. The simple adaptive range and constant-prior models remain comparison references, not a deployed trading policy. Close this planned index-only experiment as completed/negative; no further index-only model grid. Context comparison next; meaningful movement/first-passage labels and early-session inference remain open.

Local report stems under results/ (each has .json and _predictions.csv):
- 1m: banknifty_ohlc_forecast_f23ba2a4ec8b41dda802d0d98c71500e
- 5m: banknifty_ohlc_forecast_b193dcbfc2914df9940f0408f00e819a
- 10m: banknifty_ohlc_forecast_98df3326ee0445ffb7f4e8e3c35d32d7
- 15m: banknifty_ohlc_forecast_d4ccd040e8174731bbc95224bd875b4b
- 30m: banknifty_ohlc_forecast_cc9eda4f5d0c418d9e1140226e9427d7
- 60m: banknifty_ohlc_forecast_1364d4f2c3764a2e8db66eb59e8db63d

Core matrix sizes 420,264,180 to 517,514,284 bytes; no peak RSS measurement. These are user-reported console results, not independently hashed local files. Next study uses existing contextual data with matched shorter cohorts rather than pretend five-year options/depth coverage.

### Matched domestic context ablation (completed, negative)

One explicit --matched-context mode in the existing OHLC runner, fixed 5m and 365 requested days. Independent banks, peers and options lanes; use source-specific supported dates and minimum gates declared in the current command above. Compare identical paired fitting, validation and evaluation rows, same model family and training-derived columns, constant prior and adaptive range. Validation-only sigmoid uses raw logit and fixed regularization; raw and calibrated scores reported, no guarantee of calibration or usefulness. Existing bank membership, peer, and rolling option feature gates retained; missing values remain explicit with training-only imputation. Exact receipt/expiry and global/depth features remain separate tasks. Save complete lane-specific dates, metrics, pairs and source provenance in banknifty_matched_context_*.json and a single corresponding prediction CSV (absent if no lane supports the experiment). All 16 local tests and both full software CI workflows passed at 7ab3125. Actual results below.

### Matched domestic context results (November 27, 2026)

Operator run on 7ab31254080598c0bea64ccafb4d8fd8e4ed39f6: 16/16 local tests passed (0.389 s); both GitHub CI workflows succeeded. Requested 365 days; 245 observed index sessions 2025-11-27 through 2026-11-26, 216 dated membership days, 14 original bank-stock sources, zero dated weight snapshots; all ten peer indices have 245 observed sessions. Options group available on 243 supported sessions; this is a group feature-availability gate, not 243 days of complete exact option chains or bid/ask, and supersedes the earlier 90-session *narrower-scope* audit only for this feature gate. Core feature matrix 104,539,540 bytes; peak RSS unmeasured.

| Lane | Supported sessions | Fit / validation / evaluation rows | Evaluation days | Index / context / adaptive OHLC relative MAE (%) | Prior / index / context raw Brier | Index / context calibrated Brier |
| --- | ---: | --- | ---: | --- | --- | --- |
| Banks | 216 | 8127 / 13313 / 13244 | 44 | 0.02664844 / 0.02786604 / 0.02609019 | 0.25002313 / 0.25289228 / 0.26750450 | 0.24971911 / 0.24971891 |
| Peers | 245 | 9261 / 15239 / 15239 | 49 | 0.03525742 / 0.03542020 / 0.03452721 | 0.24999520 / 0.25460449 / 0.25625485 | 0.25016523 / 0.25010883 |
| Options | 243 | 9134 / 15239 / 15239 | 49 | 0.03468216 / 0.03475842 / 0.03399143 | 0.24999793 / 0.25435461 / 0.25507269 | 0.25021686 / 0.25018453 |

All three context models have worse OHLC error than the adaptive comparator (positive paired block intervals). Banks improve range MAE against index ML by 1.79384 points (95% descriptive block interval -2.39852 to -1.25412), but are worse than adaptive by 1.88777 points; peers and options are worse than adaptive by 6.77543 and 6.66471 points. Calibrated context-minus-index Brier differences respectively -0.00000020, -0.00005640, -0.00003233; all paired descriptive 95% intervals include zero. Banks calibrated Brier beats the training prior by 0.00030422, but the matched index-only calibrated model achieves essentially the same value. Calibration reduces raw probability loss; this does not establish incremental signal or certify calibration on new sessions. None establishes a useful underlying-direction edge. Do not select a combined model, expand providers or repeat these tests without a new research hypothesis. Different lanes have different dates; cannot pool rows. Earlier examined dates remain exploratory.

Local files: results/banknifty_matched_context_622f6bfc383c4b34bd5c9a521571a57a.json and results/banknifty_matched_context_622f6bfc383c4b34bd5c9a521571a57a_predictions.csv. Console evidence only; original file hashes and full local source reconciliation remain unchecked.

### Direct option premium response (implementation retained; run deferred)

Deferred protocol and command above; scripts/benchmark_option_response.py reuses verified index and rolling option loaders and existing numerical models, not a new live engine. Conditional premium movement outcomes, option-only vs option-plus-index, no-change and training-only historical bucket baselines, complete evaluation candidate state accounting. Existing Greeks/scenario and historical option research are retained. No assumption that underlying forecasts are reliable, no exact contract, actual IV response target, order execution or strategy profitability claim. New tests and empirical run remain pending; direction qualification takes precedence.

### Direction qualification benchmark (completed; not qualified)

The project owner clarified that the goal includes actual manual trading, so directional qualification is a blocking prerequisite. Operator console at 8a3b138: all 3 tests passed (0.046s). Five-year span 2021-11-29 through 2026-11-26, 1,231 observed weekday sessions; chronological 738/246/247 session reservations, 50,650 nonoverlapping fit, 86,523 validation and 87,191 rolling evaluation rows. Observed date continuity is not a certified complete exchange-session calendar: incomplete/gap windows excluded, weekends excluded, no proof every expected trading day is present. No random date split; fixed fitted model rather than daily walk-forward retraining. The current model's features use only the immediately preceding 16 same-session completed bars, not overnight or previous-session state. Five-year training supplies examples across days, not a continuous multiday input sequence. Earlier OHLC features included prior-session and up to five earlier-day summaries, but that is not this compact direction-gate feature set.

| Evaluation method | Multiclass Brier | Balanced accuracy | Calls / call sessions | Day-weighted material hit | Mean net proxy bps per called opportunity |
| --- | ---: | ---: | --- | ---: | ---: |
| Raw model | 0.55540836 | 34.1062% | 13 / 5 | 51.1111% | -2.95768 |
| Calibrated model | 0.55650204 | 34.1062% | 38 / 17 | 40.2941% | -2.98103 |
| Calibrated training prior | 0.57668872 | 33.3333% | 0 / 0 | n/a | n/a |
| Calibrated clock prior | 0.57455988 | 33.3333% | 0 / 0 | n/a | n/a |
| 5m momentum | n/a | n/a | 37330 / 247 | 21.4699% | -5.01410 |

Calibrated model accuracy 58.0243% vs prior 57.8259%; largely flat-class classification, not 58% directional trade accuracy. Paired Brier differences against training prior -0.02018667 (95% descriptive block interval [-0.02630307,-0.01427880]) and clock prior -0.01805784 ([-0.02418730,-0.01236766]); this is multiclass probability improvement, not evidence of profitable direction. 16 UP and 22 DOWN calls; 38 total (0.0436% day-weighted coverage), opposite material hit 40.2941%, flat 19.4118%. Net index proxy per eligible opportunity -0.00263180 bps, interval [-0.00783141,+0.00114883]. Gate: Brier PASS, both directions PASS, support FAIL, positive proxy lower interval FAIL. State direction_not_qualified. Retain the failed protocol unchanged. Next distinct hypothesis to assess is whether causal prior-session and multi-day regime state adds direction value, with a matched short-history comparator, explicit exchange-session gaps and no overnight target leakage. The EMA/CPR level-event version completed on fa691f7 and did not qualify (next ledger entry); the crossover path audit is the current task. Wider multi-session regime features are not yet implemented. Do not claim a continuous multiday sequence or daily retraining exists. Do not tune thresholds on this already inspected test.

Local report results/banknifty_direction_gate_e4a7349a5b1d4c9c9f199ee400c35480.json and corresponding _predictions.csv. Console only; original report hashes not independently verified. No new source acquisition or production inference. Historical dates already examined remain exploratory. Even a retrospective pass requires frozen prospective shadow validation and separate actual option contract/cost/risk acceptance.

### Matched EMA 9/21 + prior OHLC/CPR + developing levels (November 27, 2026)

Operator console on fa691f731e9cad9c5943088a5765351cac69a659: 5/5 regression tests passed (0.107 s). Five-year source scope 1,231 observed sessions; 45,503 training windows, 81,896 validation and 81,543 evaluation rows across 231 supported evaluation sessions. 37,647 missing-context anchors across all partitions due to conservative prior-weekday/current-prefix gate; actual holiday/gap reasons need local reconciliation. Same delayed five-minute target, +/-5 bps deadband, 60% threshold, matched logistic family and validation-only temperature calibration.

| Evaluation | Matched intraday core | EMA/CPR context |
| --- | ---: | ---: |
| Calibrated multiclass Brier | 0.55278298 | 0.55097717 |
| Conditional nonflat sign Brier | 0.25209769 | 0.25362627 |
| Balanced three-class accuracy | 34.0611% | 33.9405% |
| Calls / call sessions | 35 / 15 | 63 / 14 |
| Day-weighted material hit rate | 46.1111% | 49.8557% |
| Mean net proxy bps per call | +0.66927 | -1.70041 |
| Mean net proxy bps per eligible opportunity | -0.00071613 | -0.00194064 |

Context-minus-core multiclass Brier -0.00180581 (descriptive 95% five-day block interval [-0.00414072,+0.00070416]); conditional sign Brier +0.00152859 ([+0.00093089,+0.00209141]) across 33,845 material-move rows. Context-minus-core proxy difference -0.00122451 bps (interval [-0.00885936,+0.00586930]). Fixed EMA cross aligned with CPR zone: 1,611 calls, 19.3481% material hit, -5.10997 bps mean proxy. Unambiguous level-event rule: 11,218 calls, 24.9853% material hit, -4.78952 bps mean proxy. Event groups: 3,681 fresh EMA crosses, 5,974 level breakouts, 5,744 level rejections, 1,683 immediate failed breakouts; overlapping groups, not independent trades. Model issued only 2, 11, 6 and 1 calls respectively in those groups. Do not select the 11-call breakout subset post hoc as a strategy. Gate: Brier against priors and both directions PASS; minimum call support, positive proxy lower interval, incremental multiclass Brier and conditional material direction Brier FAIL. State direction_not_qualified. No validated trading edge.

Local files results/banknifty_direction_ema_cpr_0eeb3dffed0444738ffd0b4a950f5ccb.json and corresponding _predictions.csv. Console evidence, original hashes not independently reconciled. The owner then requested whole crossover-to-opposite-cross movements, not fixed five-minute outcomes. Retain the negative result, prioritize descriptive path audit before further ML. No event-only fixed-horizon follow-up has been committed in this revision.

### EMA crossover path audit (completed; descriptive, not qualified)

Operator console on 89340045010002e41208a97fa38553db94693641: all 4 scoped tests passed (0.014s). Observed index scope 1,231 sessions, 2021-11-29 to 2026-11-26. Session states: 1,105 complete regular prefixes, 11 current gaps, one unavailable current prefix, 114 unavailable complete prior weekdays. Missing weekday is not proof of a missing trading session (official holidays not certified). Total 19,431 paths: 18,316 completed opposite-cross paths and 1,115 censored; 16,821 scored delayed index-open references, 1,389 reverse signal before/at entry, 106 unobserved references, 1,115 censored not scored. Latest historical evaluation: 3,922 paths, 3,691 complete, 231 censored, 3,391 scored delayed references, 257 canceled before/at entry and 43 unobserved references.

| Complete-path statistic | All five-year dates | Bullish five-year | Bearish five-year | Latest evaluation |
| --- | ---: | ---: | ---: | ---: |
| Complete paths | 18316 | 9132 | 9184 | 3691 |
| Median duration (min) | 13 | 13 | 13 | 14 |
| Median time to favorable extreme (min) | 4 | 4 | 4 | 5 |
| MFE p25 (points) | 9.10 | 9.00 | 9.20 | 11.575 |
| MFE median (points) | 30.5508 | 29.9750 | 31.1016 | 36.55 |
| MFE p75 (points) | 79.5131 | 78.2274 | 80.9367 | 94.30 |
| MFE p90 (points) | 163.40 | 162.0936 | 164.3850 | 189.85 |
| Median MAE (points) | 31.5976 | 31.60 | 31.55 | 35.40 |
| Median signed opposite-cross close move (points) | -21.20 | -21.20 | -21.20 | -24.00 |
| Median giveback (points) | 60.0484 | 59.30 | 60.9262 | 69.00 |
| Median delayed signed open move (points; scored subset) | -18.25 | -18.40 | -18.15 | -21.15 |
| Median net delayed index proxy (bps; scored subset) | -8.7605 | -8.7782 | -8.7524 | -8.6696 |
| Positive opposite-cross close move fraction | 24.7762% | 24.7043% | 24.8476% | 25.4403% |
| Positive delayed net proxy fraction (5bps assumed) | 17.9597% | 18.1829% | 17.7383% | 18.3722% |

Separate percentiles are not the history of a single typical position; no inference about order of favorable/adverse extremes within a minute. Evaluation CPR groups (completed count, median MFE points, positive fraction on delayed scored subset): bullish above (851,34.90,18.04%), bullish inside (197,48.45,21.67%), bullish below (786,35.575,17.93%), bearish above (836,36.10,16.38%), bearish inside (224,39.95,18.54%), bearish below (797,36.75,20.35%). Do not select a subgroup post hoc or infer net expected P&L from hit rates. Same inspected historical periods remain exploratory. Opposite-cross waiting has poor typical signed movement; favorable excursions can occur well before the reversal signal, but the signal-price MFE may include a move before an actual delayed entry. These observations motivate studying the causal order and entry-relative magnitude, not assuming capture of hindsight extrema or immediately trading a 4-minute exit. No account-level or option P&L, no trained predictor, no prospective qualification.

Local files: results/banknifty_ema_cross_paths_ebd96390c23e4edcbd537a7c04c377b2.json and results/banknifty_ema_cross_paths_ebd96390c23e4edcbd537a7c04c377b2_paths.csv. Console supports the above; original files and source hashes not independently inspected. Both CI workflows for 8934004 were still in progress at the documentation check.

**First-passage research design (completed; no qualification):** One event-centered first-passage benchmark, not another all-candle direction model. Reuse exact fresh-cross times, same verified contiguous prefixes and chronological reservations. Define a single material favorable barrier and adverse barrier in normalized bps, both fixed before fitting; proposed +10bps/-5bps on signed move from a delayed entry reference (illustrative research values, not verified option break-even or user-approved trading levels). Evaluate which barrier is observed first before the opposite crossover, with no fixed five-minute holding limit. Use completed-candle crossing observations or explicit ambiguous intrabar touch state; never grant a favorable fill when both barriers touch within one minute. Separate canceled, missing, unresolved and end-of-session outcomes; report denominators and coverage. No future extrema, outcome duration, future entry price or next crossover in signal-time model inputs. Compare fixed training-only historical event/clock priors against a small fixed learned classifier using available EMA/CPR distances, recent returns/volatility and prior/current market structure; fit/calibrate on earlier partitions only. The direct target is probability of a sufficiently large continuation before reversal/adverse move, conditional on actual entry and resolvable path; report competing/censored cases and avoid treating conditional probabilities as net-trade probabilities. If testing exits, compare same entry cohort, causal signals and explicit delay/cost, with no favorable selection on future path completion. Freeze protocol and reserve prospective sessions before promotion. Do not repeat the failed five-minute direction or raw crossover study. The fixed descriptive first-passage target and matched predictor are implemented in scripts/benchmark_ema_first_passage.py. Actual testing and qualification remain pending; no recommendation to place trades.

### EMA level breakout/failure path audit (completed; descriptive, not qualified)

Owner requested measuring whether bullish or bearish EMA paths cross CPR, previous OHLC and today's observed levels, how often they fail, and how far/long price then reverses. scripts/benchmark_ema_levels.py reuses scripts/benchmark_ema_paths.py crossover detection and source receipts. The protocol is specified in the current command. Reports banknifty_ema_level_paths_*.json and corresponding _levels.csv contain per-level denominators, directional counts, distributions, follow-up state, timestamp offsets and chronological groups. First-touch rejection, eventual breakout and failure after confirmed break are distinct; initial rejection follow-up is retained even if the level later breaks. A failure followed to reclaim is not a trade or prediction. New unit tests check bullish failure followed after opposite cross, bearish rejection/gap censor, frozen intraday levels, denominator integrity, and equality. Operator run on ebff6e4b6fc34b5c5092d8f82792ba44e3009785: all 5 tests passed (0.002s), 1,231 observed index sessions, identical session states to previous crossover-path run (1,105 complete, 11 current gaps, one unavailable prefix, 114 unavailable complete prior weekday). Exactly 19,431 crossovers and 388,620 named level rows (20/cross). Selected reporting rows below summarize the full console; not a post-hoc trading selection. Denominators are completed legs with a level ahead, then confirmed breaks, then recrosses before/on the opposite EMA signal.

| Evaluation direction / level | Completed ahead | Touch | Break | Failed | Break/ahead | Failure/break | Median break-to-failure min | Observed adverse points after failure |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Bull / previous high | 1420 | 126 | 111 | 91 | 7.82% | 81.98% | 2 | 33.00 |
| Bull / CPR top | 983 | 124 | 104 | 82 | 10.58% | 78.85% | 3 | 26.275 |
| Bull / today running high | 1833 | 331 | 306 | 241 | 16.69% | 78.76% | 2 | 22.65 |
| Bull / opening 15m high | 1286 | 196 | 183 | 141 | 14.23% | 77.05% | 3 | 20.20 |
| Bear / previous low | 1412 | 110 | 98 | 80 | 6.94% | 81.63% | 2.5 | 18.85 |
| Bear / CPR bottom | 1060 | 136 | 118 | 95 | 11.13% | 80.51% | 2 | 26.925 |
| Bear / today running low | 1856 | 327 | 289 | 227 | 15.57% | 78.55% | 3 | 27.85 |
| Bear / opening 15m low | 1295 | 180 | 155 | 130 | 11.97% | 83.87% | 3 | 26.80 |

Adverse point medians are across all observed confirmed-failure follow-ups including incomplete legs/censored follow-up (not the exact same denominator as the completed-leg failed counts). A strict close back through a level does not imply permanent failure; many reclaim. For bullish previous-high failures, 95 observed follow-ups, 77 reclaimed and 18 censored; median completed-only reclaim time 3 minutes and median observed adverse-extreme time 2 minutes. This demonstrates frequent whipsaws under the chosen leg definition, not statistically established cross-level causality, executable reversal or trade P&L. Do not choose a level based on these rates without adjusting for initial distance, duration, regime and dependence. All original results under results/banknifty_ema_level_paths_6d9ac81438c64b86b0b47f5d80eacf29.json and corresponding _levels.csv. Console evidence only; full files and hashes not independently reconciled. No new provider or model training.

### Cross-market EMA level replication (completed; descriptive)

The owner requires broader pattern discovery than BANKNIFTY. scripts/benchmark_cross_market_levels.py implements the current matched-date replication protocol using existing equity index and dated constituent data. The shared crossover/level routines accept an explicit scheduled regular comparison length, default unchanged at 375, so scheduled shorter cash closes are censored as session end rather than a missing bar. No artificial candles. Operator at befcb86 attempted the three cross-market tests: two passed, one errored before historical execution with KeyError initial_rejection_followup_state. The adapter must use the original level-row field initial_rejection_failure_followup_state. Corrected this field and added a regression covering both a reclaimed initial rejection and an unobserved rejection. The first attempt did not run. Operator reran at b0e731cc71ca3e7dfa668d6310d07d8cc4c66c7e: all 13 tests passed (4 EMA path, 5 EMA level, 4 cross-market) and the historical experiment completed. All 23 comparison lanes assessed; nine peer equity indices matched 228 sessions each (44 evaluation), 12 bank stocks matched 202 each and two 181 each (18 evaluation each). Dated membership unavailable/nonmember excludes 29 or 52 dates; 17 index/prior-prefix dates excluded in peer lanes. Sum of comparison instruments' own crossovers 82,283 (not independent, BANKNIFTY repeated baselines not counted in sum).

| Evaluation instrument, 44 common sessions | Bull previous-high break / failed | Median minutes to fail |
| --- | ---: | ---: |
| BANKNIFTY | 22 / 18 | 2 |
| NIFTY50 | 28 / 25 | 2 |
| FINNIFTY | 36 / 26 | 2 |
| MIDCPNIFTY | 29 / 24 | 2 |
| NIFTY100 | 29 / 24 | 2 |
| NIFTY500 | 26 / 21 | 3 |
| NIFTYIT | 6 / 6 | 2 |
| NIFTYNEXT50 | 22 / 19 | 3 |
| NIFTYPRIVATEBANK | 20 / 18 | 2 |
| NIFTYPSUBANK | 19 / 14 | 2.5 |

Other directional levels vary and some stock cells have very small denominators (HDFCBANK previous-low bearish break only one in its 18 evaluation sessions). High recross frequencies extend beyond BANKNIFTY in this descriptive protocol, but comparisons use each instrument's own event times. No predictive cross-market synchronization, transferability, causal relationship or executable profitability established. The complete local reports are results/banknifty_cross_market_levels_f1cbfe20f2d04e76a438b7a3d2a0b93b.json and corresponding _summary.csv. Console evidence only; actual files and hashes not independently reconciled.

### Synchronized first-passage crossover study (completed; not qualified)

The fixed first-passage protocol above now includes a five-year core lane and shorter separately matched banks, peers/VIX, rolling-options, pre-open daily and overnight lanes. The script uses original receipt loaders and causal feature/level definitions rather than new providers. The model predicts continuation of the observed EMA direction, not the reverse direction on a low probability. Unknown outcome states remain in evaluation journals; comparisons only score resolved labels, not actual net profit. New tests cover delayed entry, dual-touch ambiguity, censoring, causally synchronized states and matched evaluation including unresolved rows. Operator on 790f302c9691e0d48fe98d66ffbfb82894eb9334: all four scoped tests passed (0.046s); both full software CI workflows passed. Five-year 1,231 observed dates, 1,115 supported crossover sessions, 19,431 crossovers. Outcome counts: 5,129 favorable first, 9,798 adverse first, 2,766 reverse without barrier, 1,389 canceled, 197 session-end censored, 43 dual-touch ambiguous, 108 unobserved entry, 1 gap censor. 3,795 evaluation candidates, 3,453 resolved including 1,032 favorable. Calibrated core Brier 0.21259354 vs constant 0.21299586 and clock 0.21306348; both paired intervals include zero. Three >=60% calls, all unobserved entry, no scored call. No direction qualification.

| 365-day lane | Supported sessions / events | Resolved eval rows | Matched index calibrated Brier | Context calibrated Brier | Context minus index paired interval |
| --- | ---: | ---: | ---: | ---: | --- |
| Core | 228 / 3877 | 635 | 0.21837432 | n/a | n/a |
| Banks | 202 / 3347 | 583 | 0.19925286 | 0.19847199 | [-0.00360709,+0.00204109] |
| Peers/VIX | 228 / 3748 | 609 | 0.21821703 | 0.21776679 | [-0.00175808,+0.00090310] |
| Options | 227 / 3737 | 617 | 0.21629474 | 0.21633109 | [-0.00141507,+0.00150852] |
| Global daily | 228 / 3877 | 635 | 0.21837432 | 0.21799857 | [-0.00062837,-0.00011824] |
| Overnight | 52 / 809 | n/a | n/a | n/a | insufficient support |

The one-year daily-global lane improves over matched index-only but not over its calibrated constant prior (0.21780481). Banks and peers show small inconclusive improvements over matched core. All assessed one-year models gave zero qualifying calls, overnight failed minimum support. No new threshold tuning; no executable or prospective advantage. Reports results/banknifty_ema_first_passage_10334d7b51714b68a664bdf3f6abab17.json and results/banknifty_ema_first_passage_25147d5c205641b487abc674629b72b7.json with corresponding _events.csv. Console evidence only; full original reports/hashes not independently inspected.

### Custom unified market dynamics (V2, V3 and OptionDynamics historical experiments completed)

The owner requested learning patterns directly from the synchronized state rather than imposing technical entry triggers. The fixed MarketDynamics model, minute grid and CLI above reuse the earlier original source readers and existing PyTorch model module. Six horizons with explicit missing outcome masks; neural core/joint on identical rows and one latest-snapshot logistic reference. No strategy or trading recommendation. Tests cover signal-time invariance, prior/current levels, padding, train-only identity and auxiliary scaling, delayed labels and coherent excursions, masked multitask backward and a tiny training/journal run. Operator at 715fd80 reported 4 passed, 2 skipped because optional PyTorch was missing from .venv; training never began. The owner requested full timestamped source scope and CUDA. Full-history mode is implemented in scripts/benchmark_market_dynamics.py and scripts/market_dynamics_history.py; the current command above supersedes the initial restricted run. New tests cover chronological reservation, all-minute labels and gap recovery, completed multi-timeframe OHLC, aged prior observed OHLC, memmap grid and nonmember context, option receipt families and same-strike changes, streaming scaling and snapshot scoring, and full-mode neural training/journal. Operator GPU installation succeeded in the existing .venv (PyTorch 2.11.0+cu128, CUDA runtime 12.8, NVIDIA RTX 3070 Ti Laptop GPU, 7.658 GiB reported usable total; CUDA matrix multiplication succeeded). The earlier six-test command on the old implementation passed five tests including tiny training but failed the masked-objective backward test: the test mutated the target and labels in place after loss construction, invalidating tensors saved by autograd. Corrected the test to perturb clones, compare detached scalar losses and compare original/changed output gradients including the zero masked horizon. Test now exercises CPU and CUDA when available; tiny training uses CUDA when available. Model objective and training protocol unchanged. No need to reinstall working CUDA dependencies. Full-history V2 operator run completed on 98550eb: 13/13 tests passed in 1.483s including CUDA backward/tiny training; both GitHub workflows passed. 1,231 dates (2021-11-29 through 2026-11-26), 72 instruments (61 equities + BANKNIFTY + ten peers), 83 features per instrument, grid 11,034,684,000 bytes, 7,724 option receipts inspected, 420,202 training anchors, 18,228 validation, 18,228 evaluation, 49 evaluation sessions. Core validation best epoch7 Brier 0.5220331296; joint best epoch4 0.5198348731, early stop at7. Options train support 55,051 vs eval17,481; BOATS 0 train, 17,856 eval (cannot learn); banks train414,526 vs eval7,100; peers train413,396 vs eval17,983; global any-factor flag all anchors. Flags do not establish full source coverage.

| Horizon min | Eval scored | Calibrated prior Brier | Core Brier | Joint Brier | Joint conditional sign Brier | Joint minus core Brier paired 95% descriptive interval |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 18228 | .297939 | .275788 | .275169 | .250281 | [-.004503,.003245] |
| 5 | 18032 | .678161 | .597356 | .599263 | .251029 | [-.003996,.007647] |
| 10 | 17787 | .679847 | .657560 | .659184 | .251563 | [-.005068,.007961] |
| 15 | 17542 | .671104 | .670584 | .668267 | .252423 | [-.009394,.004406] |
| 30 | 16807 | .659408 | .654069 | .653401 | .252503 | [-.006797,.005626] |
| 60 | 15337 | .634602 | .625214 | .628631 | .252995 | [-.004729,.011931] |

All neural calls at >=60% directional confidence = 0; no unresolved scheduled evaluation outcomes at these horizons. Joint signed return MAE worse than no-change at all six horizons; joint up/down excursion mean MAE lower than adaptive in all six, not proof of statistical significance. Calibrated prior degraded vs raw at several horizons; do not overstate comparison. Conditional sign not better than simple prior, no incremental directional evidence from joint vs core. Snapshot baseline performed poorly; V3 uses stable smaller constant SGD rate and reports comparisons to raw references. V2 report results/banknifty_market_dynamics_c13afc6a249a457e9bc5bfcaed2d9f60.json with _predictions.csv and _research_only.pt. Only console evidence available here; exact source exclusions, parameter counts, dates and full artifacts not independently inspected. No trading qualification. V3 and separate OptionDynamics historical GPU experiments subsequently completed at c46f65f; results below. RL remains deferred until exact-contract execution can be validated.

### MarketDynamics V3 underlying-only and OptionDynamics (c46f65f; completed exploratory GPU studies)

Operator console on c46f65f: all 23 scoped tests passed (19 MarketDynamics, 2 OptionDynamics, 2 option-response), both CI workflows passed. V3 same 1,231 observed dates, 72 assets, 83 features, 11,034,684,000-byte asset grid and 420,202 / 18,228 / 18,228 anchors. All option input flags zero; overnight training support still zero, validation 3,348 and evaluation 17,856. Core 949,416 parameters, joint 1,142,952; 166 masked local asset channels, joint 90 retained auxiliary channels, long token channels 166 core / 664 joint, BF16 projections/FP32 GRU. Two pretrain epochs over 83,544 decision anchors per model; joint 5,264,491 used observed asset-horizon labels per epoch (overlapping, correlated, not independent observations), all 72 assets represented. Both selected epoch 5 by validation movement/sign rank: core .221144, joint .220932; multiclass validation Brier .521152 / .521131. Both stopped after epoch 8; lower training loss thereafter did not establish improved validation.

| Horizon min | V3 core Brier | V3 joint Brier | V3 joint movement Brier | V3 joint conditional sign Brier | Joint minus core overall Brier paired 95% descriptive interval |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1 | .274130 | .272139 | .126641 | .250124 | [-.003752,-.000506] |
| 5 | .592922 | .592453 | .237045 | .250615 | [-.003285,.001877] |
| 10 | .654766 | .650984 | .231598 | .250486 | [-.007945,.000076] |
| 15 | .668206 | .662372 | .214475 | .250390 | [-.009283,-.002319] |
| 30 | .651317 | .647540 | .172202 | .251394 | [-.007184,-.000841] |
| 60 | .623993 | .619697 | .130895 | .249728 | [-.006221,-.002309] |

Overall joint Brier point estimates better than V2 all six horizons; subsequent matched V2/V3 journal comparison confirms descriptive paired improvements at 5/10m only (all other intervals include zero); see matched ledger below. Joint vs same V3 core movement Brier intervals favor joint at 1,10,15,30,60m; 5m inconclusive. Joint beats raw historical constant and clock multiclass priors at 1,5,10,15m by descriptive intervals; 30/60 inconclusive. No conditional material sign advantage over raw constant at any horizon; 30m worse (interval [.000159,.002798]). Balanced accuracy joint 33.33%,33.87%,35.73%,34.55%,34.67%,35.35%. All neural calls at >=60% zero; joint signed return MAE worse than zero at every horizon, mean excursion MAE lower than adaptive at every horizon by point estimates (not significance). Raw/temperature-calibrated comparisons are reported; 60m calibration changes core and joint differently. No trade qualification or prospective confirmation. Report results/banknifty_market_dynamics_cc1e2cd0bf8749ecadaa6b2b8cf5d54b.json, matching _predictions.csv and _research_only.pt.

OptionDynamics: scanned 7,724 saved rolling receipts, 245 index dates, 147/49/49 reserved sessions; scored premium outcomes 54,652 / 18,225 / 17,482, unresolved 26 / 3 / 2, 47 scored evaluation sessions. Same-strike monthly-family observations, not exact executable contracts.

| Method | Exit premium MAE points | Delayed change MAE % of signal | Calibrated up Brier |
| --- | ---: | ---: | ---: |
| No change / prior | 18.840156 | 3.770899 | .24984452 |
| Historical bucket | 18.842172 | 3.773729 | .25036229 |
| Linear option only | 18.958921 | 3.779223 | .24951114 |
| Linear option + index | 19.082541 | 3.794060 | .24966503 |
| Neural option only | 18.874340 | 3.756809 | .24972976 |
| Neural option + index | 18.883383 | 3.757170 | .24958032 |

Neural option-only 20,996 parameters selected epoch1; joint 41,988 parameters epoch5. Both neural exit premium MAE differences vs matched linear favor neural ([-.150033,-.026293],[-.303724,-.103641]); both vs no-change inconclusive ([−.027965,.098390],[−.018471,.099394]). Both direction Brier differences vs base-rate prior inconclusive; calibrated accuracy 51.16% / 51.10% vs 51.41% base-rate majority classifier. Adding index context to neural option model shows no reliable increment in exit MAE, delayed-change MAE or direction Brier. Vendor-IV change MAE .379737/.379727 on 17,482 observed outcomes, option-only vs zero-change mean −.003592 with descriptive interval [−.006894,−.000729], joint interval [−.008284,.000673] inconclusive. IV observed at completed exit candle, not executable exit-open IV. No profitable strategy established. Report results/banknifty_option_response_118227870a3542d5bb5b3551345a5bca.json, corresponding _predictions.csv and _research_only.pt.

Only operator console evidence reviewed; original local report/CSV/checkpoint hashes not independently verified. The operator subsequently ran the matched comparator successfully (below). Previous holdout examined repeatedly; no architecture tuning against it. Freeze existing research artifacts and plan fresh prospective validation rather than claim a live edge.

### Matched V2/V3 prediction-journal comparison (51d5a25, exploratory)

Operator ran scripts.compare_market_dynamics on the previously saved V2 and V3 reports, no fitting or new historical downloads. Matched 103,733 scheduled rows over 49 observed evaluation sessions, all six horizons; comparator checks matching split definitions, timestamps and actual outcomes. 5-session block bootstrap, 1,000 draws, descriptive 95% intervals. Negative candidate-minus-baseline errors favor V3.

| Horizon min | Matched outcomes | Core overall Brier delta [95% interval] | Joint overall Brier delta [95% interval] | Joint movement Brier delta [95% interval] | Joint conditional sign Brier delta [95% interval] |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 18228 | -.00165750 [-.00290368,-.00054815] | -.00302969 [-.00685044,.00045799] | -.00200771 [-.00455359,.00031642] | -.00015705 [-.00049881,.00013066] |
| 5 | 18032 | -.00443395 [-.00635884,-.00249663] | -.00681079 [-.01311564,-.00101899] | -.00436847 [-.00837268,-.00085467] | -.00041377 [-.00220513,.00123393] |
| 10 | 17787 | -.00279377 [-.00471837,-.00102011] | -.00819999 [-.01466064,-.00220514] | -.00499704 [-.00824659,-.00196959] | -.00107729 [-.00420173,.00160828] |
| 15 | 17542 | -.00237756 [-.00375231,-.00112326] | -.00589506 [-.01279678,.00056861] | -.00291658 [-.00604296,-.00001508] | -.00203248 [-.00574357,.00111466] |
| 30 | 16807 | -.00275206 [-.00406634,-.00150620] | -.00586160 [-.01331120,.00108140] | -.00351415 [-.00654224,-.00070844] | -.00110881 [-.00482441,.00234603] |
| 60 | 15337 | -.00122032 [-.00196027,-.00044405] | -.00893478 [-.01844904,.00049118] | -.00340009 [-.00667844,-.00031357] | -.00326727 [-.00793836,.00121800] |

Core movement Brier paired intervals favor V3 at all six horizons; all core and joint conditional material sign intervals include zero. Joint signed return MAE intervals favor V3 at 1/5/10m only (deltas -.00628, -.02233, -.03531 bps); V3 joint still worse than no-change on absolute signed return error at all six. Joint up/down excursion MAE differences all inconclusive. Core 1m return and down-excursion MAE worsened; core 10m down-excursion MAE improved; other core MAE differences inconclusive. The models differ in architecture, objective, pretraining and joint inputs (V3 excludes options), so this is not an isolated architecture or width ablation. No multiple-comparison correction, no independent prospective confirmation, and no evidence of a reliable directional edge. All six V3 neural horizons still have zero qualifying calls. 103,733 overlapping horizon outcomes are not independent samples. These are operator console results from matched local artifacts, not independently accessed prediction files. Retain V3 as exploratory movement/range research, not trading-qualified direction. Next step: validation-defined conditional-sign research and prospective testing, not another arbitrary capacity increase.

### Global and fixed-time experiments (November 27, exploratory)

On the global-opening-context branch, operator reported local tests passing for global archive (9), Alpaca overnight (8), pre-open benchmark (4) and post-open benchmark (4). These are scoped unit tests, not a full release acceptance or investment claim.

    .venv/bin/python -m scripts.benchmark_global_open
    nice -n 15 ionice -c 3 .venv/bin/python -m scripts.benchmark_intraday_selective

Pre-open study: 60 observed dates, 56 paired dates, 27 out-of-sample sessions; decisions 09:10 IST. Opening gap accuracy domestic/global/combined 40.74%/51.85%/44.44%; first 15 minutes 48.15%/40.74%/40.74%; first 30 minutes 44.44%/44.44%/37.04%. Combined Brier/log loss worse than domestic in all three. No demonstrated global lift in this sample; no justification to purchase more intraday global data. Local report results/global_open_baseline_2026-08-29_2026-11-27.json.

Post-open study: 124 observed dates, 83 index and 54 matched constituent out-of-sample dates, 10 clock/horizon cells. Fixed 60% uncalibrated directional threshold, one-minute delayed index-open reference and hypothetical 5 bps cost. Selected after looking at results: 09:20 / 30m selective index took 13/83 opportunities, 9 directional successes (69.2%), +7.835 bps mean net proxy; 09:30 / 30m selective constituent took 23/54, 65.2% direction, +1.164 bps proxy; primary 09:30 / 15m was negative. These are small, post-hoc candidates, not proof of edge. Do not sum overlapping cells or deploy. Local report results/intraday_selective_2026-06-01_2026-11-27.json.

These two experiments are **closed as exploratory** pending genuinely new evidence. The next work is the five-year continuous forecast, not more fixed-time tests. All original historical strategy/membership reports and exact older instructions remain available in the pinned Git history below.

## Trading and execution research

The user's final research target is BANKNIFTY options entry, contract selection, position sizing, continuous hold/exit and abstention; other markets are context, not additional trading targets. The rolling underlying forecast is a foundation, and the final objective is net risk-controlled option policy performance. Existing tools already include forecast-to-option selection, paper position management and execution replay; do not describe them as yet-to-be-created from scratch. Existing read-only/manual cockpit and paper research are separate from core forecasting. Preserve directional and separate spread panels, live versus historical modes, latency and source age. Do not route orders.

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

The 85 superseded prose files were removed from the active working tree and the root README was replaced by this guide. Original contents, including exact historical mathematical equations, commands, audit details, acceptance matrices, research protocols and source references, remain in immutable pre-consolidation commit 9e0767dda26153a0b4b8c7cfb143e598f4023737. This is an intentional consolidation, not a claim that every historical experiment is current. The archived documents can conflict with later decisions; use them only for original details/provenance, never as a competing roadmap. No market data, notebook, result CSV, source code, model or machine-readable review template was removed by the documentation cleanup. Two old public documentation links were redirected here. Existing allowlisted /api/guide/{topic} endpoints now return this same README; the help screen has one canonical document link. Full acceptance pending following the documentation-route regression on 3cabad7.

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
