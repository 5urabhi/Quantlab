# QuantLab — Canonical Release and Empirical Evidence Status

Last targeted maintenance/session review: **November 27, 2026 IST**. Earlier platform acceptance below remains dated November 17. See [current implementation and remaining-work register](QUANTLAB_CURRENT_WORKLIST.md) for the latest scoped review.

Run `bash run.sh check` for current React build, Python regression, mathematics and a read-only original-source readiness doctor. `bash run.sh evaluate` additionally generates clearly labeled synthetic experiment and chart artifacts. Both keep unavailable authenticated/licensed input distinct from a code failure. The previous `scripts/local_acceptance.py` legacy-Streamlit default is retired; archived Streamlit checks require explicit `--legacy-streamlit`. This is the authoritative status
register; older archived Streamlit/branch-specific status documents are not.

## November 17: source-safe candle window crash recovery

Dhan now writes each validated original candle CSV and its checksum/coverage
receipt using an explicit pending-manifest journal. A Python process crash
between writing the original candle file and publishing its receipt no longer
automatically turns that checkpoint into an unrecoverable SHA mismatch.
During the next authorized resume, QuantLab verifies the **exact original
CSV SHA-256 and Dhan exchange/security/interval identity** before finishing
the pending manifest publication without another broker request.

If the crash happened before replacing the CSV, the previous complete
checksum pair remains authoritative; QuantLab discards only the incomplete
metadata journal and downloads the still-missing date window using the
existing legal/provider-aware retry rules. If saved bytes, metadata or source
identity disagree, it **fails closed** rather than guessing or modifying
original market observations. Recoveries are counted in Dhan download details
and the Database Manager activity view.

Offline regression tests explicitly inject interruptions at both rename
boundaries, tamper a saved candidate, and verify that no original price
history is synthesized or silently replaced. This is process-interruption
recovery; it does not promise recovery from physical drive failure or
uncertified vendor source history.

## November 17: repository-side reliability, research and operational hardening

The Data Manager **Activity & recovery** panel now exposes read-only source
SQLite integrity, disk capacity, enabled Parquet state, interrupted jobs and
broker session-presence diagnostics. This check does **not** contact a broker
or certify a historical dataset. Job progress/stages are persisted with
backward-compatible SQLite migrations; recent job links after a restart show
the last durable receipt and an explicit interrupted state rather than
pretending completion. Dhan batches scheduled but not yet started are correctly
shown as queued; interrupted user-authorized batches retain their saved
per-window data and are not forcibly restarted after credential failure.

Registered empirical model readiness and numerical runs share one canonical
historical-price matrix contract. A current, source-locked DuckDB/Parquet
mirror may accelerate the shared Dhan daily/monthly matrix, matching original
price dates/security columns and refusing corrupt source receipts. On stale
or unavailable acceleration, the original validated CSV remains authoritative.
No historical session is forward-filled. Broker secrets and tokens are
redacted from durable operational errors; the localhost-only credential
boundary and no-orders policy remain unchanged.

Results Studio **Overfitting & regimes** adds an expanding training-only
selection stability analysis: choose initial training months, nonoverlapping
later test months and an explicit 1–6 month embargo. It exports full
fold-by-fold observations and matching benchmark returns. This is a useful
retrospective candidate-selection diagnostic, **not** per-fold strategy
retraining, label-purged CPCV, a never-viewed preregistered final test,
or an independent market-performance certificate.

Old source/mathematical acceptance reports are rechecked against current
source hashes. If a source changes or disappears, QuantLab marks the old
receipt stale without rewriting its historical evidence. Reports also cannot
claim a model pass if no model actually executed.

**Deliberate software limits:** Source-changing operations remain serial to
protect original price and account records. Complete historical index
constituents, licensed TRI and corporate events, true exchange execution
fills and independent publication review still require original external
data. The current source-safe mathematical/ML catalog does not represent a
trained production PPO/SAC/LSTM trading agent or a broker execution router.

## November 17: Zerodha as second historical provider and source acceptance

QuantLab now offers optional Kite Connect historical equity candles after Dhan cache
and authorized original Dhan requests. It requires an official login, a current
Kite NSE/BSE instrument master, exact exchange-token and trading-symbol match,
explicit fallback consent and consistent overlapping Dhan closes. Session and
master status are available in-app; neither credentials nor historical archive
rights are inferred from source metadata. The new real-data acceptance action
combines PIT, TRI, corporate-action, chronological holdout and numerical model
checks into a saved report, but never issues an exchange certification.

**Not yet independently verified:** actual broker credentials, provider
entitlement, full delisted-security coverage, genuine full TRI/corporate-action
history, and a finalized untouched holdout study. See the Research Completion
Guide for the local acceptance path. No order placement is involved.

## November 17: automatic historical index source initialization

On a new checkout, the Data Library's NIFTY 50/BANK NIFTY historical
selection now automatically prepares missing public PIT constituent records
and current Dhan Security IDs, shows distinct failed-provider errors, and
offers explicit end-date correction when the upstream membership source has
not documented the requested final trading sessions. Source preparation is
read-only and separate from starting a real Dhan price download. Multi-year
minute history has a visible recommendation to switch to Daily.

