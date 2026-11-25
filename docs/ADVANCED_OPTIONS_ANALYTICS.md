# Advanced Options Analytics

Open **Trading → Option Chain → Advanced Analytics**. The Overview
remains available. This workspace does not start another WebSocket,
change recorder consent, submit orders, or require completed ML/RL research.

## Manual contract comparison

Select an original Dhan expiry. Enter available capital, maximum lots,
preferred premium, a direction (UP, DOWN or BOTH), assumed BANKNIFTY
move in points, holding minutes and IV change in percentage points.
The maximum premium exposure is an adjustable ceiling (default 100%,
not a recommended allocation). Change it to match your own loss limit.
Apply the assumptions. BOTH compares calls under a positive assumed
move and puts under a negative assumed move, not a forecast of direction.

The contract filter requires a recent local regular-session chain
receipt (within 30 seconds), exact master identity and lot size,
positive noncrossed bid/ask, bid >= INR 20, relative spread within
the entered ceiling (default 250 bps), model absolute delta 0.15–0.85,
positive reported OI/volume, affordable and top-level-quantity-supported
lot size, a valid midpoint IV solution, sufficient remaining tenor,
positive favorable net P&L and valid adverse, flat and IV-crush scenarios.

The score is NOT a win rate or expected profit. The fit components are
reward/risk (50 points), spread (20), premium proximity (15), favorable
return (15). Reward/risk includes unfavorable underlying movement,
time decay and a further two-percentage-point IV-contraction shock.
Ranking prioritizes three evidence tiers:

1. Recent source trades and independently validated original 20-level
   book received within 8 seconds, with matching bid/ask within the
   explicit tolerance and sufficient displayed top-level quantity.
2. Recent source trade timestamps and cumulative-volume increase,
   but without the highest-tier depth confirmation.
3. Indicative snapshot-only comparison; recent activity unverified.

The source trade screen uses two distinct exchange last-trade timestamps
and growth by at least one verified lot in the preceding 120 seconds.
These are other market participants' observations, not user order fills.
Indexed depth reads check at most the leading 60 candidates plus the
selected ID. Unchecked depth is not declared absent. Stale, changed
assumptions, or failed requests suppress the current shortlist.
Historical/blocked rows remain inspectable. Actual spread, fill probability,
queue position, intraday profitability and broker execution remain unknown.

## Analytics tabs

- **Best-fit contracts:** both directions can be compared independently;
  ranked contracts, evidence quality, scenario net P&L and loss-to-zero.
- **Greeks:** independent BSM Delta, Gamma, Theta per calendar day, Vega
  per IV percentage point, Rho per rate percentage point, intrinsic /
  extrinsic and position-level sensitivities. Provider Dhan Greeks
  are shown separately, without assuming their units.
- **Volatility:** bid/mid/ask IV inversions with no-arbitrage bounds,
  provider IV changes, skew/smile, observed term structure and
  same-expiry ATM IV history. IV rank/percentile requires at least
  20 prior observed dates. It is not a constant-tenor IV index.
  Realized volatility requires at least 30 contiguous saved index
  one-minute log returns, annualized using sqrt(252 x 375).
  India VIX is explicitly unavailable, not fabricated.
- **OI & Volume:** reported OI/volume and prior same-session receipt
  differences, descriptive price/OI states, PCR and max pain if
  coverage is complete. Unsigned gamma x reported OI x spot squared
  x 1% is a proxy per reported OI unit. Dealer positioning sign and
  OI unit convention are not established; dealer GEX is unavailable.
  No inference of long/short participant identity from OI changes.
- **Liquidity:** relative spread, top-level quantities, independently
  validated saved original depth, imbalance, recent trade evidence
  and cost estimates. The chain itself remains a REST snapshot.
- **Trade Calculator:** affordable lots including entry charges,
  full premium risk, estimated break-even SELL premium, quote crossing,
  position Greeks, favorable/flat/adverse and IV shock scenarios,
  and detailed fees. A manual journal draft is not an order.
- **Watchlist:** exact local contract IDs in browser localStorage;
  compare them against the selected current expiry. IDs from other
  expiries remain stored but are not represented as fresh.

All model values are conditional on user-entered risk-free rate and
dividend yield, a regular 15:30 IST expiry assumption, European BSM,
365.25-day year, and constant IV shocks. Scenario exits use theoretical
midpoint less current half-spread and an adjustable exit-slippage haircut.
The fee schedule reuses the existing indicative broker tariff model;
exercise/settlement, unmodeled levies, actual fills and rounding are
not independently broker-verified. Future IV, execution and spread are
unknown. A long option can lose all premium plus entry costs.

## Data and performance

The analysis endpoint calls the existing cached and rate-limited
Dhan chain function; the advanced view suspends the Overview polling
and refreshes every 30 seconds while visible. It uses read-only
bounded SQLite queries over the same market library. History uses
the latest prior saved chain, up to 60 prior daily samples, at most 40
selected-contract saved receipts, up to 12 latest same-day expiry
observations, up to 121 completed index bars, and the preceding
120-second Quote/OI window. The historical chart never invents
missing observations. The original recorders and schema are unchanged.

## Validation

```bash
.venv/bin/python -m unittest discover -s tests -p test_advanced_options.py -v
npm run build
```

CI's synthetic fixtures check the BSM kernel against the preexisting
math implementation, quote IV inversion, fee-adjusted position sizing,
source evidence tiers, stale/missing data, historical IV/OI and realized
volatility, endpoint behavior and browser navigation/watchlist.
Passing these tests establishes software behavior, not evidence of
live trade profitability. Actual local Dhan data remains unverified.
