#!/usr/bin/env bash
# Local React/Vite + Python research workstation.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
# Manual historical research can run alongside live recording. Keep CPU and
# disk priority low and numerical thread pools bounded in these CLI processes.
manual_research() {
  export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 BLIS_NUM_THREADS=1
  if command -v ionice >/dev/null 2>&1; then
    exec nice -n 15 ionice -c 3 .venv/bin/python "$@"
  fi
  exec nice -n 15 .venv/bin/python "$@"
}
case "${1:-workstation}" in
  workstation|research|web|both)
    exec bash scripts/run_workstation.sh
    ;;
  verify-saved|verify-all-saved)
    if [ ! -x .venv/bin/python ]; then
      printf 'Python environment missing. First run: bash run.sh setup\n' >&2
      exit 2
    fi
    shift
    # Never stop or restart the live Dhan recorder; inspect saved sources only.
    # Keep numerical regressions independent of available source data.
    for case_file in \
      test_every_registered_model_runs.py \
      test_math_acceptance.py \
      test_model_validation.py \
      test_audit_all_models.py \
      test_recorded_chain_model_quotes.py \
      test_verify_saved_models.py
    do
      nice -n 10 .venv/bin/python -m unittest discover \
        -s tests -p "$case_file" -q
    done
    exec nice -n 10 .venv/bin/python -m scripts.verify_saved_models "$@"
    ;;
  audit-models|check-models)
    if [ ! -x .venv/bin/python ]; then
      printf 'Python environment missing. First run: bash run.sh setup\n' >&2
      exit 2
    fi
    shift
    # The same single command must verify mathematical correctness AND test
    # every registered code path before inspecting original local sources.
    # Reduced CPU priority favors independent live market recording.
    case " $* " in
      *" --preflight-only "*) ;;
      *)
        # Test files are intentionally not a Python package, so use
        # discovery rather than the fragile tests.test_name import path.
        for case_file in \
          test_every_registered_model_runs.py \
          test_math_acceptance.py \
          test_model_validation.py \
          test_audit_all_models.py
        do
          nice -n 10 .venv/bin/python -m unittest discover \
            -s tests -p "$case_file" -q
        done
        ;;
    esac
    # Execute as a module: the repo root must be on sys.path for workstation_api.
    exec nice -n 10 .venv/bin/python -m scripts.audit_all_models "$@"
    ;;
  cpr-repair)
    if [ ! -x .venv/bin/python ]; then
      printf 'Python environment missing. First run: bash run.sh setup\n' >&2
      exit 2
    fi
    shift
    for case_file in 'test_cpr*.py' test_options_history_sync.py test_data_maintenance.py test_full_option_feed.py
    do
      nice -n 10 .venv/bin/python -m unittest discover -s tests -p "$case_file" -q
    done
    exec nice -n 10 .venv/bin/python -m scripts.run_cpr_option_repair "$@"
    ;;
  cpr-next)
    if [ ! -x .venv/bin/python ]; then
      printf 'Python environment missing. First run: bash run.sh setup\n' >&2
      exit 2
    fi
    shift
    nice -n 10 .venv/bin/python -m unittest discover -s tests -p "test_cpr*.py" -v
    manual_research -m scripts.run_cpr_execution_evidence "$@"
    ;;
  cpr-context-check)
    if [ ! -x .venv/bin/python ]; then
      printf 'Python environment missing. First run: bash run.sh setup\n' >&2
      exit 2
    fi
    shift
    manual_research -m scripts.check_cpr_context "$@"
    ;;
  cross-index-research)
    if [ ! -x .venv/bin/python ]; then
      printf 'Python environment missing. First run: bash run.sh setup\n' >&2
      exit 2
    fi
    shift
    manual_research -m scripts.run_cross_index_research "$@"
    ;;
  candle-research)
    if [ ! -x .venv/bin/python ]; then
      printf 'Python environment missing. First run: bash run.sh setup\n' >&2
      exit 2
    fi
    shift
    manual_research -m scripts.run_candle_patterns "$@"
    ;;
  cpr-research)
    if [ ! -x .venv/bin/python ]; then
      printf 'Python environment missing. First run: bash run.sh setup\n' >&2
      exit 2
    fi
    shift
    manual_research -m scripts.run_cpr_hybrid "$@"
    ;;
  validate-trading)
    if [ ! -x .venv/bin/python ]; then
      printf 'Python environment missing. First run: bash run.sh setup\n' >&2
      exit 2
    fi
    shift
    exec nice -n 10 .venv/bin/python -m scripts.validate_trading_research "$@"
    ;;
  archive-market)
    if [ ! -x .venv/bin/python ]; then
      printf 'Python environment missing. First run: bash run.sh setup\n' >&2
      exit 2
    fi
    shift
    exec nice -n 10 .venv/bin/python -m workstation_api.market_session_archive "$@"
    ;;
  verify-v3)
    if [ ! -x .venv/bin/python ]; then
      printf 'Python environment missing. First run: bash run.sh setup\n' >&2
      exit 2
    fi
    shift
    exec nice -n 10 .venv/bin/python -m scripts.verify_ui_v3 "$@"
    ;;
  python-packages)
    shift
    exec bash scripts/research_packages.sh "$@"
    ;;
  setup|check|evaluate)
    exec bash scripts/start.sh "$1"
    ;;
  -h|--help|help)
    cat <<'HELP'
bash run.sh                  React/Vite quantitative research workstation (default)
bash run.sh workstation      Same as default; local Python API and Vite
bash run.sh research         Same as default
bash run.sh web              Same as default; NOT the old public showcase
bash run.sh both             Same workstation (API + React)
bash run.sh setup            Install local Python and Node dependencies
bash run.sh cross-index-research  Matched cross-index directional and volatility forecasts
bash run.sh candle-research    Next-candle pattern library and chronological direction forecasts\nbash run.sh cpr-repair        Test, repair expired option receipts, probe wider strikes and audit saved evidence\nbash run.sh cpr-next          Run CPR regression tests and execution evidence / development horizon screen\nbash run.sh cpr-context-check  Audit historical constituent and global context before option replay\nbash run.sh verify-v3 --scientific  Check isolated execution, scientific imports and local source health without restarting
bash run.sh python-packages check   Inspect approved scientific packages
bash run.sh python-packages install Install missing approved packages with local approval; no app restart
bash run.sh check            Existing research acceptance checks
bash run.sh evaluate         Existing synthetic evaluation and reports
bash run.sh verify-saved     Run all 35 models against saved original datasets; reuse saved chain
bash run.sh verify-saved --dataset dhan_shared  Verify shared Dhan data only
bash run.sh verify-saved --strict  Nonzero exit if any original inputs remain missing
bash run.sh audit-models     Read-only audit of every model and active dataset
bash run.sh audit-models --dataset dhan_shared  Audit shared Dhan only
bash run.sh audit-models --preflight-only  Check inputs without running models
bash run.sh cpr-research  CPR/EMA baseline, ML filter and offline-Q exits\nbash run.sh validate-trading  Off-hours saved-source trading validation; no broker requests\nbash run.sh archive-market --day YYYY-MM-DD  Verified non-destructive market archive (off-hours)
bash run.sh archive-market --verify PATH  Verify archive checksums and row counts
HELP
    ;;
  *)
    printf 'Unknown mode: %s\n' "$1" >&2
    exit 2
    ;;
esac
