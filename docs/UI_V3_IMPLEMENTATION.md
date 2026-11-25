# QuantLab UI V3 implementation and acceptance

This is a local-first research application. The new graphite/amber visual system is scoped to the existing V2 shell. Green/red remain semantic market and status colors. No broker order path has been enabled.

## User workflow
- Global Python opens a resizable workspace from any route; it preserves draft state across navigation.
- My scripts persists named code, category and immutable revisions to local SQLite in data/quantlab_scripts/library.sqlite3. Save uses optimistic revision checks. Save as new retains history. Existing browser-saved strategies can be imported, and code can be exported as .py.
- Python analysis on compatible research and market charts attaches the displayed fixed snapshot; the option chain and Data Explorer expose contextual snapshots too. The chart sandbox accepts analyze(data), with title, x_label, y_label and aligned finite-or-null traces. Source rows are not overwritten. The custom output is shown separately and labeled user-snapshot analysis. A strategy opens the existing causal strategy editor, which uses completed historical/live candles.
- Run snapshot uses the existing local research queue and mandatory bubblewrap/prlimit subprocess. Only the copied input and script are mounted. Standard library only. No unsafe fallback, broker credentials or order permissions.
- Automatic recorder uses the existing token/setup and persisted disarm rules. In Trading -> Order Book, select an automatically captured contract to inspect its latest saved original book. This does not start another broker socket. A manual ticker may be stopped while automatic capture is armed; the UI must not call those saved samples live signals.
- Trading -> More tools contains Options Analytics and Directional Trading, alongside the existing chain/strategy paths. Existing routes and paper trading remain available.

## Acceptance
- Existing React build, Python tests and Chromium acceptance suite must pass on the final head. New tests cover script version history, input/output validation, fail-closed sandbox, compact navigation and saving reusable code.
- Verify actual Dhan token validity, local namespace permissions, market-hours capture and real source coverage on the user's Ubuntu machine; CI uses synthetic fixtures only.
- Snapshot-based Python is not an automatically executing custom live indicator, arbitrary package manager, broker execution engine or plugin registration system. These require a separate capability review. Do not claim those features are ready.
- Chart improvements cover shared research figures, observed index and advanced option plots. Dedicated legacy chart types still need a complete inventory and per-route visual QA before claiming the entire redesign is finished.