Historical membership remains a third-party reconstruction, not exchange
certification; a current Dhan master cannot resolve every old delisted or
renamed constituent. An official total-return benchmark and audited stock
returns remain separate inputs.

## Acceptance matrix

| Capability | Software | Genuine historical NIFTY evidence |
| --- | --- | --- |
| React/FastAPI workstation and local dataset manager | CI and Chromium tested | Dhan entitlement needs user-local access |
| Multi-factor Index Studio and constraints | Implemented | Actual PIT and dated factor inputs pending |
| Benchmark-relative optimization | Implemented | Real dated benchmark weights pending |
| Sourced Yield and source-vintage fundamentals | Implemented | Original filing and payout record review pending |
| Factor/specific active-risk estimation | Implemented | Authentic factor returns and weights pending |
| Capacity, spread and square-root market impact | Implemented | Historical ADV/spreads and cost assumptions pending |
| Explainability/Graph Studio/Data Passport | Implemented | Source truth and independent reproducibility pending |
| Immutable research releases and three study pipelines | Implemented | Actual untouched empirical holdout not completed |
| Python SDK, Jupyter, saved calculations, replay | Implemented | Authorized source access for external reviewer pending |
| Synthetic large-universe CPU/memory benchmarks | Bounded script and CI artifact | Does not demonstrate exchange data accuracy |
| Local demonstration video generation | Opt-in recorder available | Actual video must be recorded and reviewed |
| Resume/public abstract and methodology drafts | Source-safe wording available | No independently validated factor-alpha metric |
| Production NIFTY research publication | Methodology and release tools ready | NOT complete; independent review required |

Software verification source: GitHub Actions on main, CI workflows
[Python/React](../.github/workflows/workstation-ci.yml) and
[Ubuntu Chromium](../.github/workflows/workstation-browser-smoke.yml).
Review the most recent workflow SHA before claiming an individual release
passed. CI uses deterministic synthetic fixtures, not audited NSE results.

## Source-assembly upgrade (research inputs)

QuantLab now has source-preserving month-end calendar alignment, a first
publication date-lagged official monthly weight snapshot importer, reconstructed
PIT membership disagreement reporting, and exact missing security-month
coverage. These tools address input *integration*, not independently establish
original NSE data completeness. See
[Authentic NIFTY Data Completion](NIFTY_SOURCE_COMPLETION.md).

## Additional local engineering acceptance

The source-locked job-recovery endpoint permits explicit retry after a Python restart only for registered idempotent research calculations (sweeps, validation, notebooks and learning). Any changed price, metadata, calculation code or edited notebook forces a new run. Existing Dhan bulk batch recovery remains separate and can resume its saved windows with the configured local token.

The Data Quality duplicate scan now fingerprints *all files*, including nested source provenance. It offers only confirmed, dependency-protected, recoverable Trash for redundant prepared views; source candle caches are never deleted. Plot Builder accepts optional user-declared INR/USD/EUR/GBP labels and explicitly labels return fractions. Exact-date compatible figures can synchronize zoom and pan.

These are **software capabilities**, not evidence that a real-market original-source study passed.

## Source completion worklist in Experiment Studio

The **Exact missing history and evidence to collect** panel now consolidates what was formerly scattered between terminal reports and source audit pages. It reports actual eligible stock and forward-return gaps, whole missing months, unresolved historical identities, preferred +20% training-buffer shortfall and source-specific official acquisition links. The **Export missing-source ZIP** action packages only source identifiers, evidence status and hashes; it does not export copyrighted market records or credentials.

The displayed final-test count now follows the actual return labels produced by `backtest_index` (price dates after the first observation), fixing an older one-month undercount in the empirical coverage doctor. A corrupt source panel keeps the repair worklist visible with a blocked audit rather than hiding the next steps. These are **software improvements**, not independent NSE source review.

## Official NSE public source navigation

Experiment Studio now distinguishes six public archive pages (official NIFTY
TRI, monthly constituent weightage, daily EOD Bhavcopy/volume, reconstitution
notices, original corporate actions, issuer financial filings) from approval-
required **Data for Research** and proposal-reviewed **Data for Analytics /
NSE Data Room**. Import routes use existing Dhan/Data Library workflows; raw
exchange observations are not automatically fetched or reclassified as
certified. The source-worklist ZIP includes a public-source guide in addition
to the previously verified missing-security and evidence reports.

## Existing TRI and official NSE source automation

The historical-evidence screen now detects a **previously imported TRI**
from original benchmark metadata, reports its observed date coverage, and
explicitly avoids requesting a redundant import. A spot index or ambiguous
benchmark is never silently treated as total-return-index evidence.

The CLI `scripts/quantlab_nse_sources.py` supports source-safe offline
CSV/ZIP intake with SHA receipts and unverified dated-manifest templates,
plus explicit single-query informational access through NSE's published
MCP interface. **No prohibited NSE website scraper is included.** NSE and
NSE Indices prohibit automated website harvesting, and NSE MCP access is
informational/educational, not blanket backtest or redistribution permission.
See [NSE source automation](NSE_AUTOMATED_SOURCE_WORKFLOW.md).

