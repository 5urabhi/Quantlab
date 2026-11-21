# QuantLab — canonical repository and discoverable tools

## Canonical GitHub repository

QuantLab's repository was renamed on November 21, 2026:

**https://github.com/5urabhi/Quantlab**

The GitHub repository ID, history, existing PRs, live-recording code, market-data
files, and default `main` branch remain the same.

Fresh clone:

```bash
git clone https://github.com/5urabhi/Quantlab.git quantlab
cd quantlab
bash run.sh
```

Existing checkout: update the configured remote explicitly so future pushes
and pulls no longer depend on GitHub's rename redirects:

```bash
cd ~/Desktop/codes/quantlab
git remote set-url origin https://github.com/5urabhi/Quantlab.git
git fetch origin --prune
git switch main
git pull --ff-only origin main
```

This does not delete user-created local branches, reset working files, clear
the original Dhan data store, or restart a running recorder. Starting/restarting
the app is a separate manual action when recording is inactive.

## Workspace navigation

QuantLab keeps eight primary workspaces. Each workspace exposes two or more
common pages as visible top tabs. Its implemented but less frequently used
pages are grouped under **More tools** in that workspace:

- **Models:** Factor Research, Portfolio Construction, Risk Attribution,
  Rolling Validation, Robustness & Sensitivity, Guided Model Grids,
  Index Research Studio and New Guided Study.
- **Data Center:** NSE Source Evidence and Evidence & Machine Learning.
- **Results & Charts:** Historical Charts, Index Comparison and Research Jobs,
  in addition to the visible saved-results, comparisons and chart studio.
- **Projects:** Saved Resource Library.
- **Settings:** Backend & Privacy and Help & How It Works.
- Other research pages remain discoverable without crowding the main tab row.

Every More tools item opens the **existing** route. No registered mathematical
model, dataset, strategy, numerical evaluation, live market packet, recorder
process, or source-audit capability is removed. Switching pages does not
reinitialize the Dhan collector.

## Acceptance

- Select **Models → More tools → Risk Attribution**, then Model Catalog.
- Select **Data Center → Quality & Coverage → More tools →
  NSE Source Evidence**, then Downloads.
- Verify the submenu works with a keyboard (Tab → Enter / Space and
  regular focus traversal), has a visible current-page label, and remains
  usable at narrow desktop and mobile widths.
- Run existing browser + Python acceptance. Automated UI fixtures are not
  live-market correctness or broker latency certification.
