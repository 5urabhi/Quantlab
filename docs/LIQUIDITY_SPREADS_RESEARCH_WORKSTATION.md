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
