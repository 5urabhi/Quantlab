# Market pattern intelligence

Open Live Trading / Index monitor or Option Chain in QuantLab. The rolling
365-calendar-day report reads the existing Dhan IDX_I minute receipt library
and today's observed shared SQLite minute bars. Refreshes every 30 seconds.
It is not a separate dataset and never submits orders or opens a new socket.

- Historical regular sessions require exactly 375 distinct minute slots
  (09:15–15:29 IST). Today's bars are excluded from the baseline. The report
  shows actual source dates/counts, partial days, invalid receipts, omitted
  receipts, and overlap revisions; missing whole sessions are not inferred.
- Newest SHA-verified receipt wins overlapping minutes. Current observed
  minute bars supplement original history, but cannot replace original
  historical OHLC evidence. Missing current minutes make observed ranges
  lower bounds and disable equal-clock comparison.
- One-time "Enable read-only history sync" stores local consent and uses the
  existing authenticated Dhan connection. It backfills uncovered receipt
  date windows (up to 90 calendar days per request; at most five per pass),
  checks after close from 16:00 IST and retries no faster than 30 minutes
  while the local server is running. Sync covers BANKNIFTY. NIFTY50 uses
  existing saved receipts if selected. It does not infer missing holiday
  sessions or guarantee minute completeness inside a requested window.
- Historical probabilities are descriptive frequencies, never predictive
  confidence or option P&L. Forward windows overlap. Breakout examples use
  next observed minute open, not same-bar fills; in-sample index proxy only.
- Existing Constituent Intelligence, Advanced Options, spreads, option
  backtests and execution paper simulation stay separate and unchanged.

Local acceptance: python -m unittest discover -s tests -p 'test_market_patterns.py' -v
and npm run build, then launch with bash run.sh. Verify coverage with actual
Dhan data. No real market data or credentials are included in fixtures.

## Workspace organization
Live Market keeps the index chart first, with compact movement context and
an all-member heatmap alongside on wide screens. Heatmap colors use observed
interval returns or observed opening-sample returns; missing/stale values
are gray. Dated weights determine tile order, not invented size. Full
historical tables live on Market Intelligence; full constituent diagnostics
remain on Directional Trading. Options Analytics and Positions & Risk are
primary trading destinations. Depth, spreads, replay, paper trading and
custom scanners remain accessible through More tools.

Positions & Risk reads the existing manual trade journal and full-size
bid marks. It adds combined conditional BSM scenarios over -2000..+2000
points, with a shared spot reference, per-leg inferred IV, spread/slippage
and fee assumptions. Incomplete, expired, unsynchronized or invalid-IV
baskets do not produce a portfolio scenario. No actual broker-account
positions are claimed. Conditional historical pattern tables use fixed
rules, a chronological 70/30 split, one first event per session, next-open
index proxies and MFE/MAE; not option returns or proof of profitability.
