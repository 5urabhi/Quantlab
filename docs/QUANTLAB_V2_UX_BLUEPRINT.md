# QuantLab V2 — Whole-Workstation UX and Navigation Blueprint
Status: PROPOSED DESIGN; this document is a UX specification, not a completed UI migration.
Prepared: 2026-11-20
Scope: the authenticated/local React/Vite Workstation, not the separate public educational landing page.

## Evidence audited
- Source of current navigation: src/Workstation.tsx (10 main destinations and 21 internal tabs).
- Additional nested navigation: src/ResearchWorkspace.tsx (12 internal pages), src/TradingCockpit.tsx (6 tabs), src/ResultsStudio.tsx (9 result views), src/DataManager.tsx (10 sections), src/MarketDataWorkspace.tsx (3 pages), src/ModelLaboratory.tsx (6 mathematical families plus per-model views).
- Visual evidence: successful Ubuntu Chromium synthetic-acceptance screenshots in GitHub Actions run 44696984292: home, live/replay/options Trading, data acquisition/database manager, model readiness, results/evidence, plots, notebooks, comparisons and mobile. These are synthetic smoke screenshots, not a live browser inspection of the user's actual localhost or broker session.
- CSS example: src/workstation.css currently uses many 9–12px navigation, caption and table fonts, and a 258px sidebar. Multiple pages repeat a global title and a second large hero heading.

## Product objective
An approachable but serious local-first quantitative research workstation where:
1. All observed prices, options, order books, source snapshots and completeness checks originate in one canonical Market Library. A model requests missing inputs from that library and appends/reuses instead of making parallel duplicate datasets.
2. Two clear paths share the same data and results system: (A) BANKNIFTY trading/strategy research, (B) mathematical/index/portfolio model research.
3. All research uses one sequence: Choose source → Choose strategy or model → Configure → Run → Analyze → Save.
4. Users can paste Python and test EMA combinations without restarting the service or interrupting live Dhan WebSockets. Long work runs in isolated, lower-priority jobs.
5. Every number/chart has explicit units and a click-through evidence source; "implemented", "input ready", "simulation" and "independently validated" remain distinct.

## New primary left navigation (8 destinations)
| Position | New label | Purpose | Default subpage |
|---|---|---|---|
| 1 | Home | Status, work-in-progress, fast resumption | Dashboard |
| 2 | Trading | Market observation, real option liquidity and playback | Live Market |
| 3 | Strategies | Signals, EMA optimization, Python scripts, index and option backtests | Strategy Library |
| 4 | Models | Stochastic, index construction, risk, optimization and options math | Model Catalog |
| 5 | Data Center | One market library, acquisition, browsing, quality and downloads | Market Library |
| 6 | Results & Charts | All saved runs, interpretation, comparison and visualizations | All Runs |
| 7 | Projects | Notebooks, attached runs, reports and export bundles | My Projects |
| 8 | Settings | Broker/data connections, recorder settings, preferences and diagnostics | Connections |

Keep Help as a contextual '?' button in the top bar, not a ninth full-size destination. Move the five-step Guided Research screen into a global New Study workflow, available from any page. Move Jobs to a persistent top-bar drawer rather than a nested tab under Research Workspace.

Suggested deep-link routes are /app/home, /app/trading/live, /app/trading/options, /app/trading/depth, /app/trading/replay, /app/trading/journal, /app/strategies, /app/strategies/ema, /app/strategies/python, /app/strategies/backtests, /app/models, /app/models/index-builder, /app/data, /app/data/get, /app/data/explorer, /app/data/quality, /app/results, /app/results/{run_id}, /app/results/compare, /app/results/charts, /app/projects, /app/settings. Actual routing library is an implementation choice.

