# Research analytics closeout — scope and acceptance

This follow-up deliberately replaces generic tables with actual saved-source research workspaces, not new fabricated analytics or live broker features.

- Models: Factor Research, Portfolio Construction, Risk Attribution, Rolling Validation and Robustness & Sensitivity.
- Results & Charts: Index Comparison and Historical Charts.
- Each route uses the existing saved index run selector and immutable artifacts. Charts use explicit metric units, missing values remain null, original CSVs are downloadable, and bounded response rows have pagination and JSON export.
- Portfolio construction includes sector history where it was actually saved; active risk calls the existing source-gated covariance model; rolling beta and zero-risk-free-rate Sharpe use 12 consecutive saved monthly pairs. No substitute benchmark or factor data.
- Robustness uses one fixed execution lag and observed parameter cells; heatmap/surface require a complete grid. No interpolation of missing cells or claim of holdout significance.
- Market Library: observed endpoints timeline, selectable 1–90-day calendar record counts, distinct instruments, and calendar heatmap. The SQL API is read-only and bounded. Counts from different source types are never summed; an empty calendar bin is not proof of a missing exchange session. Exchange-calendar completeness requires a verified holiday/session calendar and expected instrument/subscription manifest.
- Verification: unit tests for activity limits, source type separation, unavailable data and zero counts; browser interaction test on an actual synthetic research engine run at desktop and mobile widths, plus a clearly labeled UI-only recording activity response. Existing full regression and route audit remain enabled.
- Remaining: dedicated Trading/Strategies/Projects/Settings redesigns beyond this scope, actual authenticated provider acceptance, and visual review on the user's machine. ML and RL remain deferred.
