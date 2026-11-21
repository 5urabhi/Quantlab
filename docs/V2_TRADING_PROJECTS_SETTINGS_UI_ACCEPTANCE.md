# QuantLab V2 — Trading, Strategies, Projects, Settings usability acceptance

This is a presentation and workflow simplification atop the existing original-
source research engine. No broker orders, Dhan recording changes, risk-model
formula changes or market-source edits were introduced.

## Trading
- Live Trading, Option Chain, 20-Level Book, Replay and Trade Journal remain
  separately discoverable research destinations.
- Manual trade entry requires the user to enter the *actual broker fill*;
  source interpretation is a collapsed "How fills are interpreted" disclosure,
  not repeated warnings before each field.
- Default trade table shows symbol, status, direction, quantity, entry, exit,
  holding duration and net recorded-fill P&L. Optional six-minute statistics
  remain in a disclosure. It does **not** impose a six-minute exit policy or
  submit an order.

## Strategies
- Three clickable research starts: EMA Crossover, Custom Python, and real-data
  BANKNIFTY Options Backtest.
- Each card describes what it computes and routes to the existing focused
  workflow; no banner claims strategies are "ready" without inspecting saved
  original market observations.
- Source integrity, option contract validity and no-live-order qualifications
  remain in a concise optional explanation.

## Projects and Notebooks
- New task-first project header shows real saved project and notebook counts.
- One creation action at a time: **New project** or **Notebook**. Notebook
  creation is disabled until a destination project exists and is selected.
- Click a saved project to edit goal/scope, then click a notebook to edit
  research cells, saved-run references, charts and report source.
- Import portable project ZIP, add cell options, and export notebook JSON are
  collapsed until the user requests them; full functionality is retained.
- The existing notebook autosave and source-limited report HTML/MD/PDF
  generation are unchanged.

## Settings
- Connections, Automatic Recording and System Diagnostics are visible
  high-frequency tabs; Storage & Data Management, Preferences, privacy and
  Help remain accessible under **More tools**.
- Connections opens a summary of actual local Python health, whether Dhan
  credentials are *present* (not necessarily valid), and disabled broker
  ordering. Credential entry is a deliberate action ("Manage Dhan
  connection") instead of the initial page.
- Automatic Recording continues independently of navigating the UI.
- All data remain local, and the service is not made network-exposable.

## Validation

Browser acceptance verifies the new Projects creation modes, Settings
connection details, the recorder settings and remaining advanced Settings
routes. All other previous interface and numerical regressions still run.
Live Dhan contract coverage, original NSE events, Heston's missing daily
returns, and actual trade performance must separately pass saved-data
acceptance, not just synthetic browser fixtures.
