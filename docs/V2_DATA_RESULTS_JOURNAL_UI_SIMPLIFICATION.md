# QuantLab V2 interface simplification — Data, Results, manual trading

This PR continues the **Models Catalog → Model Setup → Results** redesign.

## Data Center / Database Manager

Default integrated view has four clickable tasks instead of making users first
expand ten database-management tools:

1. **Browse market data:** unified shared market library.
2. **Get missing data:** source-aware model acquisition/reuse.
3. **Inspect stored records:** original price tables and file provenance.
4. **Health & recovery:** database integrity and interrupted-job review.

An advanced disclosure still contains **every prior source, analytics,
microstructure, research, and database-browser tool**. The four-task entry
changes only navigation, not file locations, provider permissions, source
acquisition approval, evidence classification, or dataset deletion.

Global workstation titles are now compact on pages that already have an
internal title. This removes duplicate explanatory headers.

## Results & Charts

- Filter the existing saved-run picker by **All / Models / Index runs** without
  changing the selected underlying result or its archived evidence.
- The integrated Results screen drops the redundant four-stage checklist and
  uses a smaller header. Interactive charts, comparisons, evidence audit,
  sources, statistics, the Ask QuantLab tool and exports remain intact.
- Source classifications and all mathematical inputs are unchanged.

## Trading / Journal

- Recording a *manually entered* option fill **does not automatically start
  a six-minute countdown**. The user can hold until their real exit decision,
  record that price and compute net entered-fill P&L.
- The six-minute local reminder remains an **optional expanded tool** in
  Trading → Live Market and is not an exit policy.
- The old six-minute summary statistic remains available under an optional
  disclosure for research continuity, not as the dominant journal label.
- There is no broker order execution, no algorithmic exit override, and no
  change to the historical holding-rule backtest choices.

## Local acceptance

1. Open **Data Center → Data Explorer**; select each of the four task cards,
   then expand advanced tools and confirm source provenance and database
   inspection remain accessible.
2. Open **Results & Charts**, switch **Models / Index runs / All**, reopen a
   saved run and check charts, exports, archived evidence and compatible
   comparison. The result does not change with the picker filter.
3. Open **Trading → Journal** and enter a manually reported fill. No timer
   should automatically start; optional timer controls remain separate.
4. Verify all eight sidebar destinations, sticky navigation, responsive
   layouts and key pages in both Chromium V2 and classic browser tests.

A green CI run establishes interface behavior against isolated synthetic
fixtures, not live Dhan market conditions or profitable trading.
