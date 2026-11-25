# QuantLab Models and Data Center follow-up

## Models
- Main navigation exposes catalog, index builder, custom models, experiments and guided grids.
- Catalog groups calculations by mathematical family. Source selector, readiness check, input type and ready-only filters are explicit.
- Model detail retains real input parameters, mathematical reference, backend execution and saved-result links. The three-step workflow and graphite/amber surfaces replace the inherited teal layout.
- Advanced research offers direct access to specialized workflows and an explicit parameter sweep / validation / scenario / reproducibility selector.

## Data Center
- Market Library defaults to the unified saved-data inventory, followed by dated equity universe and sector browsing and original prepared source views.
- Coverage counts, first/last stored timestamps and per-instrument / expiry / resolution entries are derived from the local canonical SQLite tables or original cache receipts. Raw historical files use actual first/last CSV rows, not requested date ranges.
- Database row previews use allowlisted scalar fields only. Payloads stay in original replay tools. Search, type filters, pagination, coverage JSON, preview JSON and Python snapshot transfer do not download or duplicate originals.
- Records distinguish closes, candles, ticker events, quote events, OI events, chain snapshots, depth books, derived features, sector classifications, expired-option receipt timestamps and archive receipts. Counts are not additive; overlapping receipts and derived data must not be treated as extra observations.
- A logical library does not mean every raw file is physically stored in one SQLite table. Existing prepared research data, raw caches and backups remain in their original locations.
- SQL reads and receipt enumeration are bounded and cached. Interrupted scans or mismatched receipts show partial/not verified, not zero data. CSV receipt counts and endpoints are not a fresh full SHA verification. Observed date ranges do not establish gap-free coverage or completeness.
- Acceptance: regression suite, Chromium desktop/mobile route audit, new model/source controls and inventory interaction tests. Actual user's saved source inventory must be inspected locally.
