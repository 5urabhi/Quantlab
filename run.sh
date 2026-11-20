#!/usr/bin/env bash
# Local React/Vite + Python research workstation. Default is NOT Streamlit.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
case "${1:-workstation}" in
  workstation|research|web|both)
    exec bash scripts/run_workstation.sh
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
  legacy-streamlit)
    exec bash scripts/start.sh research
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
bash run.sh check            Existing research acceptance checks
bash run.sh evaluate         Existing synthetic evaluation and reports
bash run.sh audit-models     Read-only audit of every model and active dataset
bash run.sh audit-models --dataset dhan_shared  Audit shared Dhan only
bash run.sh audit-models --preflight-only  Check inputs without running models
bash run.sh legacy-streamlit Launch preserved legacy Streamlit UI if needed
HELP
    ;;
  *)
    printf 'Unknown mode: %s\n' "$1" >&2
    exit 2
    ;;
esac
