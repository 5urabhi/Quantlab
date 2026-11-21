# Dhan original candle timestamp recovery — CANBK batch 2026-11-21

## The observed local failure

The user's Ubuntu batch `batch_d9d83f019467471b` processed 15
BANKNIFTY bank-stock instruments. Fourteen completed and **CANBK (10794)**
failed its first daily candle request for 2023-11-21 to 2024-11-20.
The Dhan REST call returned HTTP success, then the original provider-candle
validator rejected the result with `Dhan supplied missing or duplicate timestamps`.
The index price request subsequently completed. A generic `batch completed`
message does **not** mean full 15-of-15 data acceptance.

## Recovery behavior

- Convert Dhan's original Unix-second timestamps to timezone-aware IST.
- Segregate rows whose timestamp is absent, unparsable or out of range
  into a dated source-audit CSV, **but reject that entire source window for
  coverage purposes**: without a valid timestamp we cannot prove when the
  undated observation occurred. Good rows in that response are not falsely
  certified as a complete historical interval.
- For two bars with the **same instant and exactly equal numeric OHLCV**
  (including open interest if present), keep one original observation and
  quarantine the repeated observation. Numeric equality is not a guarantee
  that vendor JSON bytes were identical.
- If two bars with the **same timestamp have different source OHLCV**,
  **fail closed**. It is impossible to pick the true bar from those conflicting
  observations. Do not use first/last, interpolate, forward-fill, or invent
  a candle to complete the date window.
- Keep a source-audit copy of quarantined rows in the existing
  `*_rejected/` directory, including the original Unix timestamp and
  rejection reason. When a source window is otherwise valid (e.g. a repeated
  *identical* observation), its receipt records the reject file and SHA-256,
  and it is marked `partial_source_anomalies`. When even one original
  timestamp is missing or unparsable, the audit CSV is retained and the
  window fails **without changing the verified coverage manifest**. If all
  bars are invalid, no verified coverage is written either.
- Verified windows from other stocks and past CANBK downloads remain
  untouched. Running a failed batch again skips stock rows already marked
  complete/cached and downloads only uncovered failed windows.
- A completed background job with any failed stocks is explicitly logged
  as incomplete source coverage, with failed symbol names. The Data Center
  shows a focused source-timestamp diagnostic and an existing
  **Resume / retry missing** action.

## User workflow — no command-line fix required

1. Update QuantLab from the canonical repository
   `https://github.com/5urabhi/Quantlab`.
2. At **Data Center → Downloads**, open
   `batch_d9d83f019467471b` and confirm that 14 stock items are complete
   and CANBK remains failed.
3. Click **Resume / retry missing**. Previously source-verified windows are
   retained; original Dhan data is requested only for the unresolved window.
   This requires a valid local Dhan session and the user's authorized API.
4. If the returned duplicate rows are numerically identical, the window
   can now finish, with an audited rejected-row count. If the duplicates
   actually conflict, CANBK remains failed and should be escalated to the
   provider instead of falsifying a market observation.
5. Confirm **15/15 complete** before assuming the full index constituent
   history has been prepared and ingested. Rerun the source-backed model
   audit and inspect actual Heston readiness separately.

## Software acceptance

- Parser tests for missing timestamps, exact repeated values, inconsistent
  duplicate timestamp values, no all-invalid-source acceptance, and original
  quote/volume preservation.
- Batch tests for reusable SHA-checked cache, source-audited discarded rows,
  clear user-facing source errors and fail-closed conflicting data.
- No broker orders, no alteration of previously saved original candle cache,
  no hiding or fabricating monthly/NIFTY total returns.

**Limits:** This fixes a class of vendor timestamp anomalies. It cannot
prove what exactly happened to CANBK's original response without the
unmodified source arrays, and does not guarantee all 15 securities will
succeed on the next authorized request.