## Persistent application shell
Desktop:
- Fixed 216–224px sidebar: brand, compact eight-link menu, bottom privacy/offline indicator. No enormous promotional banner.
- Sticky 60–64px header: breadcrumbs, source context (e.g. BANKNIFTY, 1m, current project), global New Study button, search/command palette, Recorder status, Jobs, Help and user-local settings.
- Compact page title (22–26px) with one plain-language description and one primary action, not a repeated 37px title plus another inner 30px hero and several rows of status chips.
- Only one secondary tab bar on a screen. Prefer a secondary side panel or modal for advanced controls; no third set of same-level tabs.
- Content grid: full-width charts/tables for research, 65/35 chart and action sidebar for live trading, 2-column cards for overview. Do not keep a giant empty border around an unavailable chart.
- Global Recorder status always visible: configured vs receiving, 190/200 selected if that's the observed coverage, number with actual recent depth pairs, genuine saved books, socket count, last valid-packet age, dropped samples. Selected contracts must NOT be described as all recorded unless actual snapshots exist.
- Jobs drawer: running/queued/completed/error; progress, retry/stop when safe, source requirements, last error, logs and completed output. Never navigate away and lose access to progress.
- Preserve page state and scroll when switching destinations. Real URL routes must make browser Back/Forward, deep links and saved views work.
Mobile/tablet: collapse sidebar into an accessible drawer, move filters into a sheet, keep the one primary CTA and chart visible, make tables horizontally scrollable with sticky instrument/date columns.

## 1. Home — Dashboard
Default first screen, replacing the current Guided Research default.
Top: three action tiles: New Strategy Backtest, Run a Model, Get Missing Data.
Middle: (A) current market recording and provider health; (B) last research job, progress or resume action; (C) one canonical data coverage summary.
Bottom: latest saved runs and projects, any actionable errors, next recommended steps (e.g. 'EMA sweep complete: compare top five' or 'GARCH requires 60 aligned returns: fetch 72 with buffer').
Never lead with a decorative research banner or a synthetic performance graph when the user has no real saved result.
Home is a launchpad, not an alternate copy of Results Studio or the Data Library.

## 2. Trading — live observation and market replay
Secondary pages (only one row): Live Market / Options Chain / Order Book / Market Replay / Journal.
Live Market layout:
- Header: BANKNIFTY spot, market status/time (IST), stream freshness, chosen timeframe 1m/5m/15m/30m/1h.
- Main left: full candle chart with optional EMA9/EMA21 red/green crossover markers, indicators, zoom/hover, actual underlying price and axis units.
- Main right: read-only signal state, current selected CE/PE contract, premium, expiry, strike, exchange lot size, bid/ask and spread. Clearly distinguish model signal, paper trade and genuine manual fill.
- Under chart: compact side-by-side option-chain/depth preview and recorder health. Full 20-level ladder lives one click away.
Options Chain:
- Source-backed CE/PE table with search, expiry, ATM-relative strike range, LTP, bid/ask, spread, volume/OI if genuinely available, lots and source timestamps. Option-chain REST quote is NOT a 20-level streaming book.
Order Book:
- Single chosen contract, full original 20 bid and 20 ask levels, quantities, spread in bps/INR, imbalance, slippage/market-impact estimates labeled as estimates, packet age and 20-level entitlement. Show how many of the desired 190/200 selected contracts actually produced depth.
Market Replay:
- Synchronize BANKNIFTY candles, original chain and saved option books with a shared timeline scrubber, speed control and play/pause. Never create historical depth from OHLC candles.
Journal:
- Separate manual trades, paper trades and signal/prediction accuracy with clear source labels. No fixed 6-minute timer in the default EMA strategy; a manual timer can remain as an optional tool only.
Recorder setup belongs in Settings → Recording, while read-only status and a direct link remain in Trading.

## 3. Strategies — backtests and direct Python
Secondary destinations: Strategy Library / EMA Explorer / Python Editor / Backtest.
Strategy Library: cards for EMA crossover, existing EMA+RSI, momentum and genuinely implemented approaches. Each card shows strategy definition, required data, actual readiness, last tested dates and Open/Compare action.
EMA Explorer:
- Choose one pair (9/21 default), chosen EMA lists (≤256 valid combinations), or all supported 2≤fast<slow≤150 (11,026 pairs).
- Present the source/timeframe selector at top; below it, launch the isolated sweep. Show Top Five training-ranked cards and separately held-out evidence where available; annotate insufficient trade counts and search overfitting.
- One click on a pair opens its actual BANKNIFTY index chart, red/green EMAs, price/points, ROC momentum, RSI 70/30, EMA spread in bps and paper equity. Never confuse EMA spread with option bid-ask spread.
Python Editor:
- Direct paste/type/Run in the UI, syntax-friendly editing, code save/load, examples, inline validation and a useful error console. Standard-library signal(history) sandbox with no broker credentials or order access. Do not require file creation or terminal commands to iterate.
Backtest:
- Explicit two-column methodology: (1) underlying BANKNIFTY index directional signal and timing; (2) selectable fill model: index-directional 1× paper proxy OR historical original CE/PE contracts with actual strike, expiry, premium, exchange lot size, slippage/fees, missing-data exclusions. Do not present index-directional proxy as actual options profit.
- Default EMA reversal: confirmed completed index crossover → close existing long option and buy the correct opposite CE/PE at next original minute open; hold until opposite confirmed crossover or observed EOD. No arbitrary 5–6m cap. Optional risk-stop/time cap only if selected.
- Results appear in Results & Charts; backtest screen shows a focused mini-summary and an Open Full Results button.

