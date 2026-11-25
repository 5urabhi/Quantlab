# Paper trading and original-depth replay

Open **Trading → Paper Trading**. The dedicated workspace is separate from
the user-entered actual-fill journal, Dhan recorders, and live broker APIs.
No real orders, money transfer, or account trading permission.

## Paper Account & Orders

Create a preserved virtual account (up to ten local research accounts).
Starting cash, premium-exposure cap, concurrent-position cap and cumulative
realized-loss threshold are configurable research assumptions. A BUY reserves
worst-case cash, including estimated entry fees; new BUY orders are rejected
when the configured cash/exposure/position/loss constraints are violated.
SELL may only close held long units. Naked short positions and unverified
margin borrowing are intentionally disabled. Open positions surviving
expiry are unresolved: no fabricated cash settlement.

Each simulated order records its exact current-master contract identity,
strike, expiry, lot size, requested quantity, simulated latency, time in
force, protection price, adverse slippage and displayed-depth participation.
A protected market order is an IOC-style attempt on the first valid later
original 20-level receipt. A resting limit can execute on successive later
contra-side books only when adverse-adjusted prices satisfy its protection.
The depth walk haircuts available quantity and uses whole lots. Identical
book packet pairs cannot provide repeated liquidity to the same account,
identity and direction. Different accounts are separate counterfactuals.
No assumption of passive queue priority, order acknowledgement or exchange
event time. Prices and fees are illustrative, not verified broker rounding.

The local monitor reads already persisted original books every five seconds,
processes at most forty working orders per cycle, and maintains durable
state and a fill ledger. Book windows begin strictly after submission and
simulated latency. Cancellation limits the subsequent evidence window;
eligible earlier books cannot be erased by later cancellation. Wait 15
seconds past the fixed terminal window for persistence latency; late writes
behind the processed receipt cursor are not automatically replayed. Missing
valid books are explicitly unobservable. Partial fills, remaining orders,
expiry and cancellation remain distinct. Existing paper account state
survives normal restarts. No recorder configuration is changed.

Cash and proportional fee-inclusive position cost basis are updated in the
same transaction as fills; brokerage is charged once per simulated order
using cumulative turnover. Marks use a full-size, current original bid
walk (within 8 seconds) less indicative closing costs. Marks are not
hypothetical realized fills, and missing positions prevent a complete
equity value. Per-minute observed equity samples preserve gaps.

## Historical Depth / Spreads

Specify an IST decision time, exact recorded historical identities in
structure order, lots, budget, latency, window, hold time, participation,
slippage and fee profile. The first saved receipt per leg in the fixed
window is used, not the best subsequent price. Exit is requested after
the last entry receipt plus holding time and latency. All legs require
original source identity, matching terms, full displayed quantity and
receipt skew within the configured limit. The six defined-risk structures
reuse the existing spread structure and terminal payoff validator. Research
capital must cover the larger of theoretical terminal loss including
entry fees and gross buy-leg debit. This is **not** actual broker margin.

These are conditional synchronized basket quote markouts. A partially
observable basket is censored, not booked as zero P&L; sequential legging,
margin and forced partial-leg unwind remain unmodeled. No short-position
live paper orders are authorized by the replay. Missing exit evidence
does not imply an exit at the last available quote.

## Rule-Based Replay

EMA crossover, momentum and mean reversion use completed, originally
recorded BANKNIFTY minute bars. A decision cannot predate the minute close
or final receipt. Reset rules across missing minutes, never interpolate.
Supply fixed historical CE and PE identities before running; this does not
retrospectively choose the most profitable strike. FIXED uses the holding
period. FLIP requests close on the opposite signal, then opens the
opposite side only after the observed prior exit if the signal has not
been superseded. If no opposite signal arrives, attempt exit before
regular session close. No overlapping trades or reuse of ambiguous
committed capital; maximum fifty attempts per run. Completed-subset P&L
is distinct from whole-run P&L when execution is unresolved.

The replay and paper engine share displayed-depth walk and indicative
charges, not a trained forecast. Research must still verify actual
source coverage, chronological holdouts and realistic execution. This
does not provide statistical profitability, a calibrated fill probability,
a margin quote, or an actual realized result.

## Validation

```bash
.venv/bin/python -m unittest discover -s tests -p test_paper_execution.py -v
npm run build
```

Tests use synthetic deterministic original-shape books to verify causal
windows, partial fills and deduplication, cash/accounting, risk rejection,
cancellation, basket skew and rule reversal. Chromium acceptance checks
the new navigation and interaction. Local source verification remains
necessary; do not substitute fixtures for actual market observations.
