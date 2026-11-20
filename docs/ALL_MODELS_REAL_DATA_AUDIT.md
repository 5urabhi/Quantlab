# QuantLab — Check every model against every local dataset

## One safe command

From the already-cloned QuantLab folder:

```bash
cd ~/Desktop/codes/quantlab
git pull --ff-only origin main
bash run.sh audit-models
```

This is **read-only** with respect to original Dhan/NSE observations and
broker sessions: it does not contact a broker, submit orders, arm/disarm the
depth recorder, download data, or create saved trading/model experiments.
The command runs under reduced CPU scheduling priority (`nice -n 10`)
to favor live recording. It may still consume CPU, RAM, and disk; running
after NSE hours is safest for a heavily loaded recorder.

The command scans **every active non-synthetic local dataset**, including the shared Dhan
library when present, and covers **all registered 35 models**. It executes the
nine assumption-based mathematical models once without market history. For
each non-synthetic dataset, it checks the 21 historical-data and five
option-quote models against their actual source prerequisites and executes
those with usable inputs. It does not fabricate missing data or label an
index spot proxy as option premium or NIFTY TRI.

### Useful options

```bash
# Audit just one prepared dataset, e.g. the shared Dhan collection:
bash run.sh audit-models --dataset dhan_shared

# Audit input readiness WITHOUT any model computation:
bash run.sh audit-models --preflight-only

# Demand that absolutely no inputs are missing:
bash run.sh audit-models --strict

# Save to an explicit new directory:
bash run.sh audit-models --output-dir results/my_first_model_audit
```

`--dataset` can be repeated to audit multiple named source datasets. Unless
a dataset is explicitly selected, **all active datasets** are checked.
Archived/deleted sources and the built-in synthetic demonstration are not silently included. For an explicit fixture-only diagnostic, use `bash run.sh audit-models --dataset synthetic`; its results never count as original market evidence.

The command requires the existing Python virtual environment. If it is absent,
run `bash run.sh setup` first. It never restarts the running FastAPI,
Vite, market-data capture, or any live process.

## What the command produces

Under `results/model_audit_YYYYMMDD_HHMMSS_microseconds/`:

- `MODEL_AUDIT.md` — a readable dataset-by-dataset report of every
  model, sample depth, missing history, exact selection, actionable blockers,
  source changes and failures.
- `ALL_MODEL_RESULTS.csv` — one row for each of the 35 registered
  model IDs, with 26 source-dependent checks repeated for each dataset.
- `DATASET_SUMMARY.csv` — all dataset names and counts, including
  source-backed passes and blockers.
- `SUMMARY.json` — input/model metadata, original file SHA-256
  manifests, outcomes and explicit limitations. Original vendor price rows,
  market-depth packets and credentials are not exported by the audit.

The four model-result states are:

| Result | Meaning |
|---|---|
| `math_pass` | The model numerically ran from **assumed** mathematical parameters. |
| `observed_input_pass` | The numerical model ran on local original-source input with identifiable dataset/contract ID. It is not externally certified. |
| `blocked_input` | No valid original source, enough continuous returns, or usable option quote. The report states what to obtain. |
| `software_fail` | The model or dataset evaluation failed during actual calculation or source parsing. Inspect the failure before declaring readiness. |

`ready_not_executed` means input checks passed, but the user explicitly
requested `--preflight-only`. `source_changed` means canonical input bytes
changed during the audit, so the result should be discarded and rerun on a
stable snapshot.

The default command exits nonzero on software failures or a changing source,
but **not** merely because some genuine external market data is missing.
With `--strict`, missing inputs also cause a nonzero exit status. Missing
inputs are never reclassified as passed.

## Historical models and the +20% rule

At least one exact single-stock series is needed for four historical
stochastic fits: GBM (10 observed returns), OU log-realized-volatility (90),
Merton jump proxy (120), Heston realized-variance proxy (252). Their preferred
targets are respectively 12, 108, 144 and 303 returns.

Portfolio, risk and inference models normally use up to eight aligned
eligible securities (minimum two), with eligible counts shown in the CSV.
When an original panel has fewer complete stocks, this audit may lower its
explicit research asset count to evaluate a valid smaller problem; when needed,
a constrained optimization cap is adjusted to remain feasible. The selected
values are recorded in the output, not hidden.

Missing and nonfinite prices are not forward-filled. Annualization is based on
the actual source frequency. Dhan historical stock prices do **not** by
themselves prove historical survivorship safety, total-return conventions,
dividends, public filing dates or profitable index construction.

If a model is blocked, use:

**Data Center → Get Market Data** → select exact stock/model → preview
missing original observations → explicitly authorize the missing-data
append with the extra 20% buffer → rerun this audit.

## Option models

The five observed-quote models need dated, original option bid/ask, index
spot, strike, expiry and an explicit model rate/yield assumption. The audit
tries available saved original contracts, but a quote can be invalid for
European Black–Scholes inversion despite passing structural source checks.
It reports that as a blocked input, not as a fabricated volatility.

Use **Models → Model Catalog → observed quote model → Get original option
quotes** to collect a read-only Dhan option-chain snapshot. The CSV original
quote importer remains available when source permissions allow it. There is
no automatic implication that every option quote is current or executable.
No historical option premium is reconstructed from spot candles.

## Mathematical correctness and research validity

A successful execution is **software acceptance**, not evidence of forecast
accuracy, profitability, production execution, independent NSE verification
or permission to redistribute exchange data.

The base stochastic models (GBM, OU, Heston, Merton, antithetic MC) are seeded
simulations with manually assumed parameters. Where an empirical companion
exists, the audit checks that separate historical model; it does not claim the
base theoretical simulation was itself calibrated.

The historical Heston model is deliberately an estimated **realized variance
proxy**, not market-calibrated risk-neutral Heston. A complete multi-expiry,
multi-strike Heston calibration needs licensed original surfaces and a separately
validated optimizer; that system is not falsely marked implemented.

Point-in-time index construction requires dated constituents, dividend and
corporate-action evidence, proper TRI and a frozen untouched test before any
public performance or alpha claim. For additional source evidence, open
**Data Center → Quality & Coverage / Research readiness** and run the
existing historical acceptance workflow after obtaining the original files.

## Separate software regression check

The real-data audit complements, but does not replace, the full CI/local
mathematical test suite. Run:

```bash
cd ~/Desktop/codes/quantlab
bash run.sh check
```

This checks the React/FastAPI build, Python regression suite, numerical
invariants and the original-source readiness doctor. It uses test fixtures
where needed; only the `audit-models` command checks which of your *actual*
local market inputs can run each model.
