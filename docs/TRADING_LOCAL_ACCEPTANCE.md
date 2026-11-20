# Trading Cockpit — Local acceptance in five actions

This is the **real Dhan acceptance checklist** for the read-only BANKNIFTY
research workstation. The UI itself contains the same instructions under
**Trading Cockpit → Connections → Check my trading system**. Run all checks
using the local machine that holds the ignored `.env` credentials and Dhan
original source database. Do not upload a broker token or client ID.

## Start the latest workstation

From the existing local checkout:

```bash
cd ~/Desktop/codes/quantlab
git switch main
git pull --ff-only origin main
bash scripts/run_workstation.sh
```

Open `http://127.0.0.1:5173` on the **same machine**. Do not expose the
FastAPI server over a public tunnel or share the local Dhan environment.

## Step 1 — Dhan, historical spot and option contract IDs

Go to **Trading Cockpit → Connections → Check my trading system → Run
local checks**. This invokes one local read-only report and the existing
Dhan profile/token verification endpoint (the latter contacts Dhan).

Confirm:
- **Dhan token valid**, historical **Data API active**, client ID configured.
  A connected historical Data API does **not** prove 20-level entitlement.
- **BANKNIFTY one-minute spot ready**. If not, use the existing **Get missing
  index spot candles** action in Connections.
- **CE and PE Dhan master IDs fresh**. If not, refresh the official Dhan
  instrument master in Data Library, or arm the recorder: it can refresh
  the original official master before subscribing.

**Pass** means locally verified evidence; **Waiting** means data cannot be
proved from the current market window. Missing original market observations
must never be replaced with guessed values.

## Step 2 — Arm the automatic genuine 20-level recorder

Select **Live Trading → BANKNIFTY option chain & 20-level depth**.

Defaults: ₹300 desired option LTP, ±₹75 tolerance, 2 CE and 2 PE, 3 lots
and one saved 20-level book every 3 seconds per contract. You can adjust
these before arming. Explicitly check the consent box and click
**Arm automatic 20-level recording**.

During a **regular NSE trading session 09:15–15:30 IST**, leave the local
QuantLab backend running. If your time zone is different, use the IST clock
shown in Trading Cockpit. The collector does not record overnight and
does not know holidays or special sessions absent original packets.

A successful active collection must show ALL of:
1. The recorder is armed and has **verified NSE_FNO CE and PE IDs**.
2. At least one contract reports **fresh** source packets (not just
   `connected`).
3. Bid and ask each have **20 real source levels**.
4. **Observed source packet pairs** and **books stored** increase.
5. A 3-lot displayed-book VWAP is available **only if** the original 20
   levels show sufficient quantity for that contract's current lot size.

If armed but `Connected · no fresh depth packets`, check Dhan full-market-
depth entitlement separately, verify the correct option IDs, and inspect
the Dhan connection. The 1-minute Data API plan may be active while full
depth is unavailable. The UI does not authorize any trade or order.

## Step 3 — Verify saved original packet evidence

Select **Market Replay → Recorded 20-level books**. Confirm both CE and PE
source books, timestamps, 20 bid/ask levels, contract-specific spread,
imbalance, and the illustrative 3-lot order-book prices.

Then return to **Connections → Run local checks**. Confirm
`Saved original 20-level evidence` shows:
- A positive count of locally persisted automatic book samples.
- Nonzero **verified CE** and **verified PE** counts in the recent sample.
- No corrupt/missing sampled original book SHA-256 receipts.

The integrity check is **read-only** and inspects the latest 200 records;
it is not a full audit of every stored record. A sample from an earlier
market session proves historical receipt, **not live entitlement today**.

## Step 4 — Resolve historical CE/PE zero flips

Open **Options Backtest**, choose BANKNIFTY original index history and
the default **Flip CE ↔ PE on opposite signal** rule. Keep the preferred
₹300 premium and three lots. Click **Run options backtest**.

Inspect the "Why aren't all signals becoming options trades?" panel:
- **Actual UP↔DOWN changes** versus repeated same-side one-minute labels.
- **Option entry availability** around ₹300 at the signal and following OPEN.
- **Opposite-signal exits / same-open re-entry attempts / completed flips**.
- **Rejection reasons**, especially missing nearby options, insufficient
  capital, missing minute at entry, and incomplete exact-contract path.

Zero completed flips with zero opposite exits is NOT the same as an exit
where a PE/CE re-entry was rejected. A backtest may score few complete
positions despite many one-minute signals. All P&L uses assumed fills and
costs, not verified Dhan broker executions.

Click **Download safe backtest diagnostic**. It provides aggregation,
coverage, policy assumptions, rejection counts and rule comparisons.
It does NOT include raw market quotes or broker account details.

## Step 5 — Share two safe reports, then expand the study

In Connections, click **Download safe report**. You will have:

- `quantlab-trading-acceptance-safe.json`
- `quantlab-banknifty-options-safe-diagnostics.json`

These are the **two files** to attach to the ChatGPT QuantLab conversation
for analysis. Do NOT share your Dhan token, password, client ID, local
`.env` or captured broker network logs with credentials.

The existing options backtest has a bounded recent 1-minute index window.
For learning research, expand original BANKNIFTY + specific option-contract
coverage across more **independent sessions and market regimes** before
training an agent. A preliminary 30-session threshold and a broader
250-session research-planning threshold in the audit are *heuristics*,
not statistical certification. A finite historical OHLC candle database
does not reconstruct older historical 20-level bids/asks.

## What is implemented vs still outstanding

| Capability | Software | Needs Dhan/local observation |
| --- | --- | --- |
| Dhan 1-minute index source and expired/active option candles | Present | Confirm correct original dates, lot assumptions, provider entitlement |
| Automatic CE/PE 20-level recorder | Present | Verify real paired full-depth packets and stored CE+PE |
| Safe one-click local readiness and SHA sample | Present | Run on actual local source database |
| Multi-exit historical options simulator and flip reasons | Present | Rerun latest backtest and inspect observed/unscored event counts |
| Supervised CE/PE trade-or-skip evaluation | Not implemented | Expanded genuine option history and chronological holdouts |
| Options-specific offline RL training and evaluation | Not implemented | Much more source coverage, action masks, credible costs |
| Live broker order routing | **Disabled** | No live order test or automatic trade authorized |

The original market library is `dhan_shared`; no separate parallel
market-data dataset or remote account copy is required by these checks.
