# Nov 23 2026: QuantLab Dhan live source evidence and quality fixes

## Evidence from local real-session screenshots (10:38 AM IST)
Screenshots of Settings → Automatic Recording show:
- **2,850 current BANKNIFTY option master IDs** and **2,850 requested Quote/OI subscriptions**. Only **380 original option IDs** had produced a valid observed trade price in the in-process session; 380 also received valid price evidence in the last 60 seconds. A subscription request is **not** proof the vendor accepted every security or that a silent security traded.
- Original Quote and OI packet counts: **23,601 / 11,298**; **17,512** original events stored; broad-stream dropped/rejected counters **0 / 0**. The difference between received packets and stored events is not inherently data loss: repeated identical observations are deduplicated and stale source last-trade timestamps are excluded.
- Deep books: **200/200** source-selected instruments; per-socket recent paired books **50/50, 50/50, 48/50, 50/50**; about **198** contracts with current accepted depth and **10** additional contracts promoted for observed activity.
- 20-level parser: **479** generic rejected binary frames and **4** rejected decoded bid/ask pairs. Neither proves 479 genuine tradable market updates were lost: the old counter did not distinguish control messages, unexpected response codes and malformed data. It also does not certify that all 479 were harmless.
- Complete Dhan option-chain snapshots covered **6/6** source-reported expiries. These are independently received REST snapshots, not replacements for missing original Quote or 20-depth packets.

## Source code defects confirmed
1. `move_60s_pct` and `move_5m_pct` both used the first available print within a short active session. If only 8 seconds of source trade history were present, the UI mislabeled that same 8-second price movement under both time horizons.
2. The five-minute source-anchor pruning discarded all observations older than the cutoff, preventing proper 300-second comparisons after enough time elapsed.
3. Unfiltered `score` ranked low-premium contracts (e.g. ₹0.95, ₹1.95) highly after tiny absolute changes, and the depth selector could therefore promote them ahead of the intended ₹99→₹500 research case without a separate market-activity screen.
4. Only aggregate Quote/OI counts were visible; the observed/unobserved distribution across the six expiries could not be assessed.
5. Every original 20-depth parsing exception incremented the same opaque rejected-frame counter, even for documented Dhan disconnect/control responses.

## Changes made
- All original Dhan contracts remain subscribed and saved within existing source and storage limits. **No recording filter** is added. Instead, research returns short-span `observed_change_pct` and `observed_span_seconds`; a 60-second or five-minute percent return appears **only after an original source-trade observation can anchor the actual horizon**. Incomplete windows are represented as `null`, never as invented returns.
- Display all observed movers, with **source-activity-screened contracts first**. Deeper-book promotion separately requires a recent source-observed movement, current premium ₹25–₹2,000, original cumulative-volume increase ≥100 units, and distinct trade timestamps. These rules are **not** proofs of liquidity, future profitability, spread quality, or executable fills; they only control the scarce 20-level prioritization slots.
- Add per-expiry subscribed ID count, any Quote observed, Quote seen in last 60 seconds, any OI, OI-only, and no-price-yet counters. Lack of a quote can mean no trade occurred; further investigation is necessary before attributing it to subscription failure.
- Break down Dhan depth parser rejection counts into source disconnect/control codes, unsupported feed codes, truncated/incorrect packet lengths, and invalid headers/levels. These are safe counter categories derived from the decoder; raw vendor payloads and tokens are never logged. The underlying strict source packet and book validation is unchanged.
- The original 479 rejected frames were observed before this categorization existed. They cannot be retroactively classified without retaining their raw evidence; do not infer their exact causes.

## Next real market acceptance
After this PR is merged and an existing capture is safely stopped, update `main` and start `bash run.sh`. In the next live session inspect the new **Original price and OI coverage by expiry** table and the reason-specific depth parser counters. For option price movers inspect their **Observed move / Trade span** versus strictly measured **60s / 5m** returns. Confirm no penny-option contract with insufficient source volume wins the limited 20-level depth promotion slots. Confirm a real original ₹99→₹500 case remains observable and eligible after adequate evidence.

Offline tests use synthetic packet fixtures. They cannot certify Dhan connection acknowledgments, continuous coverage of all 2,850 contracts, or trading execution.

## Broker packet delivery versus last-trade freshness

The initial 380/2,850 count came from contracts with a **validated recent
Dhan last-trade timestamp**, not a count of every contract for which a
source Quote packet arrived. In particular, a far-expiry option may be
correctly subscribed and Dhan can send a Quote message carrying a last
trade from several hours earlier. Treating that as a trade at the *receive*
time would fabricate a market event, while reporting that there was no
packet at all would also be inaccurate.

The recorder now tracks `last_quote_packet_received_utc` in **volatile
source-delivery diagnostics** separately from `quote_received_utc` used
for accepted live-trade activity and saved price histories. Per-expiry
fields include `received_quote_packet_ids`, `with_any_quote` (accepted
last trade), `stale_quote_packet_only`, and
`never_received_quote_packet`. These fields are not substitutions for
exchange acknowledgments or genuine live prints. Stale last trades are
still excluded from false fresh-trade/momentum claims and are not inserted
as if they traded at the current receive timestamp.

This enhancement helps distinguish an illiquid but transmitting option
from a contract that has never delivered even one original Quote packet.
