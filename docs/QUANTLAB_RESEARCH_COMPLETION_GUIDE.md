# QuantLab — Research completion and original-data boundaries

**Implementation:** QuantLab Database Manager, Model Laboratory and Research Readiness Center. **This is a software acceptance guide, not a certificate that historical NSE market data is complete or that a strategy makes money.** Original provider access, genuine TRI, delisted securities, and specific regulatory licenses remain external evidence requirements.

## Beginner workflow (no terminal operations after launch)

1. Start QuantLab with `bash run.sh` (existing Ubuntu launcher).
2. Open **Data Library → Data Manager → Research readiness**.
3. Select the intended **original** dataset. Every registered model receives a status, minimum input length, preferred **+20%** buffer, next action, and disclosure of mathematical vs empirical inputs.
4. If needed, select **Get missing model inputs**. Choose the exact model and named instrument. QuantLab first reuses existing validated Dhan observations, then asks permission for uncovered Dhan date windows. An optional **Zerodha Kite Connect fallback** can be approved separately.
5. Leave **Run and save model after data completion** checked to perform **Select data → Resolve → Run → Save** in one source-bound background job. If genuine inputs are still missing, QuantLab returns an explicit blocker and does not substitute synthetic history.
6. Explore experiments, figures and reports in **Model Laboratory** and **Results Studio**. Saved model runs preserve the normal source/engine evidence.

Model mathematics (Black–Scholes, simulated stochastic processes, etc.) can run without live price data, but output remains visibly hypothetical. Historical quantitative research requires original observed inputs. Option-chain research requires original, time-stamped provider quotes. Some models can run with a minimum sample even when the preferred extra 20% cannot be obtained; that is an explicit limitation, not a successful extra backfill.

### Dhan → Zerodha Kite Connect historical fallback

The primary authorized daily price provider remains Dhan. An **optional** secondary provider uses Zerodha Kite Connect **daily** historical candle API only when a Dhan request is unavailable or fails for a recognized connectivity, entitlement or vendor reason.

- Enter your Kite developer **API key and secret** in **Sources & provenance → Zerodha**. QuantLab stores them only in a local mode-0600 file, never in a report or in GitHub; alternatively configure `KITE_API_KEY` and `KITE_API_SECRET` in ignored `.env`. Register `http://127.0.0.1:8765/api/data-manager/zerodha/auth/callback` in your Kite developer app; sign in from the **Sources & provenance** tab. Do not share secrets in ChatGPT, GitHub issues or public logs. The local setup form sends the secret only to the loopback API and never echoes it. The access token expires at 6 AM IST the next day; daily official login/2FA cannot be automated away.
- The alternative instrument must match the original Dhan equity by **exchange + exchange-issued security token + exact canonical trading symbol**. Kite's instrument master does not include an ISIN; no ticker-only, guessed-company or fuzzy identity mapping is accepted. Even an exact match still requires at least three agreeing historical Dhan close sessions.
- Check the distinct **Allow Zerodha fallback** checkbox before authorizing. The preview includes provider availability. No background credential escalation or live order submission occurs.
- A retrieved secondary daily-price history is admitted only after the same original-close validator finds **three or more matching observed Dhan sessions** for that security, with no contradictory overlapping observations. Original records are append-only. Unsupported adjustment conventions, security mismatches, missing original overlap or source licensing uncertainty remain blockers; the source receipt is preserved for review.
- Tokens expire and provider plans/rate limits vary. A configured alternative cannot guarantee download success. Dhan and Zerodha historical intraday entitlement and maximum lookback are separate from daily candles. The API does not make historical delisted constituents or genuine dividend-reinvested TRI available.

## Point-in-time NIFTY/BANKNIFTY and total returns

QuantLab already supports a pinned independent CC0 reconstruction of historic NIFTY 50 and NIFTY Bank membership with an **in-app Sync historical memberships** action, checks source checksums and effective-date intervals, and identifies original Dhan Security IDs that cannot be resolved against the current instrument master. This is **not official NSE certification**. Older changes, delisted/renamed members and rights must be reconciled against dated notices and a permissible instrument archive. A current index composition must never be projected into the past.

The Database Manager **Market-data evidence gates** separately display:

- Actual time-dependent NIFTY 50 membership and corresponding Bank NIFTY membership;
- Genuine, authorized NIFTY **Total Return Index** levels/returns, **not** price-only NIFTY spot levels;
- Publication-/ex-date-based dividends, bonuses, splits, spin-offs and delisting terminal payoffs; and
- Independent source-rights and calculation review.

Original TRI and corporate action uploads already exist in Data Library; QuantLab does **not** silently treat an attached source receipt as independent exchange certification or fill missing events with zeros. External source approval and exhaustive delisted-security coverage require genuine data.

## Verified original one-minute candles → Parquet

Open **Data Library → Data Manager → Minute & order book**.

