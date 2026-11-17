#!/usr/bin/env bash
# Sourced by start.sh AND run_workstation.sh; do not execute directly.
# Fix the local Ubuntu Node/npm PAIR without modifying global packages.
# Node 22.23.5 is the November 11, 2026 LTS security release and bundles
# npm 10.9.9, which allows esbuild's normal verified install lifecycle.
QUANTLAB_PORTABLE_NODE_VERSION="v22.23.5"

quantlab_node_compatible() {
  local root="$1" node_version npm_version
  command -v node >/dev/null 2>&1 || return 1
  command -v npm >/dev/null 2>&1 || return 1
  node_version="$(node --version 2>/dev/null)" || return 1
  # npm 12 warns during even 'npm --version' if the Node patch is too old.
  # Capture the version and suppress the warning ONLY during detection.
  npm_version="$(npm --version 2>/dev/null)" || return 1
  node "$root/scripts/node_runtime_compat.mjs" "$node_version" "$npm_version" >/dev/null 2>&1
}

quantlab_activate_node_runtime() {
  local root="$1" mode="${2:-install}" arch dist folder url tmp
  QUANTLAB_NODE_RUNTIME_CHOICE="system"
  if quantlab_node_compatible "$root"; then
    return 0
  fi
  case "$(uname -m)" in
    x86_64|amd64) arch="x64" ;;
    aarch64|arm64) arch="arm64" ;;
    *) printf 'ERROR: Portable Node LTS is unsupported on architecture %s.\n' "$(uname -m)" >&2; return 1 ;;
  esac
  dist="node-${QUANTLAB_PORTABLE_NODE_VERSION}-linux-${arch}"
  folder="$root/.local-tools/$dist"
  if [ ! -x "$folder/bin/node" ] || [ ! -x "$folder/bin/npm" ]; then
    if [ "$mode" = "offline" ]; then
      printf 'ERROR: Portable Node/npm was not installed by the setup stage.\n' >&2
      return 1
    fi
    mkdir -p "$root/.local-tools"
    tmp="$(mktemp -d)" || return 1
    url="https://nodejs.org/dist/${QUANTLAB_PORTABLE_NODE_VERSION}"
    if ! curl --fail --location --silent --show-error --retry 3 --connect-timeout 15 \
        "$url/SHASUMS256.txt" -o "$tmp/SHASUMS256.txt" ||
       ! curl --fail --location --silent --show-error --retry 3 --connect-timeout 15 \
        "$url/$dist.tar.xz" -o "$tmp/$dist.tar.xz"; then
      rm -rf "$tmp"
      printf 'ERROR: Cannot download official Node LTS. Check your connection.\n' >&2
      return 1
    fi
    if ! (cd "$tmp" && grep -F "  $dist.tar.xz" SHASUMS256.txt > selected.sha &&
          sha256sum -c selected.sha); then
      rm -rf "$tmp"
      printf 'ERROR: Official Node LTS SHA-256 verification failed.\n' >&2
      return 1
    fi
    if ! tar -xJf "$tmp/$dist.tar.xz" -C "$root/.local-tools"; then
      rm -rf "$tmp"
      printf 'ERROR: Could not extract verified local Node LTS.\n' >&2
      return 1
    fi
    rm -rf "$tmp"
  fi
  export PATH="$folder/bin:$PATH"
  QUANTLAB_NODE_RUNTIME_CHOICE="portable"
  if ! quantlab_node_compatible "$root"; then
    printf 'ERROR: The verified portable Node/npm pair is not compatible.\n' >&2
    return 1
  fi
  return 0
}
