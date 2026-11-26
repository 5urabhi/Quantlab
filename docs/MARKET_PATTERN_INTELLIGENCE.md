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

## Range-bound research and scalping costs
A fixed 30-change close efficiency ratio (absolute net displacement /
sum of absolute close changes) distinguishes a narrow compressed range,
low-efficiency range, high-efficiency trend and mixed movement. The
thresholds 0.30/0.65 and 0.10% close-width floor are uncalibrated research
heuristics, not probabilities or safe trade signals. Contiguous data is
required. The nonoverlapping historical study uses a fixed 20% edge band
and an inward close movement; chronological 70/30 comparison uses next
minute open to horizon close with excursion metrics. Paper Rule-Based
Replay supports the same causal rule with original saved option-depth
evidence; select Range-gated reversal and edge fraction 0.20. Existing
quote coverage, capital, size, execution windows, fees, and unresolved
fill safeguards remain active. It does not target a trade count.

Scalping economics is a user-input scenario, not a backtest. The
break-even win fraction is (average gross loss + round-trip friction) /
(average gross winner + average gross loss). Separate extra spread and
slippage are zero if already reflected in fill-based gross returns.

## Matched net scalping validation
Market Intelligence includes a user-started local background study, saved as
derived JSON under trading_cockpit/scalping_studies. It uses all requested
weekdays (max 60 calendar days, prior completed dates only; not an official
holiday calendar), requires original observed index minutes 09:15–15:28
with chronological receipt decisions, and fixes each day's pair using
the nearest observed monthly or other available expiry at 09:45 from a
hash-checked prior chain receipt no older than 120 seconds. Select the CE/PE
nearest the target ask within the premium band, size/affordability and spread
constraints; never select by future depth availability or profitability.
Each day/rule independently starts with the same research capital. Three
frozen rules use identical fixed holding time and original-depth replay
settings. Missing entry or exit observations stop and censor the day;
only days complete across all rules enter the matched comparison. Report
requested dates, reasons, attempts, fees, net P&L, profit factor, drawdown,
and extra fixed friction stress. Matched samples can be selection-biased;
no causal or profitable-edge claim follows. The 70/30 chronological weekday
split is fixed before replay. The per-side fee floor uses max(estimated
broker fee, floor) on executed turnover, not their sum. A daily loss
budget blocks new entries only after completed trades; it cannot guarantee
a loss bound. No provider calls or live orders. Test with
python -m unittest discover -s tests -p 'test_scalping_validation.py' -v.

## Current Zerodha costs (reviewed 26 Nov 2026 IST)
Official sources: https://zerodha.com/charges/ and
https://zerodha.com/marketintel/bulletin/445377/revision-in-stt-securities-transaction-tax-from-1st-april-2026 .
NSE IPFT is included in the transaction charge (Zerodha transaction-charge
support page). The common fee engine now supports asymmetric executed-order
counts. Market Intelligence → Scalping economics automatically calculates
all-in local estimates from actual hypothetical entry/exit premiums, target
exit price, and separate winning and losing payoffs. Replay uses the current
Zerodha tariff by default (optional per-side floor = non-additive stress).
These are current-tariff estimates, not historic contract-note reconstruction
or actual Kite execution costs. Do not double count spread in fill-based P&L.

Optional virtual-note comparison calls only documented Kite POST /charges/orders on explicit click with a user-entered exact symbol; response terms and charge sums are checked. No order-placement endpoints. Positions & Risk supports opt-in, page-scoped read-only GET /portfolio/positions every 60 seconds; broker-reported net positions remain separate from the journal and estimated liquidation P&L. Both require the existing authenticated local Kite session; synthetic tests do not prove real authentication.
