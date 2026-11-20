# QuantLab V2 — Screen-by-screen design contracts
Status: design review completed before frontend implementation. This is the build checklist, not proof of acceptance.
Source audit: src/Workstation.tsx, TradingCockpit.tsx, LiveFeedPanel.tsx, AutoDepthRecorder.tsx, OptionChainLive.tsx, StrategyWorkbench.tsx, ResearchPythonLab.tsx, HistoricalOptionsBacktest.tsx, MarketDataWorkspace.tsx, DataManager.tsx, ModelLaboratory.tsx, ResearchJourney.tsx, ResearchWorkspace.tsx, ResultsStudio.tsx. Synthetic Chromium screenshots are an illustration of frontend behavior, not live Dhan evidence.

## Global desktop layout
```
┌── 220px sidebar ──┬──────────────── topbar 64px ───────────────────────────────┐
│ QuantLab          │ Breadcrumb • market/data freshness • Jobs • Help • New Study│
│ Home              ├─────────────────────────────────────────────────────────────┤
│ Trading           │ Page title, description, *one primary action*               │
│ Strategies        │ Secondary tabs (max one row)                                 │
│ Models            │                                                             │
│ Data Center       │ Primary work (chart, editor, table, or interactive wizard)   │
│ Results & Charts  │                                                             │
│ Projects          │ Source context / companion panel / next action               │
│ Settings          │                                                             │
└───────────────────┴─────────────────────────────────────────────────────────────┘
```
Layout does not restart Dhan collector processes on navigation. Sidebar/hero should stay mounted on widget refresh. Main text minimum 14px, data tables 13px, metadata 12px. Responsive navigation drawer below 960px.

## 1. Home
- First paint: data API health + live recorder status (not assumed), recent research tasks, last completed results, current data coverage and three clear actions.
- Actions: "Test BANKNIFTY strategy" → Strategies/EMA, "Run a mathematical model" → Models, "Get missing market data" → Data Center/Get.
- Never show fabricated returns, fake equity charts or vague badges. No huge promotional decorative hero.
- Empty: No recorded history? Explain exactly how to connect Dhan and begin read-only capture, with "Settings/Connections" link.
- Error: API offline must show one next action, not a blank panel.

## 2. Trading
Tabs: Live Market / Option Chain / 20-Level Book / Market Replay / Journal.
- Live Market: market session in IST, real BANKNIFTY 1m/5m candle visualization, overlay controls, observed spot index, selected CE/PE and a compact recorder status card. Sidebar summary shows last packet age and source with "Open 20-Level Book".
- Option Chain: expiry, ATM-relative strikes, CE and PE quote comparison, last-updated watermark, LTP, bid/ask, OI/volume only if observed, lot calculator; read-only. Never call REST option-chain snapshots "full-depth" frames.
- 20-Level Book: original top-20 bids and asks, packet timestamp, spread (₹ and bps), depth share, visible selected-vs-verifiably-received contract counts. Empty/stale explicitly indicated; do not backfill missing L2 with estimates.
- Replay: session selector, shared timeline cursor, original spot/option/book observations synchronized. List gaps; no reconstruction claimed as original.
- Journal: real manual fills, paper trades and predictions separated. Entries have time, contract, lots, entry/exit, costs and source proof; no compulsory 6-minute trade time.
- Trading's old Options Backtest/Python Research tabs are migrated to Strategies; Dhan credentials to Settings.

## 3. Strategies
Tabs: Strategy Library / EMA Explorer / Python Editor / Backtests.
- Strategy Library: implemented strategies with compact readiness requirements and "Open" action. Model-specific input status refers to Data Center rather than duplicate acquisition.
- EMA Explorer: one fast/slow pair, comma-separated lists (max 256 pairs), full 11,026 valid 2–150 pairs. Top five cards with train returns, closed trades, drawdown and holdout. Any card opens matching red/green EMA/spot chart and trade ledger. Inputs are a snapshot of actually observed one-minute bars; missing periods are not invented.
- Python Editor: paste/type code and run bounded sandbox, example scripts, local snippet saves, syntax errors surfaced in same panel, no broker order permissions. Isolated from background Dhan recording.
- Backtest: separate "underlying index paper proxy" and "actual historical CE/PE" fill models; select cost/lot/contract/expiry. Hold until confirmed opposite crossover or observed EOD unless user opts into another policy. Source gaps unscored. Backtest results link to Results.
- Empty: missing original option candles show "Fetch exact contract data" and a precise availability caveat, not misleading paper option P&L.

## 4. Models
Tabs: Model Catalog / Index Builder / Advanced Research.
- Catalog: filters for stochastic, vol, derivatives/options, optimization, tail risk, 3D, and source types; each card says runnable math vs market-data-ready vs not applicable. Choose model → inspect requirements → configure → run → output; missing inputs link to Data Center (+20% buffer).
- Index Builder: factor weight settings, constituent caps, rebalance, dated universe membership, TRI mismatch warnings; run real index research, then inspect factor/risk/rolling sensitivity in Results. Never permit future constituent membership to leak.
- Advanced Research: existing rolling, risk, factor, concentration, robustness tooling accessible through secondary navigation or grouped advanced disclosure. No algorithms removed.
- Empty: tell users if insufficient history or quote evidence; theoretical models can run without market source where mathematically valid.

