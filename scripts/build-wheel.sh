#!/usr/bin/env bash
# Build the m3 Python wheel and stage it in src-tauri/resources/ so the next
# `cargo tauri build` bundles it inside the .app.
#
# Run from the repo root:  ./scripts/build-wheel.sh
#
# The Tauri shell looks for `m3-*.whl` in its resource directory at launch
# and reconciles a private venv against it. Stale wheels are wiped first so
# we never bundle two versions side-by-side.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

step() { printf "\n\033[1;36m▸ %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✓ %s\033[0m\n" "$*"; }
die()  { printf "\033[1;31m✗ %s\033[0m\n" "$*" >&2; exit 1; }

PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null 2>&1 || die "python3 not found on PATH (override with PYTHON=...)"

RESOURCES="$ROOT/src-tauri/resources"
mkdir -p "$RESOURCES"

step "Clearing stale wheels in $RESOURCES"
rm -f "$RESOURCES"/*.whl

step "Building m3 wheel"
# `pip wheel --no-deps` is the smallest tool that gets us a PEP 517 wheel from
# server/pyproject.toml without pulling in the whole `build` package. Deps
# resolve at install-time inside the user's venv.
"$PYTHON" -m pip wheel --no-deps --wheel-dir "$RESOURCES" "$ROOT/server" >/dev/null

WHEEL="$(find "$RESOURCES" -maxdepth 1 -name 'm3-*.whl' -print -quit)"
[[ -n "$WHEEL" ]] || die "wheel build produced no m3-*.whl in $RESOURCES"
ok "Built $(basename "$WHEEL")"
