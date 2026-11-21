# QuantLab full verification using existing original saved market data

## One command on the user's Ubuntu machine

```bash
cd ~/Desktop/codes/quantlab
git pull --ff-only origin main
bash run.sh verify-saved
```

This runs the numerical model validation regressions first, then executes all
**35 registered models**: nine assumption-only mathematical models once, and
all 26 observed-input models independently for every active non-synthetic saved
dataset. Reports include the exact historical input ticker, number of returns,
source SHA-256, saved provider quote reference and honest readiness status.

To limit a repeat run to the canonical shared Dhan data:

```bash
bash run.sh verify-saved --dataset dhan_shared
```

To make missing data a nonzero CLI exit code for automated acceptance:

```bash
bash run.sh verify-saved --dataset dhan_shared --strict
```

Results are saved under `results/full_saved_verification_UTC/`:

- `FULL_SAVED_VERIFICATION.md`: at-a-glance outcomes and exact blockers;
- `FULL_SAVED_VERIFICATION.json`: machine-readable status, provenance limits;
- `ALL_MODEL_RESULTS.csv`: every model/dataset result;
- `MODEL_AUDIT.md`, `SUMMARY.json`, `DATASET_SUMMARY.csv`: full
  original-price, historical index/PIT and source-integrity model audit.

This verification command reads saved sources and **does not contact Dhan or
Zerodha**, submit orders, invent additional prices, restart the streaming
collector or modify the original daily data/provenance files.

## Automatic reuse of recorded BANKNIFTY option chain

If `dhan_shared` has **no source-bound saved quote catalog entry**, the
verification checks its existing, checksum-protected BANKNIFTY SQLite chain
recordings. When an eligible historical observation exists, it explicitly
creates an **idempotent derived quote entry** from the *locally recorded*
original bid/ask for the five quote models. It prefers a snapshot received
during scheduled NSE hours, but this is only a local-time check. Original
vendor JSON and exchange tick time are **not** preserved. Option expiry
time is an assumed 15:30 IST convention. The model quote entry is not a
tradable live quote or proof of a fill.

To guarantee *no files whatsoever* are created outside the report directory,
use `--no-link-recorded`. The five observed-quote models will then remain
blocked until a quote is manually linked via Models.

## Distinguishing outcomes

- `ALL_REGISTERED_MODELS_EXECUTED`: all calculations executed against the
  permitted saved inputs with finite outputs; **not** independent market
  correctness, profitable trading or forecast accuracy.
- `SOURCE_DATA_INCOMPLETE`: at least one model was not executed because
  the actual saved source is insufficient. For example, Heston may have
  224 observed returns when a minimum of 252 and preferred +20% buffer of
  303 are required. The audit never fabricates the missing 28/79 returns.
- `SOFTWARE_OR_SOURCE_CHANGED`: a numerical failure, malformed coverage
  matrix or source file hash change. Must be investigated, never counted as
  a missing-data-only outcome.

A non-strict run returns 0 with an **explicit incomplete status**, so users can
still inspect its files. `--strict` returns nonzero when original inputs are
missing. True software failures always return nonzero.

**GitHub Actions tests use synthetic isolated fixtures**; only running the
command against the user's actual local saved originals establishes the
machine-specific results. Source SHA-256 stability does not authenticate the
vendor, create corporate-action-adjusted total returns or validate options
P&L under broker execution.