## Official NSE MCP integrated into the browser

QuantLab now exposes **NSE Sources** inside Data Library and **NSE Source
Assistant** inside Experiment Studio. Official MCP informational requests
are routed by the Python backend through pinned NSE endpoints; users no longer
need terminal MCP commands. Lookups are opt-in, rate-limited, source-labeled
and never written to a saved TRI or historical backtest dataset.

The source assistant handles **nested JSON text errors** from NSE
(`isError: false` does not imply usable data). Corporate action outages
are shown as unavailable, **not** zero events. Stock-price lookups
precheck corporate actions, carry coverage warnings, and never promote raw
price-index values to dividend-adjusted TRI.

Authorized NSE ZIP/CSV/XLSX/PDF reports can be prepared in the browser;
originals, checksums and blank first-publication manifest fields remain local.
Automatic site scraping and unrestricted historical MCP harvesting are not
part of the implementation. The original research and licensing
restrictions still apply.

## Dataset deletion and clearer NSE MCP instructions

Data Library now starts with **Your datasets** and a direct Use/Delete
action per dataset. A single Yes/No popup lists **all** dependent saved work
(model runs, experiment runs, notes, notebooks, reports and linked dataset
versions). One confirmed action moves the entire group to recoverable Trash;
manual removal of each old run is unnecessary. A stale confirmation token
or unsafe/protected source blocks the operation, and partial moves are rolled
back. Original Dhan market-data caches remain protected. Raw file and source
metadata tables are folded into Advanced panels so beginners can use the
main data workflow without deciphering technical columns.

The NSE Sources assistant now fills an editable RELIANCE example and explains
that its **Check NSE source** action is an informational MCP lookup, not an
automatic research dataset import. The existing TRI remains unchanged.

## Why empirical research is still blocked

A complete valid historical NIFTY study requires:

1. Original effective-date NIFTY membership notices and security identities,
   including removals/renames, audit of existing third-party reconstruction.
2. Fully sourced stock total returns and corporate actions: ex-dividend
   cash, split/bonus handling, rights/mergers, delisting recovery and suspensions.
3. Official NIFTY 50 Total Returns Index levels with actual previous-month
   close and compatible calendar and return convention.
4. As-first-published NSE financial results and historical market caps for
   fundamental factors, including documented revisions and announcement time.
5. Date-effective sector classifications, benchmark weights, factor returns,
   and historically observed ADV/spread data for advanced studies.
6. A preregistered model protocol, genuinely untouched later holdout and
   independent original-source/implementation review with licensing permission.

No synthetic dataset, modern constituents list, spot index candle, historical
close alone, source URL, checksum or user-submitted review flag can substitute
for these observations. The application explicitly marks them missing.

## NSE index-data rights

NSE's Data Sharing & Usage Policy may restrict creating a new index from
subscriber market data and redistribution of derived datasets. The official
research application path is
https://www.nseindia.com/static/research/initiatives-data-for-research
(request form via nseri@nse.co.in). Source download availability is NOT
index-creation or publication permission. Confirm intended noncommercial use
and obtain any necessary license before publishing a research product.

## Primary sources to acquire permitted exports

- Exchange TRI levels: https://www.niftyindices.com/reports/historical-data
- NSE Indices index membership schedules and methodology:
  https://www.niftyindices.com/resources/index-rebalancing-schedule
- NSE Indices monthly capitalisation/weightage archives:
  https://niftyindices.com/reports/monthly-reports
- Original NSE index announcements:
  https://www.niftyindices.com/Press_Release
- NSE company announcements and corporate actions:
  https://www.nseindia.com/companies-listing/corporate-filings-actions
- NSE financial results:
  https://www.nseindia.com/companies-listing/corporate-filings-financial-results
- Securities master/volume archives:
  https://www.nseindia.com/static/resources/historical-reports-capital-market-daily-monthly-archives

Some pages are interactive and rights-limited. Do not bypass authentication
or mass-download against a provider's terms. Save authorized raw source
files outside git; commit only legally shareable structured summaries.

## One-command missing-data and evidence report

    python scripts/research_release.py \
      --data-dir data/research_v1 \
      --config config/research_multifactor.json \
      --output-dir results/research_evidence_report_001

Produces a source checklist with official acquisition starting points,
SHA-256 inventory, internal audit (when possible), immutable HTML memo,
research evidence JSON and source-safe ZIP. Add --execute only after all
required statistical inputs and a genuinely frozen protocol are supplied.

## Publication and resume policy

The repository demonstrates implemented software mathematics, engineering,
testing, provenance controls and scientific communication. It does NOT
support claims of audited NIFTY annualized alpha, market-adjusted Sharpe,
historically invested capital, exchange-certified membership, or realized
execution quality. Any final paper must cite original licensed evidence,
actual code and reproducible results and clearly separate exploratory from
predeclared analysis.

A future reviewer may declare evidence complete, but the software will
still mark external independent certification as NOT established until a
separate manual review and public claim approval. This is intentional.
