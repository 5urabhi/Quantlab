#!/usr/bin/env bash
# Ubuntu local-first one-command bootstrap and launcher.
# Usage: bash scripts/start.sh [workstation|evaluate|check|setup]
# No Redis, Docker, global npm packages, GitHub Actions or Dhan token needed.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# Keep in-repository Python packages importable from API and helper scripts.
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
MODE="${1:-workstation}"
case "$MODE" in
  workstation|web|research|both)
    exec bash scripts/run_workstation.sh
    ;;
  check|setup|evaluate) ;;
  -h|--help|help)
    cat <<'HELP'
Usage: bash scripts/start.sh [workstation|check|evaluate|setup]

  workstation  DEFAULT: current React/Vite and FastAPI workstation.
  research, web, both  Compatibility aliases for the same workstation.
  check     Current React build, Python/integration and math checks, source doctor.
  evaluate  Run current checks, synthetic research and visual reports,
            writing artifacts to results/. No servers.
  setup     Prepare Python and frontend dependencies; start no servers.

Stop running servers with Ctrl+C.
Never paste Dhan tokens here; place them in the ignored .env file.
HELP
    exit 0 ;;
  *) printf 'Unknown mode: %s\n' "$MODE" >&2; exit 2 ;;
esac

info() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
command_exists() { command -v "$1" >/dev/null 2>&1; }

if [ "${EUID:-$(id -u)}" -eq 0 ]; then
  fail "Run this command as a normal user (not sudo). The script uses sudo only when required to install system packages."
fi
if ! command_exists apt-get; then
  fail "This automated bootstrap currently supports Ubuntu/Debian with apt-get. See GETTING_STARTED.md for other systems."
fi


install_apt_missing() {
  local packages=() package
  for package in "$@"; do
    if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed'; then
      packages+=("$package")
    fi
  done
  if [ "${#packages[@]}" -gt 0 ]; then
    command_exists sudo || fail "System packages missing (${packages[*]}) and sudo unavailable."
    info "Installing missing OS packages: ${packages[*]} (sudo may ask for password)"
    sudo apt-get update
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}"
  fi
}

info "Inspecting operating-system dependencies"
install_apt_missing git curl ca-certificates xz-utils

install_apt_missing python3 python3-venv python3-pip

PYTHON=python3
"$PYTHON" - <<'PY' || fail "Python >=3.11 is required. Update your distribution's Python interpreter."
import sys
assert sys.version_info >= (3,11), f"Python 3.11+ required; got {sys.version}"
PY

info "Preparing isolated Python research environment"
if [ ! -x .venv/bin/python ]; then
  "$PYTHON" -m venv .venv || fail "Unable to create .venv (check python3-venv package)."
fi
if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
  fail "Virtualenv pip missing. Remove .venv only if it contains no personal data, then retry."
fi

mkdir -p .local-state
REQ_HASH="$(sha256sum requirements.txt | awk '{print $1}')"
PY_TAG="$(.venv/bin/python -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
REQ_MARKER=".local-state/python-requirements.sha256"
EXPECTED_PY="$REQ_HASH:$PY_TAG"
CURRENT_PY="$(cat "$REQ_MARKER" 2>/dev/null || true)"
if [ "$CURRENT_PY" != "$EXPECTED_PY" ] || ! .venv/bin/python -c 'import numpy,pandas,scipy,plotly,reportlab,dotenv,fastapi,uvicorn' >/dev/null 2>&1; then
  info "Installing/updating local Python packages"
  .venv/bin/python -m pip install -r requirements.txt
  printf '%s\n' "$EXPECTED_PY" > "$REQ_MARKER"
else
  info "Python dependencies already available"
fi

if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  chmod 600 .env
  info "Created private .env template (Dhan token optional; edit with nano .env)"
fi
if [ -f .env ]; then chmod 600 .env; fi