## 4. Models — mathematical and index research
Secondary pages: Model Catalog / Index Builder / Saved Configurations (optional separate view).
Model Catalog:
- Existing families are **filters**, not six top-level routes: Stochastic Processes; Volatility & Econometrics; Derivatives & Options; Portfolio Optimization; Tail Risk & Inference; 3D Visual Laboratory.
- Add Factors/Index, Risk and Optimization tagging where existing code supports it. Model cards show implemented status, source-ready status, exact minimum observed returns, data frequency, units, equation/help popover and Run action.
- Clicking one model opens a standard four-stage workspace in place: Data → Parameters → Run → Results. Missing data has a single "Fetch missing (+20% buffer)" action that returns to the same model when complete.
- Display real/source-based vs theoretical vs seeded simulation honestly, without labeling working mathematical calculations as half-implemented demos.
Index Builder:
- Move current Experiment Studio index configuration, factor allocation, weight caps, rebalance rules, TRI/price-index distinction, historical membership, dated sectors, rolling validation and portfolio construction here.
- Results (factor IC, allocation charts, risk attribution, robustness) live in the saved run detail, not as five sibling sidebar destinations.

## 5. Data Center — one canonical market data system
Secondary pages: Market Library / Get Data / Data Explorer / Quality & Coverage / Downloads.
Market Library:
- One physical canonical instrument/history store with logical views: All NSE equities, NIFTY50, NIFTY100, BANKNIFTY, sectors, options, expiries, minute bars and recorded books. An index membership view must show as-of date and provenance.
- Search by instrument/contract, data frequency, provider and range. Show rows, first/last observation, missing intervals, contract eligibility, current coverage and freshness.
Get Data:
- One wizard: Choose universe/instrument → Choose timeframe/date/model needs → QuantLab checks existing coverage and provider availability → Download/append/repair only gaps (with +20% history buffer when the model requires it).
- Real data-provider errors are visible with next actions. No "NSE MCP lookup" jargon on the first screen; reveal provider details under Advanced.
Data Explorer:
- Select instrument/table, date range, preview OHLCV/quotes/depth, hoverable mini chart, search/filter/export. Move the old Database Manager's table browser here as an Advanced section.
Quality & Coverage:
- Actual vs requested bars, missing sources, original source stamps, provisional reconstruction vs observed, duplicated sessions, affected models, maintenance actions. Never show false 100% when provider lacks genuine 20-level frames.
Downloads:
- Global download jobs and append/repair history, retry/cancel safely, show progress and errors. Actual queues are also accessible from the global Jobs drawer.
Dataset deletion:
- Choose a derived/imported dataset and confirm the explicit list of dependent saved work. Raw vendor archive remains protected. Recoverable Trash and Restore live under Advanced Data Management.

## 6. Results & Charts — one place to understand output
Primary pages: All Runs / Compare Runs / Chart Studio.
All Runs:
- A searchable, filterable table of strategy, mathematical model, index research and Python-script runs; tags for original/synthetic/theoretical evidence, source range and stored result status.
- Clicking one run shows ONE run detail route with Summary / Charts / Trades (if appropriate) / Evidence & Validation / Notes. Summary first: net return with units, Sharpe/Sortino if actually defined, max drawdown, number of trades, source coverage, costs and missing-data warnings. Strategy, model and index metrics must be type-aware.
Charts:
- Common library of candle/line/equity/drawdown/bar/heatmap/scatter/3D primitives. Consistent hover, zoom, pan, legend toggles, annotations, crosshair/time sync, date range, units and source citations. Strong defaults first; full Plot Builder advanced edit from "Customize chart".
Compare:
- Choose 2–8 compatible saved runs, pin comparable time windows and units, show aligned return/benchmark/risk graphs and summary table. Do not quietly compare incompatible sources as if returns were comparable.
Evidence:
- Source hashes, exact parameters, dataset/contract IDs, train/validation/test split, observed vs reconstructed values, missing data and interpretation limits. Ask QuantLab is a contextual side drawer on the saved run; not another full tab.
Exports: Save chart, CSV, JSON, SVG/PNG where supported; Create notebook/report opens Projects with this run attached.

