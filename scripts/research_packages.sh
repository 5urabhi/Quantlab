#!/usr/bin/env bash
# Fixed distribution package allowlist. No arbitrary pip or browser shell commands.
set -Eeuo pipefail
packages=(bubblewrap util-linux python3-numpy python3-pandas python3-scipy python3-matplotlib python3-sympy python3-statsmodels python3-sklearn)
if ! command -v dpkg-query >/dev/null || ! command -v apt-get >/dev/null; then
  printf 'This helper supports Ubuntu/Debian distribution packages only.\n' >&2
  exit 2
fi
mode="${1:-check}"
if [[ $# -gt 1 || ( "$mode" != check && "$mode" != install ) ]]; then
  printf 'Usage: bash run.sh python-packages [check|install]\n' >&2
  exit 2
fi
missing=()
for package in "${packages[@]}"; do
  status="$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)"
  if [[ "$status" == 'install ok installed' ]]; then
    printf 'Installed  %s\n' "$package"
  else
    printf 'Missing    %s\n' "$package"
    missing+=("$package")
  fi
done
if [[ "$mode" == check || ${#missing[@]} -eq 0 ]]; then
  exit 0
fi
printf 'Install only missing approved packages through your configured distribution repositories.\n'
printf 'This may use disk space and network bandwidth. QuantLab will not be stopped or restarted.\n'
if [[ ! -t 0 ]]; then
  printf 'Installation requires interactive local operator approval.\n' >&2
  exit 2
fi
read -r -p 'Continue with apt-get install? [y/N] ' answer
case "$answer" in y|Y|yes|YES) ;; *) printf 'Cancelled.\n'; exit 0 ;; esac
if [[ "$(id -u)" == 0 ]]; then
  apt-get install --no-upgrade "${missing[@]}"
else
  sudo apt-get install --no-upgrade "${missing[@]}"
fi
printf 'Package installation finished. Test isolated imports in Settings > Python Environment.\n'
