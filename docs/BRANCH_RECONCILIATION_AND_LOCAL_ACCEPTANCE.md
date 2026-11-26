# QuantLab branch reconciliation and local acceptance

Base main: 50ccaa6dd7e4b015e5f999a6d22d2c53d1efcf8a. PRs #107–111 are merged. Both final-head workflows of #110 and #111 passed, including all route desktop/mobile audits, preserved Classic workflows, new chart interactions and constituent UI fixtures. These are offline/synthetic software checks, not authenticated market entitlement or trading results.

## Older branch dispositions

| Branch | Ahead / behind main at audit | Disposition |
|---|---:|---|
| feature/quantlab-local-backup-execution-stress-20261117 | 2 / 224 | Both unique modules ported into this PR with bounded safety controls, API, UI and regression tests; retain the old ref until new CI passes. |
| feature/quantlab-multi-provider-option-coverage-20261122 | 11 / 129 | Preserve as optional Upstox research; not activated or merged because the selected providers are Dhan and Zerodha. |
| research/multi-factor-equity-index | 294 / 269 | Preserve divergent legacy history. GitHub reports 112 changed files. Do not wholesale merge obsolete Streamlit/research code over V3. |
| workstation/quant-research-development-20261112 | 424 / 269 | Preserve divergent legacy history. GitHub reports 132 changed files. Current V3 is the active application; no wholesale merge or deletion. |

These are ancestry/file-inventory comparisons, not a proof that every historical implementation is equivalent. The two legacy histories remain available for exact per-feature review if needed. No branch deletion, provider changes or original data deletion is performed by this reconciliation.

## Recovered features
- Storage: local metadata-only SQLite copies with explicit consent, per-database consistency, SHA-256 and SQLite integrity verification, bounded size/time/free-space checks, and no restore route. Backups may include sensitive user-entered notes; they do not contain the original market datasets, credential files or complete research artifacts.
- Robustness: incremental fee/half-spread/square-root impact scenarios over original archived gross/net returns and turnover. Original cost retained; no observed fills, verified exchange fees, ADV, capacity or execution claims. Zero incremental costs must reproduce the archived net returns.

## Authenticated local acceptance (no recorder restart required for checks)

1. After updating the local source, launch the workstation with the existing `bash run.sh` command. Confirm Dhan read-only token is configured and the all-option recorder is already armed. Do not open an extra WebSocket.
2. In Data Centre > NSE Source Evidence, confirm that installed dated membership actually covers the current NSE session and the Dhan master uniquely resolves every member. Supply an authorized, reviewed dated BANKNIFTY weight CSV under Trading > Directional Trading (columns symbol,weight_pct). Do not invent weights.
3. Enable constituent recording. It is deliberately separate consent; the shared option socket adds the exact equity subscriptions at the next natural connection, only if all members fit in remaining capacity. Do not force reconnect a running capture.
4. During a regular NSE session inspect the local status and analysis endpoints below. Confirm the existing option quote counter continues advancing, no additional socket is opened, expected members resolve, saved samples advance, storage/drop state is explicit, timestamps are fresh, and aligned coverage is reported. Market Library should list constituent quote receipts. After at least five qualifying earlier same-time recorded sessions, relative volume is eligible. Otherwise it correctly remains unavailable.
5. Verify local sandbox and mathematical data readiness without stopping the recorder:
   ```sh
   bash run.sh verify-v3 --scientific
   bash run.sh audit-models --dataset dhan_shared --preflight-only
   curl --fail --silent http://127.0.0.1:8765/api/trading-cockpit/constituents/status
   curl --fail --silent 'http://127.0.0.1:8765/api/trading-cockpit/constituents/analysis?horizon=5'
   ```

## Prospective directional research gate

Current constituent analytics are descriptive. For a valid comparison against EMA, freeze the pressure rule, EMA rule, observation clock, 1/5/10/30/60-minute target windows, missing-data exclusions and transaction cost assumptions before looking at future returns. Log time-stamped decisions from both methods on the same eligible receipt-time information, then join subsequent original index observations without forward-fill or future leakage. Report joint eligible count, per-method coverage and abstentions, paired directional accuracy, confusion matrices, and session-cluster uncertainty; separately backtest actual tradable option bid/ask and costs before any profitability claim. A prospective paired decision ledger and real observations remain required. No live accuracy, calibrated probability or P&L is claimed by this release.
