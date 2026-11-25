# Remaining recorder storage limits and session archive

Removes the fixed 200,000 auto-depth books/day, 2,500 REST chain
snapshots/day and 30,000 individual books/session cutoffs. The existing
Quote/OI 2-million-event cap was removed in PR #99. All original
subscription, per-contract sampling and source validation limits remain.
The shared disk guard protects 3% of filesystem capacity, bounded
512 MiB–10 GiB. It pauses depth/chain ingestion when unsafe and retries
after free space returns. The separate `storage_health` values identify
committed writes, known dropped samples and gap transitions independently
of connectivity. A resumed stream does not imply the missing interval
was recovered. The append-only gap ledger is best effort; counters are
process-local. Queue overflow and transaction commit failure must not
be counted as successfully saved. A source gap cannot be reconstructed.

## Verified day export

After NSE hours, use:

```bash
bash run.sh archive-market --day 2026-11-23
bash run.sh archive-market --day 2026-11-23 --output-dir /path/to/backup
bash run.sh archive-market --verify data/dhan/session_archives/2026-11-23
```

Exports original stored rows from six timestamped market tables in one
consistent read snapshot into compressed JSONL files, with counts and
byte/row checksums, then verifies before publishing the directory.
An absent table is explicitly identified. Existing archives are verified,
not overwritten; interrupted hidden .partial directories remain for
inspection. This is a non-destructive backup, **not** a transparent
archived-data reader or automated disk reclamation policy. It does not
delete the canonical rows or certify complete provider coverage. Run
off-hours to avoid competing with live recording and to avoid prolonged
read transactions. Actual disk reserves and write behavior require
local observation. No broker calls or order changes.
