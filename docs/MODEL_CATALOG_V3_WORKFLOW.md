# QuantLab Model Catalog — simpler workflow (November 21, 2026)

## The problem this change fixes

The earlier Models page showed a 4-step ribbon, 6 family tabs, 35 status
cards, a left-side model list, implementation/source badges, a separate
warning-heavy seeded-simulation panel, a large how-to-run checklist,
parameter editors, sources and download forms, four internal result tabs,
duplicate run buttons and an equation box. Clicking “See mathematical
assumptions” changed the hidden tab without bringing the user to its content.

## New three-screen experience

**1 · Models → Catalog**

- One search box and five research *topics*: Stochastic Processes,
  Volatility & Econometrics, Derivatives & Options, Portfolio Optimization,
  Tail Risk & Inference.
- A card shows the model name, one concise sentence, source status and
  one natural click target, “Open model”.
- “3D Visual Laboratory” is not a research category. Its three existing
  calculations are still present and counted among all 35. Derivative
  surfaces appear under Options, while correlation stress appears under
  Portfolio Optimization. This is a *presentation* mapping only; Python
  model IDs, registry groups, saved output metadata and formula code do
  not change.
- Recent saved work links to the real Results Studio.
- The status “Ready” means code and applicable local inputs are available,
  **not** that the model makes profitable predictions or has licensed,
  independently reviewed market data.

**2 · Model → Focused Setup**

- A single page title, context, one Simulation / Historical or Observed-quote
  switch for models that have both numerical modes, and “About & equation”.
- The equation opens a real keyboard-accessible modal, rather than moving
  the viewport invisibly into a different tab.
- Four core settings are visible by default; other numerical settings
  remain fully supported in “More settings”. Saved configurations are one
  click away. No parameter defaults or validation are changed by the UI.
- One **primary** action adapts to model readiness: Run model, reuse an
  existing original quote, complete the specifically recommended eligible
  stock, or open data options. Historical/provider downloads remain
  explicitly user-triggered. Existing source proof and all advanced
  acquisition/import controls remain under **Data options**, not deleted.
- Data errors are still surfaced when material. A source is never
  classified as observed if it is simulated, and no synthetic candles,
  bid/ask or exact brokerage fills are substituted.

**3 · Results & Charts → saved model run**

- “Run model” invokes the existing Python /api/lab/run and archives
  exactly the same numerical output.
- Once the server returns a successful run ID, the application navigates
  directly to **Results & Charts → that run**. Model metrics, interactive
  2D/3D figures, data/evidence audit, exports and comparisons already live
  there. Thus visualizations are not a sixth model category.
- Any saved run remains reopenable from the Catalog and Results library.
  A model's last edited settings are persisted to its existing local draft.

## Verify locally

1. `git pull --ff-only origin main` after this PR is merged; do not
   restart the recorder while NSE live capture is active.
2. Open Models. Search “Heston” or “Black–Scholes”. Confirm no sixth 3D
   category exists, but search “option surface” still finds its model.
3. Click a model card. Confirm its concise setup, one primary action,
   editable numerical defaults and working **About & equation** modal.
   Check Escape and click-outside closure.
4. Click “More settings”, make a change, navigate back and reopen the
   model. Existing local draft must preserve the value.
5. Open a historical model with insufficient dates: “Data options” should
   still expose the exact stock picker and the source-backed +20% action.
   No silent Dhan request should occur from merely opening a page.
6. For an observed-quote model, existing saved source-bound quotes should
   be reusable. Recording capture controls and live Dhan WebSockets must
   not be restarted by the new catalog.
7. Run a mathematical model. Confirm routing to the exact saved model
   result inside Results & Charts, and download its SVG/CSV/JSON figures.
   Confirm all 35 model IDs remain present and numerical tests pass.
8. Verify responsive desktop and mobile layouts. The canonical browser
   tests run both the compatibility and V2 UIs without real provider tokens.

## Limits

The UX refactor does not calibrate risk-neutral Heston from stock candles,
create new authorized historical quotes, certify original NSE dividends/PIT
membership, or enable live broker orders. Live recording, Dhan data
availability and real strategy performance are separate acceptance tasks.
