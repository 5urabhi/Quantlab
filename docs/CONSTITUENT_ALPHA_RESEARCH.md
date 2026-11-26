# BANKNIFTY underlying-first alpha research

## Objective

Study 5–60 minute conditional index movements, not bid/ask scalping or latency arbitrage. Predict the underlying before choosing instruments. This feature is research-only and does not modify the existing automatic paper selector or send orders.

## Open and prepare

Open Trading → Directional / constituent intelligence → **Alpha research**. The existing Data setup section enables cash-equity capture, loads today's official membership, and imports reviewed dated weights; Signal research enables the existing prospective paired decision ledger. These remain explicit user actions. Quotes, index ticks, membership evidence and weights use the existing canonical library. Do not change recorder subscriptions or restart during capture just to run the study.

Alpha Research reports capture/ledger consent and completed recorded sessions. **Audit evidence & run model comparison** works even without sufficient training data and exports the coverage audit CSV. No historical backfilled calls or current weights are inserted into the prospective ledger.

## Frozen research specification

- Existing prospective protocol: 5, 10, 30 and 60-minute recorded outcomes. The 15-minute label requires a new prospective protocol version; it is not fabricated or silently substituted.
- Index features: 5/15/30-minute changes from earlier receipt-valid reference observations, observed one-minute realized volatility (at least 20 adjacent returns), EMA9/21 gap, RSI14 and time of session. No missing price is forward-filled.
- Constituent features: contemporaneous reviewed weights and aligned five-minute constituent returns, breadth, weighted dispersion, signed relative volume (five prior same-time samples required per constituent), ATP deviation and displayed buy/sell quantity imbalance. Optional aggregate features use at least 80% observed weight and a separate missingness flag. ATP is not necessarily a verified exchange VWAP, and displayed quantity is not aggressor flow.
- Membership and weight provenance must be present. Each included constituent current/anchor receipt must be available at its corresponding cutoff. Full weighted coverage is required for the matched sample; no equal-weight fallback.
- Split the first 60 completed **recorded** sessions in the original protocol into 30 training, 10 calibration, 20 holdout. Unsupported days are retained, not replaced. Current session is excluded. Require at least 60/20/40 scored samples from at least 20/7/12 supported sessions and 10 training samples in each class. More history is desirable before real decisions.
- Select non-overlapping decision windows greedily, including the 30-second target receipt allowance. A missing outcome reserves its window and remains counted. Samples can still be serially dependent.
- Three classes: future index return less than −5 bps, between −5 and +5 inclusive, above +5. Models: index-only standardized L2 logistic; matched constituent logistic; matched constituent histogram gradient boosting. Fixed classifier settings in code; calibration temperature chosen on the 10 calibration sessions, never holdout.
- Development expanding-window checks: first 20→next 5, first 25→next 5 sessions, subject to support. Final model assessment uses the frozen train/calibration split on later 20 sessions. This is a local chronological assessment, not an external preregistration or evidence that the researcher never saw those dates.
- Baselines: training class prior, no trade, 30-minute index momentum, rule-based regime momentum, EMA/RSI, weighted pressure and volume-confirmed pressure. The rule-based regime uses 30-minute movement relative to observed one-minute volatility; compression uses a 3 bps one-minute volatility threshold. It is not a fitted HMM.
- Class probabilities, Brier and log loss, classification accuracy, confidence reliability, selective direction hits, call coverage and descriptive net proxy are reported on matched observations. Probability models abstain unless the highest class is directional and has probability at least 0.60. The fixed hypothetical 5 bps round-trip index cost proxy is not an option fee, a spot fill or actual money.
- Conditional 10/50/90th percentile return regressors use training-only gradient boosting, with pinball losses against unconditional training quantiles, interval coverage and quantile crossing diagnostics. No future quote is used as a feature.
- Descriptive model gate: Brier better than training prior and, for constituent models, better than index-only logistic; at least 20 calls over 10 sessions; positive mean signed net index proxy. No gate is proof of significance, option profitability, or permission to trade.

## Verification and next dependencies

Run `python -m unittest discover -s tests -p 'test_constituent_alpha.py' -v`. Tests use synthetic fixtures and do not establish market performance. Browser acceptance checks insufficient-history behavior.

Pending: verified historical minute-level constituent acquisition and historical availability of dated weights (separate retrospective protocol); 15-minute and end-of-session prospective labels; opening-range / pullback studies, richer multihorizon constituent inputs, fitted regimes, LightGBM/XGBoost and empirical IV changes; instrument selection from predictive distributions using original option books, actual cost and margin constraints; untouched future-session prospective evaluation. Existing execution and paper-trading engines remain independent. Do not promote an in-sample or chronological result automatically to live decisions.
