# Liquidity & Spreads — BANKNIFTY research workstation

Location: **QuantLab → Trading → Liquidity & Spreads** or direct
\`http://127.0.0.1:5173/login#/tradingspreads\` under the existing app shell.

This is independent of **Settings → Automatic Recording** (collector
configuration and health), **Trading Cockpit** (directional decisions and
journal), and **Market Replay** (source-session navigation). It uses **only
Dhan**, never creates additional broker connections, and does not execute,
queue, replace, or cancel broker orders.

## Four working tabs

1. **Live Spread Monitor:** Reads at most 200 currently selected 20-level
   identities and their saved bid/ask features from the existing automatic
   Dhan recorder. Displays price, quoted spread ₹/bps, 20-level imbalance,
   top bid/ask quantities, freshness of original paired packets, sampled
   book age, core/activity/rotating status, CE/PE/strike/expiry search,
   and a two-contract visual comparison. A selected contract shows
   exactly 20 original bid and ask levels if its book was saved.
   **A recent source packet does not make a 30-second-old saved quote
   executable.** No inferred depth for unsubscribed contracts.
2. **Execution Simulator:** Uses a selected actual saved Dhan 20-level
   book and master-verified lot size. Sweeps asks to model a marketable
   purchase and bids to model a marketable sale for 1–10 lots. Rejects
   a full-price estimate if there is not enough observed original
   quantity. Separately shows a **two-passive-fill optimistic upper
   bound**, which may be unfillable, and an explicit bps adverse-move
   stress scenario. No observed fills, queue position, broker orders, or
   realized P&L are assumed.
3. **Historical Spread Analysis:** Reads bounded original saved
   depth snapshots with source timestamps from the same
   \`dhan_shared\` SQLite store, dates in IST. Interactive point-hover
   chart, optional overlay, 20-level source-book inspection, and
   explicit sample-cadence / scan warnings. This is not a continuous
   bid/ask tape or a reconstructed historical market.
4. **Spread Strategy Lab:** Fee-adjusted counterfactual sensitivity for
   the selected original book samples, with marketable same-book net
   costs versus theoretical passive net and adverse stress. Reports
   optimistic positive *snapshot* counts, not profitable executed
   trades. \`realized_pnl\`, \`fill_rate\`, \`sharpe\` and verified
   trade count are intentionally unavailable without execution evidence.
   This is a usable **research bound**, not a queue-aware real-fill
   backtest or a trained spread-trading strategy.

## Endpoints (local loopback only)

- \`GET /api/trading-cockpit/liquidity/overview?limit=200\`
- \`GET /api/trading-cockpit/liquidity/history?identity=NSE_FNO%3A62539&day=2026-11-23&limit=300\`
- \`POST /api/trading-cockpit/liquidity/simulate\` with
  \`{"identity":"NSE_FNO:62539","lots":3,"day":"2026-11-23","adverse_move_bps":25}\`
- \`GET /api/trading-cockpit/liquidity/research?identity=NSE_FNO%3A62539&day=2026-11-23&lots=3\`

All are bounded and source-ID validated; only simulation is POST
to pass bounded hypothetical parameters, not a broker order.
Original source \`packet_pair_sha256\` and local receipt time are retained
as provenance. The history reader excludes non-Dhan-auto or corrupt
books and revalidates bid/ask ordering and 20-level payloads. The
source table is append-only and is never reconfigured or deleted.

## Cost model and where it is approximate

Default Nov 2026 illustration for NSE **equity options**:

| Component | Base assumption | Notes |
| --- | --- | --- |
| Dhan brokerage | ₹20 / executed order | Two sides and adjustable number of executed orders |
| STT | 0.15% of sell premium | Effective April 1, 2026; nearest ₹ |
| NSE transaction | 0.03553% of total premium | Indicative rate; reconcile contract note |
| SEBI | 0.0001% total premium | Approximation |
| Stamp duty | 0.003% of buy premium | Approximation; nearest ₹ |
| GST | 18% of brokerage + exchange + SEBI | Other GST-bearing charges may exist |

The page explicitly warns that clearing/IPFT/other charges, expiry
exercise, physical delivery, rounding, partial order fills, and actual
broker contract notes can change the result. Historical observed books
are never described as contemporaneously available broker prices.

At a ₹250 premium and 40–50 bps bid/ask width, even one lot of 30
contracts yields only ₹30–₹37.50 of *possible gross* passive capture
versus ₹40 brokerage across two executed orders (before taxes). A
two-sided passive fill is NOT observed, and a wide spread might indicate
illiquidity or severe adverse selection, not free income.

Official reference:
- https://dhan.co/pricing/
- https://www.nseindia.in/static/products-services/equity-derivatives-securities-transaction-tax

## Verification / remaining research

Offline acceptance: \`python -m unittest tests.test_liquidity_spreads -v\`
plus all workstation regressions, Vite TypeScript compilation and
V2 Playwright Chromium browser navigation. CI fixtures are marked
synthetic, not Dhan historical certification.

After the user safely ends a running NSE recording session, update main
and restart via \`bash run.sh\`. Open Trading → Liquidity & Spreads.
During market hours examine true source freshness; after market close
select the IST date of an existing recording and inspect original books.

To claim profitable market making, a separate future study (Issue #93)
still needs actual or conservatively simulated *queue-aware* fills,
order latency, cancellation/replace events, adverse selection,
selection bias controls, independent test periods and fully reconciled
fees. **This module does not claim profitable trades.**


## Automatic spread P&L scanner — Zerodha or Dhan, all saved contracts

**Live Spread Monitor → Spread P&L Opportunity Scanner** automatically
scans the latest **original saved 20-level Dhan book for each contract on
the chosen IST date**, not just the 200 currently subscribed contracts.
Existing rotating source books are included. **The wider 2,850 original
Quote/OI subscriptions do not all provide bid/ask depth**; a contract
without an original valid 20-level book is *not* assigned a synthetic
spread or profitable mark.

It tests each quantity from **1 through 10 lots**, based on the contract's
source-verified lot size, one hypothetical buy and sell order per side
(or a configurable count), and a configurable **long-option premium**
budget (default ₹50,000). Only lot sizes affordable with buy-side cash
cost and supported by both sides of the original observed top-book and
20-level total depth qualify for the sorted stress-upper-bound column.
Every tested lot (including over-budget or insufficient-depth scenarios)
appears in the expanded **All lots** receipt ledger.

### Sorting, filters and colors

- Rank by **passive two-fill upper bound after stress**, optimistic
  fee-adjusted upper bound, immediate marketable buy/ask-and-sell/bid net,
  quoted spread in bps, required buy capital, observation age or strike.
- Show **positive hypothetical**, **negative hypothetical**, blocked
  budget/real-depth, or all contracts. CE/PE, expiry, search and original
  IST date filters are shared with the parent Liquidity page.
- Rows marked green represent *positive only if both passive limit
  orders fill at their best quoted prices*. There is no actual order or
  queue position, and no measured profit. Red marks modeled negative
  net under the chosen stress, not an observed losing trade.
- The ledger shows the **hypothetical cash debit after buying**, **cash
  remaining**, **hypothetical sell credit after taxes**, and **ending
  cash after selling**. It also shows the alternative immediately
  marketable roundtrip net against the same source book. Rows are
  separate counterfactuals, not sequentially compounded executions.
- Refresh the scanner manually or it checks every 60 seconds while
  the tab is visible. Reads only from existing local SQLite storage;
  no extra Dhan WebSocket, no API calls to Zerodha, and no orders.

### Zerodha charges and why "exact" requires a contract note

Available profiles:
- **Zerodha regular individual account**: ₹20 brokerage per executed
  option order.
- **Zerodha debit-balance/collateral-shortfall special case**:
  ₹40 brokerage per executed option order when the documented
  conditions apply.
- **Dhan regular retail**: ₹20 brokerage per executed F&O order.

These are applied with NSE option transaction charges of **0.03553%**
on premium, SEBI turnover charges **₹10/crore**, 18% GST on brokerage,
SEBI and exchange charges, buy-side stamp duty **0.003%**, and
option-sale STT **0.15% on premium** effective 1 April 2026.
Sell-side STT and buy-side stamp duty are assigned to the correct
transaction leg, with rounding reconciled to the previous total
fee engine. **Actual per-trade charges may differ** due to customer
tariff/segment, rounding over aggregated orders, executed order counts,
special balances, exchange/clearing/IPFT charges, partial fills,
exercise/physical settlement and broker adjustments. Actual fills,
price, quantity and **your own Zerodha contract notes** are needed for
exact debits, credits and realized P&L.

No Zerodha login or holdings access is required for the tariff-only
profile. The trading data source remains exclusively original Dhan.

Current official published references:
- Zerodha tariff: https://zerodha.com/charges/
- Zerodha special ₹40 scenario: https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/what-is-the-brokerage-at-zerodha-for-equity
- NSE post-2026 STT: https://www.nseindia.in/static/products-services/equity-derivatives-securities-transaction-tax
- Dhan fees: https://dhan.co/pricing/

### Backend acceptance

Read-only endpoint:
\`GET /api/trading-cockpit/liquidity/scan?day=2026-11-23&broker_profile=zerodha&capital_inr=50000&max_lots=10&executed_orders_per_side=1&adverse_move_bps=25\`.

The scanner runs one bounded daily SQLite query, checks original Dhan
packet-pair SHA integrity and independently revalidates 20-level
bid/ask ordering and quantities. It will evaluate at most 3,000
original saved source IDs per scan and reports any cap. It refuses
unverifiable books and never guesses a missing contract's bid or ask.
The formula is a *source-book scenario*, not an out-of-sample execution
backtest, risk-adjusted expected value, or advice to initiate a trade.
