# Dhan 20-level original receipt diagnostics

## Why this is needed
During a November 23 BANKNIFTY session the **Automatic Recording** page reported
200 subscribed depth IDs, four healthy WebSockets, 692 original bid/ask pairs,
141 saved books, and 68 contracts with saved books. However, the eight
fixed *nearest + rotating* example cards still said **Waiting for an
original bid+ask 20-level packet**. This is not enough evidence of a
software failure or a missing provider entitlement: the aggregate source
books may have been received for other instruments, while the eight
example contracts genuinely received no valid packets.

The recorder already captured real packets separately from sampled DB writes,
but the status API discarded its contract-level receipt timestamps and only
exposed the latest **saved** book for each displayed ID. Four connected
WebSockets did not mean all 200 contracts streamed valid books.

## New diagnostics
- The existing Dhan 20-level decoder reports only decoded original
  **bid/ask side presence**, invalid binary-frame counts, out-of-window
  pair attempts and validation-rejected book counts. These counters are
  metadata only. They never relax the exact security ID, strict one-second
  pairing threshold, original packet hash, genuine book checks, or storage
  safety limits.
- Each selected contract now has a bounded status: `bid_only`,
  `ask_only`, `bid_ask_seen_no_valid_pair`,
  `valid_pair_not_yet_saved`, `valid_book_saved`,
  `previously_saved_feed_quiet`, or `no_decoded_depth_yet`.
  API output exposes ages and labels, **not** raw half packets,
  rejected book prices, auth tokens, or unselected historical securities.
- The four socket panels each report connected state, subscribed
  contracts, and distinct instruments with original bid, ask and
  validated paired books in the last 60 seconds. The classification is
  distinct from each socket's TCP/WebSocket connection status.
- The UI offers **Nearest contracts**, **Actually saved**, and
  **Rotating depth** inspection views. With real saved books present,
  **Actually saved** displays the newest existing stored books instead
  of eight unrelated near-ATM contracts stuck on the same generic text.
- Diagnostics reset or prune on a genuinely new recording session and
  contract rotation. Original stored market receipts remain unchanged.

## No change to the actual Dhan capture
Only observability and browser selection are adjusted. The background
collector still uses **120 continuous + 80 rotating** source-verified
BANKNIFTY contracts, 200 concurrent depth subscriptions across four
sockets, and strict one-second bid/ask pairing. It does not place orders,
download previous depth, assert source-entitlement completeness, or alter
the stored user consent state.

## How to verify on the research machine
After the PR is merged, prefer updating the local checkout only when it
will not interrupt an important active NSE session:

```bash
cd ~/Desktop/codes/quantlab
git pull --ff-only origin main
bash run.sh
```

Open **Settings → Automatic Recording**, wait for live authenticated NSE
packet flow, and check **Original 20-level delivery by socket**. Select
**Actually saved** to inspect genuine stored books. Select **Nearest
contracts** to see whether each missing ATM instrument has *no decoded
side*, *only one side*, *both sides but invalid pair*, or *a valid pair
awaiting sampling*. Pair acceptance and original packet integrity must
not be inferred from connection count alone.

The earlier deferred 58/200 stored book integrity failures remain
separately tracked in Issue #84. This change does **not** repair those
old receipts or certify all 200 contracts as actively streaming.

## Offline verification
```bash
python -m unittest discover -s tests -p 'test_dhan_receipt_observability.py' -v
python -m unittest discover -s tests -p 'test_wide_option_depth.py' -v
npm run build
```

The full GitHub Python and Chromium workflows are also required. Offline
tests use synthetic protocol fixtures and cannot prove live Dhan coverage.