# Use one compatible Node/npm pair for local builds. Node alone is not
# sufficient: npm 12.2 requires Node >=22.22.2, while user's 22.22.1 warns.
# The project-local fallback contains its OWN bundled npm, not global npm 12.
source "$ROOT/scripts/node_runtime.sh"
if ! quantlab_activate_node_runtime "$ROOT"; then
  fail "Unable to provision a compatible local Node/npm toolchain"
fi
if [ "$QUANTLAB_NODE_RUNTIME_CHOICE" = "portable" ]; then
  info "Global Node/npm pair is incompatible; using verified project-local Node LTS"
fi
info "Using Node $(node --version) and npm $(npm --version)"

mkdir -p .local-state
PKG_HASH="$(sha256sum package.json | awk '{print $1}')"
LOCK_HASH="none"
if [ -f package-lock.json ]; then LOCK_HASH="$(sha256sum package-lock.json | awk '{print $1}')"; fi
NPM_EXPECTED="$PKG_HASH:$LOCK_HASH:$(node --version):$(npm --version)"
NPM_MARKER=".local-state/npm-dependencies.sha256"
if [ "$(cat "$NPM_MARKER" 2>/dev/null || true)" != "$NPM_EXPECTED" ] || [ ! -x node_modules/.bin/vite ] || [ ! -x node_modules/.bin/tsc ]; then
  info "Installing/updating Vite/React packages"
  if [ -f package-lock.json ]; then
    npm ci --no-audit --no-fund
  else
    npm install --no-audit --no-fund
  fi
  LOCK_HASH="none"
  if [ -f package-lock.json ]; then LOCK_HASH="$(sha256sum package-lock.json | awk '{print $1}')"; fi
  printf '%s\n' "$PKG_HASH:$LOCK_HASH:$(node --version):$(npm --version)" > "$NPM_MARKER"
else
  info "Vite/React dependencies already available"
fi

# esbuild's optional native binary may be absent after an npm 12 install
# that blocked its postinstall script. Validate the real compiler every time.
# Do not bypass install-script policy globally or auto-approve other packages.
if ! node -e "const esbuild=require('esbuild'); const s=esbuild.transformSync('const answer = 42', {loader:'js'}).code; if(!s.includes('42')) process.exit(1)" >/dev/null 2>&1; then
  fail "esbuild native binary is unavailable. Re-run setup with the compatible toolchain; do not ignore blocked install scripts."
fi

info "Checking frontend TypeScript and production Vite build"
npm run build

if [ "$MODE" = setup ]; then
  info "Setup and build complete. Run: bash run.sh"
  exit 0
fi

if [ "$MODE" = check ] || [ "$MODE" = evaluate ]; then
  info "Testing CURRENT React/FastAPI research workstation and original-source readiness"
  .venv/bin/python scripts/local_acceptance.py --skip-build
  info "Running mathematical acceptance"
  MATH_DIR="results/math_acceptance_$(date +%Y%m%d_%H%M%S)_$$"
  .venv/bin/python scripts/verify_mathematics.py --output-dir "$MATH_DIR"
  if [ "$MODE" = evaluate ]; then
    info "Running clearly labeled synthetic factor experiment"
    if [ ! -f data/synthetic_example/prices.csv ]; then
      .venv/bin/python -m index_research.cli make-fixture --output-dir data/synthetic_example
    fi
    RUN_DIR="results/synthetic_$(date +%Y%m%d_%H%M%S)_$$"
    .venv/bin/python -m index_research.cli run --input-dir data/synthetic_example --output-dir "$RUN_DIR" --config config/research_multifactor.json
    VISUAL_DIR="results/visual_validation_$(date +%Y%m%d_%H%M%S)_$$"
    .venv/bin/python scripts/export_visual_validation.py --output-dir "$VISUAL_DIR"
    info "Synthetic results: $RUN_DIR"
    info "Visual report: $VISUAL_DIR"
  fi
  info "Software acceptance PASSED; original NSE/Dhan source review and empirical certification remain separate."
  info "Math evidence: $MATH_DIR"
  exit 0
fi

