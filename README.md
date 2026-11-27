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
- **P0 — Direction qualification gate (CURRENT).** The five-year binary close/OHLC and matched domestic studies were negative. Preserve those results; investigate one fixed material-direction target with early-session support, delayed open-to-open outcome, explicit flat class, calibrated confidence and abstention. Do not prioritize premium forecasting until a useful directional signal has retrospective and prospective evidence. If it fails, report no qualifying signal and investigate a genuinely different information hypothesis, not a threshold/model search on the same holdout.
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
- [x] Implement a fixed matched EMA 9/21 and level-event hypothesis after the owner's observation of BANKNIFTY breakouts/reversals near prior OHLC/CPR and today's ranges. The new optional direction mode seeds one-minute EMAs from the preceding complete weekday, computes prior-day levels and causal developing levels, and encodes breakouts, retests/rejections and one-bar failed breakouts. Original 16-minute direction comparator retained; tests and empirical run pending.
- [ ] Pass EMA/CPR tests and run the fixed matched five-year study. Record both models, fixed level rules, directional (not merely flat-class) skill and event-specific outcomes; no tuning on inspected dates.
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

**Phase 3 — Option response (DEFERRED UNTIL DIRECTIONAL QUALIFICATION)**
- [x] Implement original rolling option history, theoretical Greeks/IV and BSM scenarios; existing predictive_option_research and forecast_depth_research.
- [x] Attempt mathematical premium-target, sector-confirmed, capped utility and supervised correction research.
- [ ] Audit actual local option coverage, price/IV/OI/volume and exact contract identity vs rolling family.
- [x] Implement fixed direct rolling monthly premium-response benchmark using original receipt loaders, delayed five-minute open-to-open labels, option-only and option-plus-index ridge/logistic, no-change and historical bucket baselines, validation-only sigmoid calibration and matched day-block diagnostics. Implementation committed; tests and run pending.
- [ ] Deferred: pass premium-response tests and run on saved 365-day range only after directional qualification; document coverage, unresolved outcomes and paired premium/probability scores. No executable net P&L claim.
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

**Current next command — matched EMA 9/21 + breakout/reversal context (P0):**

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

Calibrated model accuracy 58.0243% vs prior 57.8259%; largely flat-class classification, not 58% directional trade accuracy. Paired Brier differences against training prior -0.02018667 (95% descriptive block interval [-0.02630307,-0.01427880]) and clock prior -0.01805784 ([-0.02418730,-0.01236766]); this is multiclass probability improvement, not evidence of profitable direction. 16 UP and 22 DOWN calls; 38 total (0.0436% day-weighted coverage), opposite material hit 40.2941%, flat 19.4118%. Net index proxy per eligible opportunity -0.00263180 bps, interval [-0.00783141,+0.00114883]. Gate: Brier PASS, both directions PASS, support FAIL, positive proxy lower interval FAIL. State direction_not_qualified. Retain the failed protocol unchanged. Next distinct hypothesis to assess is whether causal prior-session and multi-day regime state adds direction value, with a matched short-history comparator, explicit exchange-session gaps and no overnight target leakage. The initial EMA/CPR level-event version of this hypothesis is now implemented (see current command); tests and local run remain pending. Wider multi-session regime features are not yet implemented. Do not claim a continuous multiday sequence or daily retraining exists. Do not tune thresholds on this already inspected test.

Local report results/banknifty_direction_gate_e4a7349a5b1d4c9c9f199ee400c35480.json and corresponding _predictions.csv. Console only; original report hashes not independently verified. No new source acquisition or production inference. Historical dates already examined remain exploratory. Even a retrospective pass requires frozen prospective shadow validation and separate actual option contract/cost/risk acceptance.

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
