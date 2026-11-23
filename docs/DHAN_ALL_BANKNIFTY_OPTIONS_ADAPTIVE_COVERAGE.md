# Dhan-only BANKNIFTY: all listed options and adaptive 20-level coverage

## Why

The former 20-level collector subscribed to **100 contracts above** and
**100 below** the nearest BANKNIFTY ATM strike (50 real CE+PE strike pairs on
each side), leaving the ATM strike itself unsubscribed. When BANKNIFTY
quickly moved beyond that limited band, new options had **no source 20-level
book history** until the next selection refresh and WebSocket reconnect.

**The problem is the fixed strike selection, not a missing broker account.**
PR #86 (Upstox/extra providers) was closed as out of scope. QuantLab uses
**Dhan only** for this feature.

## Two genuinely different data products

### Complete Dhan REST option chain (all source strikes)

- The existing `auto_option_chain` recorder saves **all CE/PE quotes for
  every original Dhan-reported active expiry**, in the original
  `option_chain_observations` table in `dhan_shared`.
- **No nearest-strike truncation.** The underlying
  `option_chain_live._normalize` walks every strike in the Dhan response.
  This is a REST snapshot, not continuous 20-level history or an exchange
  timestamp.
- Snapshot intervals are now **30 seconds** for nearest expiry,
  **60 seconds** for second nearest, **5 minutes** for next four, and
  **30 minutes** for other active expiries. The existing Dhan 3-second
  request-spacing and cache/snapshot retention limits remain in force.
  Actual interval can be longer during source throttling/reconnects.
- A source-listed strike that later becomes ATM should have historical
  chain snapshots from before that move, **if Dhan actually returned it**.
  Gaps between snapshots are never backfilled with fabricated quotes.

### 20-level depth (up to 200 simultaneous option contracts)

Dhan's official 20-depth WebSocket documentation allows **50 instruments
per socket** and a maximum of **five sockets per account**. QuantLab uses
**four 50-contract sockets** and reserves the remaining connection for the
existing live feed. It is not possible to track all `2,712` or more option
contracts continuously at 20 levels with the existing Dhan limit.

The new Dhan-only recorder:

1. Includes **all original master-verified contracts** in its candidate
   universe for the nearest currently listed expiry, including ATM and
   isolated CE or PE options. No synthetic contracts or forced pairs.
2. Keeps the **120 closest verified option contracts** (by distance from
   actual Dhan-reported BANKNIFTY spot) continuously subscribed while the
   recording socket session is healthy.
3. Uses up to **80 additional 20-level slots** to cycle through remaining
   far-strike contracts. Switches the rotation set every **90 seconds**,
   observing original books only while that contract is actively subscribed.
   Previously saved original books remain immutable.
4. Re-reads the actual Dhan option-chain spot and source contract listing
   every **20 seconds** instead of 75 seconds, and recenters the 120 nearby
   contracts when BANKNIFTY moves. Reconnecting sockets introduces short
   genuine gaps; we do not imply uninterrupted depth during reconnection.
5. Never subscribes unverified security IDs, duplicates, or more than
   **50 per socket / 200 concurrent**. Missing source-provided IDs and a
   spot outside the original listed strike range generate warnings.
6. Uses the existing one SQLite writer and preserved original-packet
   checksum/receipt verification, existing local token and trading-hour gate.
   No new broker connection, account permission, or order endpoint.

## User-visible readiness

Open **Connections → Automatic Recording** or **Trading → 20-Level Order
Book**. The recorder reports:
- Total source-reported CE/PE contracts and genuinely master-verified depth IDs.
- Simultaneous subscribed count (max 200), continuous core vs rotating IDs,
  verified source strike min/max vs active subscribed min/max, and rotation cycle.
- Source-reported strike-range limitations, current WebSocket health,
  last received paired packet, and saved original 20-level book counts.
- Complete-chain recorder's number of active expiries observed, full chain
  quotes per snapshot and source timestamp.

The table still allows browsing all returned current Dhan options in
**Trading → Option Chain**. No Upstox or Zerodha option-chain changes.

## Verify on your Ubuntu machine

After merge:

```bash
cd ~/Desktop/codes/quantlab
git pull --ff-only origin main
bash run.sh
```

If you previously pressed **Stop and disarm**, re-enable automatic recording
from the app with explicit consent. Leaving it disarmed must remain respected.

During NSE regular trading hours, record a period with genuine BANKNIFTY spot
movement. Confirm: 1) actual Dhan full-chain snapshots retain extreme strikes
and listed expiries; 2) the core selection moves when source spot changes;
3) far-strike `rotation_step` and rotation IDs change without false source
quotes; 4) source socket count never exceeds four; 5) original books and
feature receipts reconcile; 6) missing/failed packets and source-history
gaps remain visible.

Run the independent read-only audit:

```bash
bash run.sh verify-saved --dataset dhan_shared
```

The deferred Heston and existing 58/200 stored depth integrity investigation
remains tracked in **Issue #84**, unaffected by this change.

## Offline regression coverage

```bash
python -m unittest discover -s tests -p 'test_full_chain_adaptive_depth.py' -v
python -m unittest discover -s tests -p 'test_wide_option_depth.py' -v
python -m unittest discover -s tests -p 'test_auto_option_chain.py' -v
npm run build
```

CI uses fixtures and can verify logic, not actual Dhan options entitlement,
network response timing, unique live packet availability, storage write rates,
or a historical 20-level book that was never received.
