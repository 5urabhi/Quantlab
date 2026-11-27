# QuantLab — Current implementation and remaining-work register

**Review scope:** November 27, 2026 IST. Read alongside the canonical release/evidence status and the actual CI result for the checkout. This is a targeted source review of the historical acquisition/session corrections plus the existing documented workstation capabilities, not a new independent every-page acceptance run.

## Implemented software

| Area | Implemented | Remaining verification or limits |
| --- | --- | --- |
| Market Library | Shared original data and receipt inventory; verified request scope and observed coverage; per-bank minute and complete-session audits | Re-audit actual local files under the new session policy |
| Automatic maintenance | Bounded automatic missing-data acquisition, resumable receipts, token recovery, independent productive lanes | Real source outages and rate limits still require backoff |
| Historical request scheduler | Pipelined option receipts; bank and option lanes overlap outside live-priority hours; two in-flight requests; 0.35-second minimum spacing; 80,000 local rolling-24h starts | Process-local counter resets on restart; external apps and other endpoints not counted |
| Bank continuous-session policy | Named 14 NSE bank stocks: 375 minutes before Aug 3, 360 from Aug 3 through Dec 6, then 375; real missing minutes remain repairable | Full point-in-time CAS eligibility, holidays and special sessions not established for all NSE securities |
| Option history | Original near-month rolling CE/PE requests, existing ATM ±10 maintenance scope; comparison-window coverage and separate extended-session raw receipt audit | Full exact-contract history, bid/ask and historical depth not established; post-Dec 7 full-session denominator requires exact expiry |
| Live recorder | Original quote/OI and 20-level depth; dated segment close of 15:30 / 15:40 / 15:45; storage and pressure guards | Verify post-15:30 capture locally; holidays/special sessions and real packet-loss behavior not fully validated |
| Data quality / provenance | SHA-verified original files, checkpoint recovery, rejected observation audits, optional Parquet/DuckDB cache | Independent vendor data verification |
| Guided Research and Model Laboratory | Source-aware inputs, existing factor/index/portfolio/stochastic/options models, charts and saved results | Run current model audit on actual local dataset; readiness and performance differ by model |
| Research validation | Chronological selection diagnostics, benchmark/risk reports, reproducible evidence bundles | Untouched empirical holdout and independently reproduced strategy performance |
| Trading research | Historical directional options tests, live option/quote analytics, modeled execution costs, spread analysis | Re-audit exact contract coverage, realistic execution, fees, spread fills, out-of-sample viability |
| Research assistant | Documented deterministic archived-results explanation | Not a validated autonomous trading agent |
| Second provider | Optional Zerodha daily equity fallback with explicit authorization and matching evidence | No assumed intraday/expired-option fallback or validated local credentials |
| Order routing | Deliberately excluded; read-only application | Not a missing feature to enable automatically |

## Priority work remaining

1. **P0 — Re-audit local evidence**: retain all original data. Check bank minute and complete-session counts using the new calendar. Inspect actual post-15:29 rolling receipts, live recorder through the new close, source-error diagnostics and any genuinely missing scheduled bars. No synthetic fills.
2. **P0 — Calendar completeness**: versioned exchange holidays, special sessions, historical CAS eligibility and exact listed expiry identities. December 7 expiring index contracts stop at 15:30 while others continue to 15:45; receipt coverage cannot guess exact expiry.
3. **P0 — Operational accounting**: persist historical request budget and provider cooldown across process restarts, reconcile separate processes/clients, measure actual download throughput and recorder loss/lag on authenticated local data.
4. **P1 — Extended-session research**: current strategy comparison window remains 09:15–15:30 intentionally. Build and independently validate full-session models, dated auction/settlement values, and correct expiry-specific exit rules before reporting results for extended sessions.
5. **P1 — Data needed for research**: exact dated constituent weights and memberships, historical delisted IDs, official TRI and corporate actions, dated fundamentals, original exact-contract pricing, and authorized external/global context. Historical depth cannot be reconstructed from minute candles.
6. **P1 — Strategy and spread validation**: actual bid/ask and latency, realistic costs, chronological train/validation/test splits, a frozen untouched holdout and separate directional/spread evaluations. No profitability certification from synthetic or in-sample results.
7. **P2 — ML/RL**: existing model catalog is not a fully trained and independently validated production trading agent. Validate dataset readiness, baseline comparisons and model performance before deployment.

## Local verification

After stopping the existing workstation at a safe recording boundary, update main and run the standard launcher:

```bash
cd ~/Desktop/codes/quantlab &&
git switch main &&
git pull --ff-only origin main &&
bash run.sh
```

Use Market Library to inspect observed minutes and complete sessions separately. Use `bash run.sh audit-models --dataset dhan_shared` for the current dataset/model acceptance and `bash run.sh check` for broader software acceptance at a suitable time. Do not stop an active live recorder merely to refresh this report. Local readiness, original data coverage, and code/CI acceptance are three separate statuses.

## Source references

- NSE/CMTR/74466 and NSE/FAOP/74467, May 29, 2026.
- NSE/CMTR/77355 and NSE/FAOP/77356, November 6, 2026.
- https://www.nseindia.in/static/products-services/closing-auction-session
- https://zerodha.com/marketintel/bulletin/461085/changes-to-closing-auction-session-cas-from-december-7-2026
- Existing internal evidence registers: [QUANTLAB_STATUS.md](QUANTLAB_STATUS.md), [QUANTLAB_COMPLETION_AUDIT.md](QUANTLAB_COMPLETION_AUDIT.md), [CPR_HYBRID_RESEARCH.md](CPR_HYBRID_RESEARCH.md).

## Multi-index research extension

`bash run.sh cross-index-research --sessions 90` compares BANKNIFTY and NIFTY 50 on common completed historical sessions. Both targets receive an index-only baseline and a matched peer-index augmented model, with validation-only model selection and day-paired exploratory Brier differences. Tasks include terminal direction, volatility regime, and normalized first touch at 5/15/30-minute horizons. Peer features use only completed observations; missing bars remain missing. This is a forecast study, not an options backtest.

`bash run.sh cross-index-research --list-sources` inventories additional named indices against the existing Dhan master and candidate original receipt files. NIFTY 100, NIFTY Next 50, FINNIFTY, NIFTY Midcap Select, NIFTY 500, NIFTY IT, NIFTY PSU Bank, NIFTY Private Bank and India VIX are research identity candidates. Their actual instrument resolution, minute-history entitlement and saved coverage require local verification. No extra automatic downloads or live subscriptions are enabled by this change. Existing automatic BANKNIFTY/NIFTY 50 scope is unchanged. NIFTY 100 is a broad market context series, not assumed to have listed index options. Generalizing the BANKNIFTY-specific option receipt keys, expiry schedules, lot sizes and execution model to additional listed underlyings remains separate work.