## 5. Data Center
Tabs: Market Library / Get Data / Data Explorer / Quality / Downloads / Source Provenance (advanced).
- Market Library: one canonical store; logical universe filters NIFTY50/NIFTY100/BANKNIFTY/NSE/sector, instrument counts, date ranges, sources and readiness.
- Get Data: instrument/universe + model needs → coverage plan → append/reuse/download only missing observations (+20% buffer) → progress → use source.
- Data Explorer: raw tables/price history, sortable/filterable instrument & contract views, data-source metadata and export.
- Quality: duplicates, gaps, detected source timestamp, data type (observed/reconstructed/synthetic), source age, provider repair + audit. Avoid false 100% evidence.
- Downloads: queue progress/retry/cancel and linked output, global Jobs drawer also works.
- Safe deletion: show dependent saved work; archive/Trash/Restore for derivations, protect original provider archive.

## 6. Results & Charts
Tabs: All Runs / Compare Runs / Chart Studio / Validation (advanced).
- All Runs: all archived strategy/index/model jobs in one searchable list. Click opens real result with Summary, Charts, Trades (when appropriate), Evidence, Notes.
- Compare Runs: 2–8 source-compatible results, matched dates, performance/volatility/holdout comparisons. Incompatibility shown explicitly.
- Chart Studio: hover, zoom, pan, legend toggles, overlay indicators, annotations, axes with correct ₹/%/bps/points and source dates; export figures. No duplicate graph builders.
- Run summary shows sample size, source, net returns after costs, drawdown, Sharpe/Sortino when statistically meaningful, warnings and next suggested test.
- Ask QuantLab as an evidence-aware side panel on the selected run, not a separate primary page.

## 7. Projects
Tabs: Projects / Notebooks / Reports.
- Projects: card per study with linked data/run IDs, description, last changed, notebooks and report generation.
- Notebooks: text, equations, saved chart/run references, drafts and autosave, export.
- Reports: read actual archived metrics/evidence; editable Markdown; PDF/HTML exports. No fabricated values, do not leak raw broker credentials.
- Version/delete/restore actions where existing backend supports them; metadata modifications do not mutate original history.

## 8. Settings
Tabs: Connections / Recording / Storage / Preferences / Diagnostics.
- Connections: Dhan + optional Zerodha read-only checks. Token handled server-side only; show validity/scope, not token.
- Recording: auto-resume approval and actual socket/contract/20-level coverage, packet-age, storage. Can stop/disarm explicitly; never stop when navigating pages or running a backtest.
- Storage: original provider history protected; derived runs/projects can be archived/trashed.
- Preferences: IST default for NSE data, ₹/%/bps/index points, comfortable/compact layout, contrast/reduced-motion.
- Diagnostics: FastAPI reachability, provider errors and repair actions with concise next-step messages.

## Cross-cutting interaction contracts
- A user must find each feature once; other pages contain links to that location rather than independently duplicated execution controls.
- Global Jobs drawer is available on every route, including during research. It shows actual queued/running/failed/completed results and source-coded errors.
- Global Help is contextual, not a full sidebar destination. New Study opens 5-step guided workflow as an overlay/page without duplicating model implementations.
- Restore UI state when navigating: selected instrument, research code editor, parameters, chart zoom and scroll must persist when technically feasible.
- Read-only research only. No automatic broker execution introduced.
- All existing module APIs, downloaded source tables, user notebooks and jobs stay backward compatible.
- Frontend automated acceptance: 8 primary links; every secondary route navigable; graph/editor/table functional; current Dhan recorder unaffected; no secret exposure; browser back/forward; 1440 and mobile viewport; no browser exceptions; build + unit + browser CI green.

## Existing component → screen ownership mapping
| Existing code | New owner |
|---|---|
| Workstation.tsx overview | Home |
| TradingCockpit / LiveFeedPanel / OptionChainLive / AutoDepthRecorder / SavedCaptureReview / MarketReplayPanel / manual journal | Trading |
| StrategyWorkbench / HistoricalOptionsBacktest / ResearchPythonLab | Strategies |
| ModelLaboratory / ResearchWorkspace research tools / Workstation index research / HistoricalValidationPanel | Models |
| MarketDataWorkspace / DataManager / MarketLibraryPanel / NSESourceAssistant / DhanDataManager / QualityPanel | Data Center |
| ResultsStudio / ResearchAdvanced / ResearchPlots / result comparisons / evidence checks | Results & Charts |
| ResearchWorkspace ProjectsPanel / saved notes/report editors | Projects |
| Dhan connection, recorder configuration, storage/health diagnostics | Settings |

## Delivery acceptance
Designs completed when this document and the interactive per-destination mockup are reviewed.
Implementation completed only when the actual existing React app adopts the new IA and every existing feature remains accessible, production build and browser tests pass, and no live recording interruption occurs when switching pages. The standalone mockup must never be mistaken for completed React functionality.