## 7. Projects — durable research knowledge
Primary views: Projects / Notebooks / Reports.
Show project cards with research question, linked sources, saved strategies/configurations, runs, figures, report status and last edit. One reusable notebook editor with interpretation, linked run, chart, table and formulas. Autosave, version history, delete/restore with dependencies. Generate and export HTML/PDF/Markdown reports only from actual saved evidence. Avoid separate floating "Research Projects" and nested "Projects & Notes" copies.

## 8. Settings — providers and diagnostics
Secondary pages: Connections / Recording / Storage / Preferences / Diagnostics.
Connections: Dhan/secondary Zerodha data connection health, scopes/entitlements and safe credential rotation, no tokens echoed to frontend or logs.
Recording: automatic read-only BANKNIFTY CE/PE capture rules, selected contract count, max socket limit, sample policy and persistent auto-start; verify fresh source packets vs saved samples.
Storage: disk usage/limits, caches, retention, export/backup and protected raw data rules.
Preferences: timezone (show IST for NSE), symbols/units (₹/%, bps, index points), light/dark, density and accessibility.
Diagnostics: API health, provider errors, source/job logs, retry and dependency readiness. Help / How it works is a global ? panel or contextual links, not another main navigation section.

## Remove or relocate current routes without deleting their features
Workstation 21 tab keys:
| Existing keys | Destination in V2 |
|---|---|
| overview | Home |
| trading | Trading, with Python/options backtest extracted to Strategies |
| journey | Global New Study guided wizard |
| data, dhan, nse | Data Center (Library/Get Data/Provenance) |
| mathematics, models | Models → Model Catalog |
| research, factors, construction | Models → Index Builder and saved Results |
| risk, rolling, robustness | Results → saved run risk/validation views |
| comparisons, visual | Results → Compare Runs / Chart Studio |
| workspace | Split by actual function: Results, Data Center, Projects |
| history | Results & Charts → All Runs |
| projects, reports | Projects / Results export |
| settings, guide | Settings / contextual Help |

ResearchWorkspace's 12 nested pages:
Start → Home; Library → Data Center or Results depending on resource type; NSE Sources → Data Center; Compare & Graph/Plot Builder → Results; Guided & Grids → New Study + Models; Index Research Studio → Models; Projects & Notes → Projects; Research Tools → Models/Run advanced tests; Data Quality/Evidence & ML → Data Center quality + Results evidence; Jobs → persistent Jobs drawer.

TradingCockpit's 6 tabs:
Live Trading → Trading/Live; Market Replay → Trading/Replay; Options Backtest → Strategies/Backtest; Python Research Lab → Strategies/Python and EMA; Trade Journal → Trading/Journal; Connections → Settings/Connections with visible health from Trading.

DataManager's ten internal sections consolidate into Data Center's five views. ResultsStudio's nine result tabs consolidate to five run-detail sections, with Compare in Results and Ask QuantLab in a contextual side panel.

## Shared design system / accessibility
- Keep a dark analytical theme as default, but brighten body text and substantially enlarge legibility. Main body 14–16px, form labels ≥12–13px, secondary metadata ≥12px, run metrics 20–30px, page titles 24–28px, table cells 13–14px. Current 9–10px primary information is too small.
- Base visual system: 8px spacing scale (8/16/24/32), 8–12px panel radius, 40–44px controls, at least 44px tap targets, consistent table row spacing, compact contextual captions. Avoid decorative KPI blocks that push actual charts below the fold.
- Teal = primary action / active / source streaming; blue = information; amber = incomplete/source warning; red = failure; green/red directional chart indicators are explicitly labeled. Don't use the same red as both bearish signal and backend error without a label/pattern.
- Maintain clear data lineage badges: LIVE (source freshness), RECORDED (historical original packet), RECONSTRUCTED (estimated with method), SIMULATED (theory/seeded), PAPER (non-executable trade), and VERIFIED ORIGINAL (byte-integrity, not vendor audit).
- Every chart has date/time/units, crosshair, zoom, export and evidence. No fake data to make dashboards look populated.
- Show errors next to the failed field/action with cause, severity, retry and link to diagnostics; don't reflow entire app on data polling. Real-time components update only numbers/traces, not the whole navigation shell.
- Keyboard focus-visible, screen-reader labels, color-independent graph legends, contrast testing, reduced-motion support, optional comfortable/compact density, empty/loading/error states for every primary view.