- Select a locally downloaded 1-minute Dhan instrument. If none is listed, acquire original Dhan one-minute candles using the existing in-app Dhan manager.
- Select **Build minute Parquet** to make a local year-partitioned ZSTD mirror of original validated UTC timestamps, NSE/IST trading dates and OHLCV bars.
- QuantLab checks the original CSV and SHA-256 sidecar and refuses a stale/changed source. An enabled small mirror may refresh after a successful one-minute Dhan batch; larger mirrors remain manually refreshable to avoid excessive local computation.
- Explore original close/volume charts with hover values. Missing minutes are **not** interpolated, and no historical queue/depth is inferred from price bars.
- Local DuckDB/Parquet is an analytical acceleration layer. Canonical Dhan original files, SQLite daily close store and source manifests remain the source of truth. This does not yet guarantee that every numerical model is automatically optimized to query Parquet rather than its normal input files.

## Real order-book research — 20 or 200 levels

Open the **Historical order-book laboratory** in the same tab.

Dhan offers a **live WebSocket full-depth feed**. It does **not** supply an arbitrary historical 20/200-level order-book backfill through the historical candle API.

- For live recording, put `DHAN_ACCESS_TOKEN` and `DHAN_CLIENT_ID` in the ignored local `.env`; ensure your Dhan plan actually grants depth subscription rights. Choose exact `NSE_EQ:<security_id>` or `NSE_FNO:<security_id>`, 20/200 levels, a bounded recording window and opt in. The recording starts **now**.
- To analyze *earlier* depth, import authorized original CSV snapshots with columns `timestamp_utc,side,level,price,quantity,orders`. Both sides must be recorded at each timestamp, with ordered prices and no invented levels. Source timestamps must carry timezone offset.
- The UI reports real observed spread (bps), best midpoint, aggregated bid/ask quantity, order-book imbalance and fraction of full-depth snapshots, with hoverable plots.
- Source files and normalized receipts are kept locally. Live WebSocket receive-clock times are **not** guaranteed exchange event times. Trading/execution simulation, orders, historical event-by-event replay and full microstructure certification require additional timing and feed QA, not synthetic depth.

## Acceptance and honest status

Use **Research readiness → Run model software checks** to run a bounded set of eligible algorithms on observed inputs (if selected), or theory/simulation math without a dataset. Results are saved as **software audit receipts**, distinct from trading, benchmark or source validation. If a model is input-blocked, QuantLab names the missing source and next in-app action rather than inventing proof.

CI exercises strict TypeScript, Python regression tests, source-aware API endpoints, and Chromium UI navigation using isolated fixtures and mocked providers. **Live Zerodha/Dhan entitlements and download success cannot be certified by CI** because the token lives on the researcher's machine. Do not describe synthetic fixtures as real-market data.

The remaining evidence-dependent work, which cannot be completed by repository changes alone, is obtaining authorized historical delisted identities, a complete official TRI/corporate action ledger, real historical order-book archives if required, and a local live provider acceptance run. Their absence does not invalidate tested software behavior but prevents a defensible claim of complete historical research readiness.

## Developer reference

Core modules:
- `workstation_api/data_acquisition.py`: source plan, readiness +20%, explicit approval, single pipeline.
- `workstation_api/model_data_manager.py` and `single_series_completion.py`: cache-first original Dhan acquisition, guarded alternative provider.
- `workstation_api/zerodha_fallback.py`: authorized local Kite app setup, official daily sign-in, read-only verified NSE/BSE instrument master, token/symbol mapping and original Dhan price-overlap fallback.
- `workstation_api/compatible_sources.py`: append-only original-price evidence gate.
- `workstation_api/research_workflow.py`: resolve original source, run mathematical algorithm and save output.
- `workstation_api/research_acceptance.py`: all registered model statuses and source/software audit receipts.
- `workstation_api/intraday_parquet.py`: SHA-bound one-minute columnar mirror.
- `workstation_api/market_depth.py`: Dhan live packet parser/recorder, licensed CSV import, actual spread/depth metrics.
- `src/DataAcquisitionPanel.tsx`, `src/ResearchReadinessPanel.tsx`, `src/MarketMicrostructurePanel.tsx`: in-app controls.

Read the existing `docs/QUANTLAB_USER_GUIDE.md` for general project navigation and `docs/DATA_MANAGER_MODEL_ACQUISITION.md` for database-level detail.

Official API references:
- Zerodha Kite Connect historical daily candles: https://kite.trade/docs/connect/v3/historical/
- Dhan HQ full market depth WebSocket: https://dhanhq.co/docs/v2/full-market-depth/

### Real-source acceptance on your machine

Open **Research readiness → End-to-end real-data acceptance**. Choose a real dataset, the validation start and later untouched final-test start, then run. The saved report audits missing month/return cells, point-in-time constituents, original TRI, corporate actions, minimum 44 training months and 12 final-test months, plus eligible numerical algorithms. A structural pass does **not** set `independently_certified=true`; actual issuer source and licensing review remain external.

Kite session verification is a separate read-only in-app action. It checks login, **not** historical entitlement; the paid historical API must be exercised using your local account. The paid Kite Connect plan currently includes historical candles (Zerodha lists ₹500/month per app), while the free personal plan does not. See https://kite.trade/docs/connect/v3/historical/ and https://kite.trade/docs/connect/v3/user/.
