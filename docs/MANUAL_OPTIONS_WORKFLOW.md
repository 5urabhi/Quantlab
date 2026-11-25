# Manual options workflow

Path: **Trading → Option Chain → Advanced Analytics → Manual trading workflow**.
The existing Overview, Greeks, Volatility, OI, Liquidity and Trade Calculator
are unchanged in purpose. No broker orders, account trading access or new
market-data WebSocket subscriptions.

## Across Expiries

Uses the latest integrity-checked original saved Dhan chain for up to 12
nearest unexpired expiries, on the same applied scenario and budget. Rows
older than 30 seconds or outside the normal weekday market window are
not ranked as current. Every expiry keeps its independent local receipt
timestamp. Far expiry capture intervals are intentionally slower, so
the coverage table may show delayed or absent expiries; the comparison
does not pretend all expiries were observed simultaneously or continuously.
The scan returns at most 100 ranked rows and can inspect the exact contract
in the shared calculator. No extra chain requests for the comparison.

## Positions & Exits

Prepare a manual journal entry from the existing calculator **after** your
actual broker fill. The journal now stores the exact verified Dhan ID,
expiry, strike, lot size and indicative fee profile in an additive
metadata table in the existing manual journal database. The server
matches the exact symbol/side/quantity to the fresh official master.
Old manual trades are retained unchanged; explicitly link an open legacy
record to the exact ID if it still exists in the master.

Marks are based on the newest eligible saved original 20-level bid
walk (8 seconds) or full-size chain top bid (30 seconds), not LTP.
Missing/insufficient size is unavailable, not a zero-profit trade.
No mark after the regular session or expiry. All P&L is estimated using
user-entered entry prices and the existing indicative round-trip broker
cost model. Actual fill/fee values are not independently authenticated.
Close a journal record only by entering the actual exit premium and
combined actual charges; this never sends a broker order.

The exit calculator inverts the fee model for break-even, configurable
profit target and loss threshold as percentages of original premium
notional. Default 5% / 2.5% are examples, not advice. A further BSM
inversion estimates the underlying move needed under the selected
holding minutes, IV shock, rate, dividend and slippage assumptions,
within ±20% of spot and before expiry. It is not an executable stop
or a prediction. Greek coverage is explicitly reported; aggregate
sensitivities include only recent model receipts, not synchronized fills.

## Contract Alerts

Create a persistent rule for a current verified exact identity. Choose
one or more of max ask, max spread, absolute Delta range, model IV
range, bid thresholds, and minimum displayed units on both sides.
All supplied conditions must match. Blank conditions are ignored.
Model-IV/Delta alert calculations use the stated fixed 6.5% rate and
0% dividend yield; they need not equal a user's customized scenario.
The local monitoring worker evaluates latest *new* saved chain receipts
every 10 seconds while the backend runs. It logs an event when a rule
first matches or returns to matching after a nonmatching receipt.
Missing metrics are not treated as false or zero; old receipts before
rule creation cannot fire it. Expired rules stop automatically.

The rule and event history persist in the manual journal SQLite file.
Disabling rules preserves their history. In-app status and optional
browser notifications are available while Advanced Analytics is open
and browser permission is granted. The backend can continue logging
events while the browser is closed, as long as QuantLab and its
authorized data collectors are running. No email/SMS, broker order,
continuous exchange trigger or guarantee of catching brief conditions.

## Ranking Review

Enable **automatic shortlist recording** explicitly. Future selected
expiry and cross-expiry analytics scans record up to two leading calls
and two leading puts. There is no new ranking when the user is not
scanning; pending evaluations still run while QuantLab runs. Each
decision is immutable and deduplicated by scope, exact ID, source
receipt and scenario; it cannot acquire a later-selected control.
When available, each leading candidate is paired with a distinct,
lower-scoring same-side, same-expiry, same evidence tier, same-unit
candidate with decision ask within 25%. The match is chosen before
any future observations, without looking at outcomes.

- Record decision time, observed source ask, exact terms, ranking
  assumptions, evidence tier, quantity and cohort.
- Entry proxy = first subsequently saved chain receipt at/after
  decision within 60 seconds, requiring a valid full-size ask.
- Exit proxy = first saved chain receipt at/after entry plus the
  registered holding horizon, within 60 seconds, requiring a
  valid full-size bid.
- Wait 15 seconds past an empty window for persistence latency.
  First unusable receipt or missing evidence censors the outcome,
  without searching for a more favorable price. End-of-session
  incompatible windows are not registered.
- Fee-adjusted quote markouts and paired net-return differences are
  descriptive only. Return denominator is entry premium notional.
  Positions overlap, may be censored, are not independent, and no
  actual executions or win probabilities are established.

The worker reads the original market library and stores this compact
audit ledger in the existing manual-trade SQLite database. No historical
market data are deleted or fabricated. The ledger survives a normal
restart and new scans are opt-in; turning off new recording leaves
pending evaluations intact.

## India VIX

The Volatility view requests the documented Dhan v2 marketfeed/ltp
read-only snapshot using a unique NSE INDEX/IDX_I India VIX identity
resolved from the fresh official local instrument master. No guessed
ID or substitute volatility value is accepted. Requests (including
failures after identity resolution) are cached for 60 seconds per
credential/master context. The local receipt is not an exchange
timestamp. If the master, authentication or data plan does not support
the index, display unavailable with the reason. Provider interface:
https://dhanhq.co/docs/v2/market-quote/

## Acceptance

Run offline tests with:

```bash
.venv/bin/python -m unittest discover -s tests -p test_manual_options_workflow.py -v
npm run build
```

Existing Python and Chromium acceptance jobs also run. Synthetic test
fixtures verify logic and UI interactions, not live data or profitability.
Local acceptance requires the user to observe fresh chain receipts,
record a real manual fill, check exact-ID marks, trigger a test alert,
and obtain subsequent forward markouts from actual saved source data.
No dealer-signed gamma exposure is claimed; public OI cannot identify it.
