# Dhan-only continuous BANKNIFTY option universe — original Quote/OI and dynamic depth

## Purpose
BANKNIFTY can move 1–2% intraday. A CE/PE that traded at ₹99 may later trade
at ₹500 without ever being among the 120 nearest ATM contracts subscribed for
20-level books. Complete REST option-chain snapshots alone cannot establish the
intervening traded price path. QuantLab therefore uses a separately authorized
single Dhan v2 **Quote** market-feed WebSocket covering every master-verified
current BANKNIFTY CE/PE contract that fits within the account's real feed limit.

All observations enter the **existing** `dhan_shared` SQLite market library.
The old chain-snapshot and 20-level market-depth recorders are not removed.

## Exactly what each source can prove

| Source | Coverage | Evidence |
| --- | --- | --- |
| Dhan REST chain | All source-returned strikes for each active expiry | Snapshots: price/IV/Greeks/OI/quotes at received times. Not trade-by-trade. |
| Dhan v2 market **Quote** feed | Up to 5,000 master-verified contracts on **one** WebSocket | Original packet-hashed LTP, last-trade timestamp, trade size, cumulative volume, buy/sell totals; asynchronous separately hashed OI packets. Not 5-level or 20-level. |
| Dhan v2 market **Full** feed | Dhan offers five-level depth in another request mode | Not enabled for the all-contract monitor: stronger throughput and storage requirements, separately assess. |
| Dhan 20-level sockets | At most 200 selected instruments simultaneously, four 50-ID sockets | Strict original paired bid/ask 20-level books, with source receipts. |

Official Dhan reference: https://dhanhq.co/docs/v2/live-market-feed/
(5,000 instruments per connection, 100 per subscribe request, code 17 Quote,
response 4 Quote and 5 OI) and
https://dhanhq.co/docs/v2/full-market-depth/
(50 instruments per 20-level socket).

**Subscription is not proof of delivery.** Illiquid contracts may have stale
last-trade timestamps, disconnected feeds have gaps, and Dhan might omit or
delay individual events. This software cannot reconstruct absent packets.

## Source contracts and subscription

1. Read the *same official local Dhan instrument master* used by the 20-level
   recorder. Require freshness, NSE_FNO BANKNIFTY OPTIDX CE/PE type,
   matching current provider expiry, positive strike and lot, unique
   economic contract terms, and an unambiguous original `NSE_FNO:ID`.
2. Create one Dhan v2 read-only Quote socket, group into batches of at most
   100, never request more than 5,000 contracts on one connection.
3. If Dhan lists >5,000, expose the precise **unsubscribed count**. Do not
   advertise complete coverage; prioritize earlier expiries and closest
   original strikes.
4. Avoid opening a sixth connection: an automatic four-socket depth session
   plus the all-contract quote socket uses the five allowed slots. A separate
   manual Trading Cockpit ticker/depth session is mutually exclusive while
   automatic capture is armed.
5. On a current master/expiry change, disconnect the existing quote socket,
   update exact IDs and reconnect. Session disconnections cause genuine
   gaps and never auto-fill missing source packets.

## Separate, explicit opt-in

The all-contract live stream requires an **additional** local consent click
in **Settings → Automatic Recording → Full-universe option price monitor**.
This can be enabled or disabled *without stopping four active 20-level
sockets*. The consent is persisted only to a private 0600 local file in the
existing Dhan recording settings directory. Existing Stop & Disarm disables
all automatic captures. Restart resumes full-universe streaming only if
both the depth recorder and the full-stream consent are still enabled.
Credentials are read from local Dhan configuration; never returned in
status JSON, stored with quote records, or logged.

## Original data storage and safety

New table: `dhan_option_live_events` in `dhan_shared`.
Every accepted source event stores the verified contract identity, local
packet receipt time, original Quote packet's Dhan last-trade UTC (when
present), type (`quote`/`oi`), original parsed price/volume/OI,
packet SHA-256, and capture session ID. All writes use bounded SQLite
batches and a bounded write queue, with an explicit drop counter.

A maximum of 2 million source events per market day is enforced. Capacity
and storage shortfalls are reported instead of silently deleting records.
Consecutive repeated byte-identical quotes and identical OI values are
counted as repeated packets rather than fabricated additional trades.
The monitor is not a broker fill or model-verified continuous time series.

The HTTP endpoints are read-only except the two explicit local consent
actions:

- `GET /api/trading-cockpit/option-feed/status`
- `GET /api/trading-cockpit/option-feed/contracts?offset=0&limit=100`
- `GET /api/trading-cockpit/option-feed/opportunities?limit=25`
- `GET /api/trading-cockpit/option-feed/history?identity=NSE_FNO%3A62539&limit=500`
- `POST /api/trading-cockpit/option-feed/enable` with `{"confirm_live_quote_stream":true}`
- `POST /api/trading-cockpit/option-feed/disable`

## Opportunity detection and 20-level promotion

The in-memory 5-minute original Quote timeline scores price movement
and actual Dhan trade timestamps and volume changes; unchanged or stale
last-trade events cannot fabricate a momentum signal.

A source-confirmed rapid option move can now promote up to **40** genuine
same-expiry contracts into deep-book subscriptions, beside:

- 120 closest master-verified continuous 20-level contracts,
- up to 40 rapidly moving verified contracts,
- the remaining up-to-80 budget rotating among other verified IDs.

With no original movers, 80 contracts remain in the distant-strike rotation
as before. A newly observed high-severity move can trigger promotion on the
next 20-second Dhan-chain review, while smaller changes are grouped until
the next 90-second remote rotation to avoid excessive reconnections.
Ordinary option trades across **all currently listed expiries** continue
to be monitored on the broad Quote socket; the current 20-level
opportunity promotion specifically applies to the nearest expiry.

A momentum score identifies **observed price activity**, not a prediction,
profitable strategy, trading signal to execute, or proof of fill liquidity.

## Acceptance and rollout

CI tests parse original protocol-shaped binary Quote (4) and OI (5) messages,
verify all 874 sample source identities are subscribed using nine batches,
reject malformed/unknown headers, validate the real ₹99→₹500 opportunity,
and confirm original SQLite history has no invented intermediate bars.
Tests also assert independent consent and bounded 200-slot depth promotion.

Then run on the Ubuntu workstation when it will not interrupt live data:

```bash
cd ~/Desktop/codes/quantlab
git pull --ff-only origin main
bash run.sh
```

While Dhan is open, visit **Settings → Automatic Recording**. Ensure
automatic depth remains armed. In **Full-universe option price monitor**,
check separate consent and click **Start all-contract price stream**.

Inspect requested contracts vs contracts with observed fresh prices,
packet count, dropped writes, rejected frames, and original top movers.
Browse contract pages and open saved price history for an individual CE/PE.
Confirm the `opportunity_depth_contracts` count changes only for
genuine master-verified selected IDs.

**Not certified by CI:** actual Dhan token entitlement, live subscription
acceptance by the broker, every contract producing quote packets, exact
remote market timestamp fidelity, realtime latency, depth for every option,
and profit potential. Remaining live source verification should be
tracked under GitHub Issue #84.
