# Index Builder V2 — source → factor model → index rules → backtest

## Scope
The **Models → Index Builder** destination is now a guided, responsive research workflow. The numerical index engine, dataset selection semantics, saved Python results, transaction cost and execution timing conventions are unchanged. This is a usability and input-readiness improvement, not new verified historical performance.

### Step 1 — Real source evidence
Choose from the existing canonical `dhan_shared` market library, user-provided research source, or explicitly labeled synthetic demonstration. The Index Builder now distinguishes four inputs instead of a single unhelpful READY/NEEDS INPUTS badge:

- Saved monthly price matrix (`prices.csv`)
- Historical effective-date index membership (`membership.csv`)
- Compatible historical benchmark returns (`benchmark.csv`)
- Publication-dated fundamentals (`fundamentals.csv`) when Value/Quality/Size is selected

A fifth conditional source (`sectors.csv`) is required if a sector cap is enabled, and `benchmark_weights.csv` is required if benchmark-relative portfolio optimization is selected. Any additional historical provenance exceptions recorded in the dataset manifest are presented by name, rather than silently ignored. A saved file alone does not certify official total returns or point-in-time source quality.

Explicit actions link to existing **Get Market Data**, **NSE Source Evidence** and **Market Library**. Price candles can be acquired automatically from an authorized Dhan provider through the existing Data Center; actual dated constituent membership, official TRI and publication-dated fundamentals are separate evidence categories that cannot be invented from daily candles.

### Step 2 — Factor research
The five supported UI factor contributions are Momentum, Low Volatility, Value, Quality and Size. All are calculated by the existing `index_research.factors.composite_scores` Python engine. Contributions are nonnegative; the normalized percentage of the current blend appears while editing. Value/Quality/Size immediately reveal the as-of fundamentals dependency. There is no silent fallback that substitutes simulated factor observations.

### Step 3 — Portfolio construction
Core controls are the experiment name, top-N constituents, weighting method, maximum constituent weight, rebalance months, transaction costs in **bps**, and execution timing. The list now exposes the existing Python `benchmark_relative` methodology, including the extra dated benchmark-weights source requirement, without changing the optimizer.

Less commonly used parameters—factor formation, skip, volatility lookback, optional chronological validation/frozen-test splits and sector caps—are visible within **Advanced** rather than cluttering the entry screen. A mathematically infeasible `top N × max weight < 100%` configuration is flagged before the server call; an explicit one-click cap adjustment is provided.

### Step 4 — Run & results
The Run button is enabled only when required dataset metadata and configuration gates pass. When the Python job succeeds, the existing Workstation logic saves its real result and navigates to Results & Charts; no hardcoded result dashboard is created. Short historical windows remain labeled exploratory rather than fake 12-month Sharpe/CAGR outputs.

The existing **HistoricalValidationPanel** and advanced frozen-evaluation preparation remain accessible under a disclosure panel so their functionality is not removed.

## Local acceptance
1. `git pull --ff-only origin main`; run `bash run.sh`.
2. Open **Models → Index Builder**. Verify source, factor, constraints and run sections are visible; show results navigates to the correct saved-run destination.
3. In the empty or incomplete `dhan_shared` source, verify explicit provenance blockers and actionable navigation to market data, NSE source and benchmark preparation. A disabled run must explain the blocker.
4. Slide Value above zero without `fundamentals.csv`: the source is blocked. Slide back to zero: this additional blocker disappears. No provider request is made simply by editing a factor.
5. Select top-N 3 and max weight 20%. A feasibility message appears. Click **Use a feasible cap**; the chosen cap becomes at least 34%.
6. Expand Advanced and verify historical split dates and sector cap behavior. Selecting benchmark-relative weighting with no `benchmark_weights.csv` exposes a blocker.
7. Test a genuine prepared source (or explicitly labeled synthetic fixture) with required files. Start a run, observe global Jobs and verify saved results, not a fabricated performance summary.
8. CI: `npm run build` and the V2 Chromium browser acceptance must pass. These use synthetic source fixtures and do not certify empirical NIFTY index performance.

## Known follow-up scope
Separate index research engineering remains necessary for institution-grade release: final PIT historical membership and delisted symbols, source-published Value/Quality records, official matched TRI, corporate-action-adjusted stock total returns, dated risk exposures and liquidity, out-of-sample/frozen holdout governance, and valid empirical backtests. The software's existing sample-size display is a preflight estimate; server-side index experiment validation remains authoritative.
