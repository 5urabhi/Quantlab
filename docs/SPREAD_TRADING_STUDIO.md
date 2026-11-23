# QuantLab Spread Trading Studio — automatic research workflow

## Two distinct engines

Open **Trading → Liquidity & Spreads**. The workspace now includes:

- **Live Spread Monitor (Bid–Ask Capture)**: automatically inspect source-verified quotes, test lot sizes under your available premium budget, estimate expenses and failed-exit losses, screen and sort research candidates. Opening a candidate starts the execution-cost simulator automatically.
- **Multi-Leg Option Spreads**: automatically construct defined-risk verticals, iron condors and butterflies from original saved Dhan books. Four submodules: Auto Discover, Build & Modify, Payoff & Execution, Research Notebook.
- Existing **Execution Simulator**, **Historical Spread Analysis** and **Spread Strategy Lab** remain available for bid–ask capture research.

This keeps the same Dhan shared market library and recorded original 20-level bid/ask evidence. The option-wide Quote/OI subscriptions are broader than the subset with source-validated 20-level books. No LTP-derived pseudo-books are accepted.

## Bid–ask capture workflow

The liquidity provider attempts a passive buy at a contract's bid followed by a passive sell at its ask. Neither is guaranteed to fill.

The scanner automatically evaluates each validated source option and 1–10 lot sizes. The new research-priority gate requires an exact original-book ID, lot-size verification, budget/depth sufficiency, a receipt age of at most 60 seconds, an unexpired contract, a positive stressed *conditional two-fill upper bound*, and a modeled break-even **conditional sell-fill hurdle at most 75%**. The threshold is a heuristic filter, NOT an actual sell-fill probability.

Ranking favors a lower hurdle, higher stressed *conditional* net per rupee of entry capital and less extreme spread width. Archived/stale source rows remain visible but are not labeled as fresh. Separate columns show the immediate marketable loss, conditional passive bound, stressed bound, failed-exit forced-liquidation loss and break-even sell-fill hurdle. Actual queue/fill data remain unknown.

## Multi-leg auto discovery

The engine constructs **six** equal-lot, same-expiry, defined-risk structures.

| Structure | Ordered legs, all from original Dhan saved books |
| --- | --- |
| Bull call debit | Buy lower CE; sell higher CE |
| Bear put debit | Buy higher PE; sell lower PE |
| Bull put credit | Buy lower PE hedge; sell higher PE |
| Bear call credit | Buy higher CE hedge; sell lower CE |
| Iron condor | Buy low PE; sell higher PE; sell lower CE; buy high CE |
| Iron butterfly | Buy low PE; sell central PE; sell central CE (same central strike); buy high CE |

Automatic discovery rejects incompatible expiry, source-verified lot size, structure ordering, insufficient 20-level depth, mismatched quote timestamps (default maximum skew 10 seconds), risk proxy over budget or nonpositive maximum terminal payoff after entry fees.

No manual contract selection is necessary for the automatic list. The optional exact-leg builder validates every leg server-side. Sort by research priority, max theoretical payoff, terminal reward/risk, smallest maximum loss, immediate crossing costs and quote synchronization. Multi-leg notebook data are browser-local research snapshots, not paper fills; it can export JSON.

## Mathematical and fee definitions

For each marketable illustrative **BUY**, the entry price walks recorded ask levels. For each **SELL**, entry walks recorded bids. Immediate unwind crosses the opposite sides of the same saved book and includes estimated entry and exit fees. Sufficient recorded 20-level quantity is mandatory.

Terminal payoff = signed long/short option intrinsic values × lot units + signed entry premium cashflow − estimated entry transaction fees. Maximum gain/loss are evaluated at piecewise-linear strike knots and extremes, and the chart interpolates these exact payoff segments. This is a **theoretical terminal** payoff, not a prediction or broker's actual settlement. Exercise, expiry settlement, overnight costs and some taxes can change cash results.

Fees are the existing Dhan/Zerodha transaction cost schedule. For a standard single order per leg, 2 legs incur two option-order brokerage charges and 4 legs incur four charges; tax and exchange fees are separately calculated. Actual partial fills, customer-specific tariffs, order counts and contract-note rounding can differ.

Short-option and credit structures require separate Zerodha broker margin verification. **Maximum terminal loss is only a risk-capital proxy**, not initial or final SPAN/basket margin. Even if the risk proxy fits the budget, a multi-leg trade may not be executable. The UI always marks broker margin as UNVERIFIED and no order is placed.

The research score is a descriptive structural heuristic, NOT measured win probability, calibrated expected profit, Sharpe or executable liquidity.

## Source integrity / execution restrictions

- Original saved Dhan 20-level packets with SHA pairing and master-verified lot size only.
- Multi-leg quote-time skew is bounded; on older recorded dates every result is historical reference, not a live executable quote.
- No broker orders, order acknowledgements, fills, cancellations, queue position, bid/ask future price prediction or realized P&L are asserted.
- No implied zero slippage or atomic simultaneous order placement. Zerodha basket orders are placed sequentially and required margin can differ from final margin.
- No automatic paper fills. A saved browser notebook observation must not be confused with a paper trade.

Official broker references:
- https://support.zerodha.com/category/trading-and-markets/charts-and-orders/basket-order/articles/final-margin-calculated-in-options-basket-orders
- https://support.zerodha.com/category/trading-and-markets/charts-and-orders/basket-order/articles/kite-basket-orders
- https://zerodha.com/margin-calculator/SPAN/

## Acceptance and scope of work

After merging and pulling the branch:

    python -m unittest tests.test_option_spread_studio tests.test_liquidity_spreads -v
    npm run build

Run repository-wide Python and browser CI as well.

To progress from research ranking toward actual profitability evaluation, collect order acknowledgments, cancellations, fills, passive queue estimates, partial-fill events, broker basket margin responses and time-synchronized historical replay, then measure out-of-sample execution P&L. Do not label a large saved spread as guaranteed or expected income.
