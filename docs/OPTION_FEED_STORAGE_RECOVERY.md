# Dhan Option Quote/OI Storage — November 23, 2026 incident and recovery

## Confirmed incident

The user ran a read-only SQLite diagnostic on the local market library:

- Database: `data/dhan/shared_market.sqlite3`
- DB size: **2.341 GB**, free disk space: **278.84 GB**
- **2,000,000** saved Quote/OI events for the NSE session
  (1,958,191 quotes, 41,809 open-interest events)
- Last persisted event at **2026-11-23 07:10:06.552918 UTC**
  (**12:40:06.552918 IST**)
- The old writer was hard-limited to 2,000,000 events/day. It discarded
  additional events after that ceiling, while the WebSocket continued
  reporting `streaming_original_quotes`.
- The live status showed `stored_events=0`, `dropped_events=182911`
  and `queue_depth=0`. `stored_events` is a *process-session*
  counter; the database daily count is the source of truth.

**Source events not saved after the cap cannot be reconstructed.**
Neither Dhan current snapshots nor option candles supply those lost
original trade timestamps and quote packets. Keep the day's historical
gap explicit in all subsequent research and backtests. No fake backfill.

## Correction

`workstation_api/full_option_feed.py` now:

1. **Removes the 2,000,000/day hard ceiling.** The writer keeps
   persisting source-eligible original events for the market session.
   Existing rows and the database file are left untouched. No migration,
   deletion, `VACUUM`, or database replacement is performed.
2. Adds a **filesystem-aware reserve**: protect 3% of the total disk,
   with a floor of **512 MiB** and a ceiling of **10 GiB**; free-space
   checks run no more than once per 10 seconds during writes.
   If capacity is unsafe or unavailable, count and mark drops instead
   of silently claiming complete recording.
3. Retries transient SQLite write contention up to three attempts.
   Persistent errors are reported independently as
   `storage_state=sqlite_storage_write_failure`.
4. Preserves a separate, long-lived storage-health state in the API,
   so a healthy WebSocket cannot overwrite a writer error.
5. Records writer-side missing-event intervals in the append-only
   `data/research_workspace/market_depth/option_feed_storage_gaps.jsonl`.
   The sidecar contains source receipt time bounds/counts, no secrets.
   It only records incidents observed **after this upgrade**.
6. Exposes `storage_daily_events`, `storage_last_saved_received_utc`,
   `storage_daily_limit=null`, `storage_state`,
   `storage_writer_alive`, `storage_gap_detected`,
   `storage_gap_started_utc`, `storage_last_drop_utc`,
   `storage_free_gb`, `storage_reserve_gb`,
   `storage_write_retries` and the gap-ledger path in the existing
   `GET /api/trading-cockpit/option-feed/status` endpoint.
7. Shows that Quote/OI storage health **separately** from depth socket
   connectivity in Trading → Liquidity & Spreads.

A stopped or missing writer is not a successful recording, even when
`connected=true`, `quote_packets` is increasing, and `queue_depth=0`.

### Deployment while preserving ongoing recording

**Prefer a controlled restart after the NSE session.** A restart
necessarily creates a brief live-data gap. Do not replace a running
collector mid-session unless that interruption is acceptable. Before
a restart, verify your working tree is clean and pull `main` after
the PR is merged.

```bash
cd ~/Desktop/codes/quantlab
git pull --ff-only origin main
bash run.sh
```

Once the API is back, run:

```bash
curl -s http://127.0.0.1:8765/api/trading-cockpit/option-feed/status |
  .venv/bin/python -m json.tool
```

**Acceptance:** `storage_state=recording`,
`storage_writer_alive=true`, `storage_daily_events` increasing
beyond **2,000,000** (during market hours with source-eligible packets),
`stored_events>0` for the new process, `dropped_events` not growing,
and `storage_daily_limit=null`. Market inactivity may delay increases;
the quote receipt counter is not itself a trade count.

### Operational limitations and capacity planning

- **Unbounded row count is not unlimited physical storage.** The
  writer now stops persisting before low free disk space and reports
  the gap clearly. It does **not** automatically erase or archive
  original evidence. Use the Data Manager to monitor database growth;
  partitioned/day-level archive and long-term retention policy
  remain future work.
- A full write queue or unresolvable SQLite errors can still lose data.
  The live status and loss counters disclose this. A zero queue depth
  only means the writer **consumed** pending events, not that they
  were saved successfully.
- `ignored_stale_trades` counts Quote packets whose exchange
  last-trade times were stale. They are *not* proof of fresh trades.
  `unchanged_quote_packets` and `unchanged_oi_packets` are
  deliberate de-duplication. They should not be confused with
  `dropped_events`.
- The spread execution-feasibility gate correctly blocks missing
  fresh source-trade activity. Restoring storage removes an
  artificial source-data gap, **but it does not prove any spread
  is profitable** or guarantee every contract trades frequently.

## Testing

```bash
.venv/bin/python -m unittest tests.test_full_option_feed tests.test_spread_execution_gate -v
npm run build
```

The automated GitHub Actions full Python regression and browser tests
must also pass. Test fixtures use local fake Dhan packets; no live orders.
