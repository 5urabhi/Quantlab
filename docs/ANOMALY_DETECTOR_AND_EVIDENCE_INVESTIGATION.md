# QuantLab dedicated source-anomaly detector (November 2026)

## Where to find it

Open **Data Center → Quality & Coverage / Research → Data Quality**, select
an observed dataset, and press **Audit dataset**. The normal source-integrity
report now also runs a bounded, read-only statistical anomaly scan of the
original price panel. It shows observation dates, tickers, observed return
fractions, detector reasons, and original-file SHA-256. Use **Inspect selected
security** for a ticker-specific scan; export the complete displayed evidence
as JSON. A non-fatal anomaly-scan error never blocks the ordinary source
quality report.

The existing **Results & Charts → Ask QuantLab** now offers an explicit
**Investigate evidence** action for an archived run. It chains three local,
read-only operations: archived result interpretation, current source-integrity
inspection, and chronological anomaly detection. It reports per-step status,
source identifiers and limitations. Synthetic/theoretical runs do not call the
market anomaly detector. This is deterministic multi-tool automation, not an
LLM-powered agent.

## Mathematics and training provenance

1. Examine each original daily closing-price column without making a copy of
   the source file or requesting a vendor update. Null, nonfinite and
   nonpositive observations are flagged as missing/invalid; prices are not
   imputed and return pairs cannot cross gaps.
2. Compute log returns between directly adjacent valid observed rows.
3. For each return after a 20-return warmup, compute the median and scaled MAD
   from only *previous* returns (up to 60 by default). Flag a large deviation
   above 6 robust standard deviations or a >40% absolute simple return.
4. Fit a seeded scikit-learn IsolationForest on the **earliest 70%** of
   historical eligible returns, with fixed feature definitions and
   contamination=0.025; apply the frozen detector to **later 30% only**.
   Dates and local source hashes appear in every result. This is unsupervised
   outlier scoring, not an independently labeled fraud/error classifier.
5. A source snapshot may be compared against an archived run using exact
   byte hashes. If hashes do not match, QuantLab reports the mismatch, never
   claims that the archive has been reproduced or silently rewrites prices.

## API and code

- `GET /api/workspace/quality/{dataset_id}/anomalies?symbol=...&max_assets=6&max_events=50`
- `POST /api/workspace/results/{model_run|research_run}/{run_id}/investigate`
- `workstation_api/source_anomalies.py`: source-bounded statistical detection.
- `workstation_api/research_assistant.py::investigate`: three evidence steps.
- `tests/test_source_anomalies.py`: original file immutability, no cross-gap
  returns, chronological fitting, deterministic seeded outputs, input safety.
- `tests/test_research_assistant.py`: source and synthetic boundaries.

Use `python -m unittest -v tests.test_source_anomalies
tests.test_research_assistant` from the project root (or run all tests), then
`npm run build`. The demo fixture only tests mathematical/software behavior.
It is not real Dhan or NSE error-label evidence.

## Limitations

- The scanner reads up to 15,000 dates and a bounded selection of columns,
  not every security in a 6,000-instrument portfolio. The displayed event
  sample is bounded; get more by specifying a security.
- Calendar weekdays are not verified NSE trading days. A genuine stock split,
  unusual corporate event or stale/dealer-supplied close may cause flags.
- No statistical false-positive rate, labeled precision/recall, market alpha,
  trading safety or broker latency guarantee is implied.
- Data repairs, original trading books and market-provider side effects do
  **not** run automatically. The system raises review candidates and uses
  existing source-aware acquisition workflows only with explicit consent.
