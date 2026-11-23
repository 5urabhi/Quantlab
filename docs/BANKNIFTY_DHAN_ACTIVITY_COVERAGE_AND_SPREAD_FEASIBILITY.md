# Dhan BANKNIFTY original-data quality and spread-trading feasibility — 22/23 Nov 2026

## Why this changed

The source screenshot's Indian-formatted depth receipt count is **2,07,238
(207,238)**, *not* 2,071,238. With 4,698 accepted original Dhan large-stack
messages, the mean is about 44.1 validated bid/ask books per message. This
is plausible because a Dhan 20-level socket has 50 instrument identities.
The previous interpretation of that UI count as invalid was incorrect.

The recorder now separately computes `depth_counter_audit.consistent` by
checking that original rescued book pairs cannot exceed either
50 × validated-large-messages or the session's observed original pairs.
The check never modifies raw evidence. Saved, deliberately sampled
books remain a different metric from decoded source pairs.

The original price feed includes **all** current master-verified options
(up to Dhan's account/connection limit), while only 200 original 20-level
books can be subscribed at once. Previously, after protecting 120 nearest
contracts, up to 40 high-velocity source-confirmed movers were selected
and all remaining subscriptions rotated among far contracts, many of
which never produced a recent trade or source book.

## Source-first improved 200-slot selection

Exact original fresh quote identities from the Dhan v2 all-option feed now
produce an additional `ranked_active_depth` list:

- Fresh original last-trade receipt within 60 seconds;
- Original trade premium ₹25–₹2,000 and positive observed volume;
- Read-only source-backed rank by last-trade recency, volume change,
  cumulative volume and original traded quantity;
- CE/PE interleaving to reduce a one-sided selection in volatile moves;
- Matching exact same-expiry, official master-verified NSE_FNO identity
  before occupying any detailed 20-level slot.

A moving/active option that is already among the 120 nearest remains in
the core without double-counting another slot.

Selection is bounded by source availability:
- **120 nearest** contracts remain continuously subscribed;
- **up to 40 confirmed high-movement** identities can take slots;
- **up to 60 other actively traded** identities can take remaining slots;
- **at least 20** rotating distant-strike discovery slots remain.

Only the original monitored **nearest expiry** gets 20-level depth;
the broad Quote/OI stream continues recording every listed expiry.
The existing 20-second Dhan chain review and 90-second distant rotation
remain. No new broker sockets, orders, or historical interpolation.

## Read-only source receipt audit

`GET /api/trading-cockpit/option-feed/quality?identity=NSE_FNO%3A62539&day=2026-11-23`

This uses the existing `dhan_shared` database to scan at most 50,000
original saved Quote/OI events for one instrument on one IST calendar
date. Returns first/last local receipt, original last-trade bounds,
number of observed saved Quote minute-bins, longest inter-receipt gap,
counts of gaps >60 and >300 seconds, and scan-cap warning.

**A gap between received quotes is not necessarily missing broker data**
— that contract may simply not have traded. Dhan may also send a Quote
packet repeating a stale last-trade timestamp, which is correctly
distinguished from a genuinely new trade. No synthetic prices are
created and this endpoint never executes an order.

## Bid–ask spread economics: 40–50 **bps** is not ₹40–₹50

In the screenshots the spread is quoted in *basis points relative to
option midpoint*. 40 bps = 0.40%, 50 bps = 0.50%.

Illustrative midpoint ₹250, observed lot size 30:
- At 40 bps, the best bid/ask price difference is ~₹1.00/option.
- At 50 bps, it is ~₹1.25/option.
- Immediate buy-at-ask, sell-at-bid = **gross loss** of one displayed
  spread (₹30–₹37.50 for one lot, ₹90–₹112.50 for three lots).
- Passive buy-at-bid and passive sell-at-ask could, in an
  *optimistic static-quote upper bound*, collect those same gross amounts
  IF both sides fill with no mark-to-market loss or adverse selection.
  This is not executable profit and ignores order queue priority.

Official Dhan retail F&O brokerage is ₹20 **per executed order**;
one two-sided round-trip, one combined order per side, has ₹40 brokerage
and at least ₹7.20 GST on that brokerage. For 2026, NSE's option-sale STT
is 0.15% of the sell premium, approximately ₹11.25 for a 30-unit lot
selling near ₹250 or ₹33.75 for three lots.

Thus an *optimistic cost floor* for a one-lot two-sided round trip
near ₹250 is ₹58.45 (brokerage+GST on brokerage+STT), already more than
the theoretical ₹30–₹37.50 gross spread. With three lots in one executed
order per side, the floor is ₹80.95 versus the ₹90–₹112.50 gross spread,
leaving at most ₹9.05–₹31.55 before NSE exchange charges, statutory
charges other than STT, slippage, adverse selection, partial fills and
unfilled passive orders. These are not validated real P&Ls. Execution
costs depend on account type and actual contract notes.

Sources:
- https://dhan.co/pricing/
- https://www.nseindia.in/static/products-services/equity-derivatives-securities-transaction-tax

### What a fair profitability study needs

Build a distinct **execution feasibility and queue-aware spread-capture
experiment** using consecutive original bid/ask books, marked marketable
vs passive limit-order assumptions, order queue position uncertainty,
partial-fill bounds, cancellation/replace latency, STT and brokerage,
plus spread widening and adverse selection after fills.

Report (i) marketable roundtrip *negative baseline*, (ii) optimistic
passive best-quote upper bound, (iii) queue/slippage stress scenarios,
(iv) net P&L and break-even lot size, (v) selection/latency controls,
and (vi) out-of-sample estimates with confidence bands. Do NOT claim
profitable market making from a spread screenshot.

## Operator acceptance, after live market capture ends

1. Safely stop live collection before updating local running processes.
2. Update merged QuantLab from `main` and launch `bash run.sh`.
3. Confirm all previous source packet counts persist; the automatic
   full-market read-only Quote/OI feed still requests every verified ID.
4. Observe activity slots and rotation slots in the compact dashboard.
   Only actual original recently traded option IDs should be promoted.
   The near-ATM 120 core and 20 discovery slots must remain protected.
5. Expand **Detailed Dhan source and decoder diagnostics** to inspect
   the invariant and original packet/book counts; expand
   **Original price and OI coverage by expiry** as needed.
6. Inspect a stored option in **Recorded price history**; verify the
   new on-demand receipt audit shows actual gaps, not fabricated trades.
7. Do not consider source-rights, missing-tick completeness, fill
   probability, net profitability or live market-maker strategy certified.
