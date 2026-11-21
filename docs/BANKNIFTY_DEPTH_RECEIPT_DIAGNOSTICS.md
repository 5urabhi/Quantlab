# Read-only investigation of saved BANKNIFTY 20-level integrity failures

Run `bash run.sh verify-saved --dataset dhan_shared` on the workstation with the
original local Dhan source files, then open the newest
`results/full_saved_verification_*/FULL_TRADING_READINESS.json`.

The `saved_books.invalid_reason_counts` object now classifies each of the
latest 200 failed original 20+20 bid/ask receipt pairs into one mutually
exclusive diagnostic code. It does not include contract IDs, account data,
individual price levels or original WebSocket payloads. The standard
`stored_depth` result also displays the four most frequent reason/count
pairs for quick diagnosis.

Most useful codes:

| Code | Meaning / safe response |
| --- | --- |
| `missing_original_book` | Paired feature exists but its original book is missing; inspect collection/storage failures and preserve the feature. |
| `unparseable_saved_json` | Source book or derived feature cannot be decoded; preserve original bytes. |
| `stored_receipt_digest_mismatch` | Saved feature and original book receipt hashes differ; review storage provenance. |
| `packet_pair_digest_mismatch` | Bid/ask original packet receipt hashes do not recompute to the stored combined digest; investigate capture integrity. |
| `source_provenance_mismatch` | Original-full-depth provenance fields are absent or inconsistent; do not count as verified original Dhan books. |
| `incomplete_twenty_level_book` | At least one side has fewer/more than 20 levels. |
| `crossed_top_of_book` | Stored best bid exceeds best ask; leave unchanged and verify later source feeds. |
| `invalid_level_values` | Nonpositive level price, negative quantity, or incompatible numeric value; keep original evidence. |
| `identity_or_timestamp_mismatch` | Book/feature identity or timestamp differs from its database row. |

Other codes distinguish missing digests, invalid feature side or units,
invalid level structure, and unexpected recorder session IDs.

This is **diagnosis, not automatic repair**. Keep all original records,
do not rewrite digests or drop bad observations to manufacture a passing
sample. No exchange-time freshness, entitlement, executable fills or
historical CE/PE strategy profitability is certified.

The report only audits the latest 200 automatic saved receipts. It is not a
full-database integrity audit, and it does not change the 35-model saved-data
verification verdict. Re-run on the same workstation to learn which failure
categories account for its reported 58/200 invalid receipts.
