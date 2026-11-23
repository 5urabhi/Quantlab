# Dhan 20-level stacked-WebSocket message bound correction (Nov 23, 2026)

## Exact source-backed defect

Dhan v2's 20-level depth WebSocket supports **50 instrument security IDs per
connection**, and each selected security sends a separate 332-byte bid and
332-byte ask packet. Its official Full Market Depth documentation states
these half-packets are **stacked together in a single WebSocket message**.

- Single original 20-level half-book: 12-byte header + 20 × 16-byte
  level entries = **332 bytes**.
- 50 subscribed instruments × 2 sides = **100 half-packets**.
- Largest fully packed documented 50-ID message:
  **50 × 2 × 332 = 33,200 bytes**.

Before this fix, `market_depth.packet_stream(blob,20)` rejected any
WebSocket message exceeding `332 × 50 = 16,600 bytes`. A legitimate full
50-contract bid+ask message could therefore be discarded **in its
entirety** before reaching the strict per-security pairing and original
order-book checks.

The user's live screenshot at approximately **11:04 IST, November 23**
reported 200/200 depth subscriptions across four connected sockets but
only **48/50, 50/50, 29/50, 12/50** securities with a valid pair in the
previous 60s, and **2,027 frames** in the combined
`truncated_or_wrong_size_frames` error bucket.

This cutoff is a confirmed source-code bug and a plausible contributor
to those rejections. **The screenshots alone cannot prove what fraction
of the prior 2,027 frames exceeded 16,600 bytes**; payload lengths and raw
evidence were not retained, so do not retroactively claim all were valid.

Official provider reference:
https://dhanhq.co/docs/v2/full-market-depth/

## Minimal patch and safety properties

- For **20-depth only**, the safe whole-WebSocket-message bound becomes
  exactly `332 × 100 = 33,200 bytes` (100 Dhan half-packets). The
  underlying Dhan connection subscription remains **50 instruments**,
  not 100; the fifth account socket stays assigned to the Quote/OI feed.
- The independent **200-level** packet parser keeps its existing bound.
- Every individual packet still requires: original 12-byte header,
  Dhan feed response code 41/51, valid exchange and security ID,
  exactly 20 source levels per half packet, correct packet byte size,
  finite/ordered/non-crossed prices, and strict same-ID bid/ask pairing
  inside one second.
- The code does not create historical 20-level books for gaps, enable
  additional subscriptions, modify broker orders, or change saved
  source-market evidence.
- Message stacks exceeding the **old 16,600-byte cutoff** increment
  `valid_depth_stacks_above_old_cutoff` **only if one or more books pass
  strict original bid/ask validation**. The companion
  `valid_book_pairs_above_old_cutoff` counts exactly how many genuine
  validated book pairs those frames delivered. This makes the next live
  session's decoder improvement measurable without exposing vendor
  packets or implying malformed data is usable.
- Decoding errors caused by messages above the **new actual** 100-packet
  limit now increment `oversized_depth_stack_frames` instead of being
  conflated with genuinely truncated/wrong-size packets.
- Offline regression constructs **exactly 50 different verified
  security IDs**, each with one original-binary-shaped bid and ask.
  It verifies all 50 original 20-level books are accepted, and 101
  half-packets remain rejected. These are synthetic protocol fixtures,
  not proof of actual Dhan provider entitlement.

## Local live acceptance (do not interrupt active recording)

When the current NSE session is safely finished, pull the merged main
branch and restart QuantLab. In the *next* active market session compare:

1. Number of 20-level sockets connected and 200/200 original Dhan IDs.
2. Each socket's **distinct source-valid books in 60 seconds** (target
   as many of its 50 IDs as Dhan actually updates).
3. **Oversized depth messages** versus **malformed/truncated packets**,
   source bid/ask pairing rejects and individual source-book availability.
4. Original price and OI full-universe feed, persisted receipts, actual
   observed trade timestamps, SQLite disk growth, and clean shutdown.
5. Do not equate 4/4 connected sockets to 200/200 actually receiving
   valid books. Previously rejected source messages cannot be restored
   without original raw packets. No interpolated history is added.

This patch is strictly decoder/diagnostic correctness and does not
override the unresolved older raw-market-depth integrity failures.