## Example workflow A — evaluate every EMA combination and trade it through CE/PE history
Home → New Strategy Backtest → Choose BANKNIFTY (1m index source) → Strategies/EMA Explorer → Test all 11,026 → See Top Five training-ranked cards and holdout warnings → Open one EMA chart and its actual crossovers → Backtest fill mode: Actual CE/PE contracts (not index proxy) → Resolve missing original option candles / lot evidence through Data Center → Simulate next-minute buy/close/reverse until next crossover or observed EOD → Results/Charts with trades, equity, drawdown, after-fee P&L, source gaps → Save to Project. Never restart live Dhan capture.

## Example workflow B — execute a mathematical model
Home → Run a Model → Select registered model → Source readiness checked automatically → Fetch missing history/quotes (+20% buffer) if needed → Configure bounded parameters → Run isolated Python job → Results summary/charts/evidence → Compare compatible runs → Attach to notebook/report. No manual parallel datasets and no unimplemented "demo" results hidden as empirical performance.

## Example workflow C — inspect real depth without recording interruption
Trading/Live → Options Chain select expiry/strike → Order Book view verified 20×20 quotes and original packet freshness → Market Replay select recorded session → Inspect synchronized exact source packets. The recorder is independent of React page navigation and the backtest worker. Zero broker orders unless a separate future opt-in system is designed and tested.

## Implementation migration (no big-bang rewrite)
Phase P0 — structural shell and navigation:
1. Adopt eight destinations + global New Study / Jobs / Help.
2. Add real URL routes, preserve state and move shared breadcrumbs, alerts and source selection into shell.
3. Remove redundant hero headers and fake 'refresh whole page' behavior.
4. Maintain compatibility/deep redirects for all 21 old tab keys; do not delete code/features yet.

Phase P1 — centralize user workflows:
5. Consolidate Data Center source/get/explore/quality/download paths on one canonical storage backend.
6. Extract options backtest/EMA/Python from Trading into Strategies; keep live, chain, depth, replay and journal in Trading.
7. Keep all existing model math and backend APIs while presenting one model catalog and index builder.
8. One Results run detail and common chart component library, merge comparison/plot/evidence UX.
9. Project notebooks/reports consume saved run IDs rather than copying results.

Phase P2 — visual polish, performance and verification:
10. Apply typography/spacing/color and shared responsive components to every route.
11. Tests for empty, error, stale, collecting, queued, running, complete, partial evidence and unsupported access states.
12. Confirm source refreshes preserve sidebar/editor/chart state, live recorder continues during research sweeps and Python, and no authenticated broker order endpoint is called.
13. Verify all old actions exist in new locations, no dead buttons, no inaccessible keyboard traps, 390px and 1440px layouts, zero unhandled browser errors and no new lookahead/measurement regressions.

## Acceptance checks / non-negotiables
- No existing model, data source, indicator, option recorder, historical analysis, project artifact, or chart is silently removed during navigation migration.
- Every feature has exactly one canonical primary location and contextual links elsewhere.
- Every common action can be completed in ≤3 navigation steps once the required source is present.
- No misleading demo values, fabricated order books or guaranteed strategy profits.
- No page navigation, backtest, pasted Python edit, or graph reload restarts the Dhan recorder. Source timestamps/data-loss gaps are measured during acceptance.
- All displayed financial quantities have correct ₹, %, bps, units, timezone and instrument identity.
- A beginner can progress with one primary CTA and a short instruction; an advanced user can inspect exact parameters, source records, code, metrics and uncertainty without losing context.
- UX QA must use synthetic browser fixtures for repeatability AND a local manual production-like smoke test with real recorded Dhan source (read only). The screenshot artifact alone does not prove actual market feed quality.

## What this spec does NOT do yet
It defines the navigation, page ownership, layouts, workflows and acceptance requirements. No React/CSS implementation or migration has been applied by this document. Do not interrupt a live recording session to install future structural UI changes; implement branch-by-branch and integrate on a safe restart after market close.
