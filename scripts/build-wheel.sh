#!/usr/bin/env bash
# Build the m3 Python wheel and stage it in src-tauri/resources/ so the next
# `cargo tauri build` bundles it inside the .app.
#
# Run from the repo root:  ./scripts/build-wheel.sh
#
# The Tauri shell looks for `m3-*.whl` in its resource directory at launch
# and reconciles a private venv against it. Stale wheels are wiped first so
# we never bundle two versions side-by-side.
#
# We also copy client/dist into server/m3/_client_dist/ before the wheel is
# built so that the SPA assets ship inside the wheel — m3.app finds them via
# `Path(__file__).parent / "_client_dist"` at runtime. Without this, an
# installed (non-editable) m3 has no static files to serve and `/` returns
# `{"detail":"Not Found"}`.

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

step "Clearing setuptools build cache (server/build/, server/m3.egg-info/)"
# setuptools accumulates a copy of every file ever built into
# server/build/lib/, including stale client/dist asset hashes from prior
# vite builds. Without wiping it, the wheel ends up containing the union
# of all builds — old script bundles shipping alongside the current one,
# and the wheel's index.html may reference assets from a stale build that
# don't exist in the wheel anymore. Blank webview, hours of confusion.
rm -rf "$ROOT/server/build" "$ROOT/server/m3.egg-info"

DIST_SRC="$ROOT/client/dist"
DIST_DST="$ROOT/server/m3/_client_dist"

[[ -f "$DIST_SRC/index.html" ]] || die "client/dist/index.html missing — run \`cd client && npm run build\` first"

# Vite emits hashed JS/CSS bundles under client/dist/assets/. If that
# directory is missing or empty (e.g. CI runs build-wheel.sh before
# `npm run build`), the wheel ships only the two tracked stub files
# (index.html + manifest.json) and the FastAPI server crashes on boot
# with `Directory '_client_dist/assets' does not exist`. We failed
# this way silently for several CI releases — never again.
if [[ ! -d "$DIST_SRC/assets" ]] || [[ -z "$(ls -A "$DIST_SRC/assets" 2>/dev/null)" ]]; then
  die "client/dist/assets/ is empty — did you forget to run \`cd client && npm run build\` before this script?"
fi

step "Vendoring client/dist into the package as m3/_client_dist"
rm -rf "$DIST_DST"
cp -R "$DIST_SRC" "$DIST_DST"
ok "Vendored $(find "$DIST_DST" -type f | wc -l | tr -d ' ') files"

# Make sure the vendored copy is wiped after the wheel build, otherwise
# editable/dev installs would shadow the source-tree client/dist.
cleanup() { rm -rf "$DIST_DST"; }
trap cleanup EXIT

step "Building m3 wheel"
# `pip wheel --no-deps` is the smallest tool that gets us a PEP 517 wheel from
# server/pyproject.toml without pulling in the whole `build` package. Deps
# resolve at install-time inside the user's venv.
"$PYTHON" -m pip wheel --no-deps --wheel-dir "$RESOURCES" "$ROOT/server" >/dev/null

WHEEL="$(find "$RESOURCES" -maxdepth 1 -name 'm3-*.whl' -print -quit)"
[[ -n "$WHEEL" ]] || die "wheel build produced no m3-*.whl in $RESOURCES"

# Sanity-check that the SPA actually made it into the wheel. We avoid
# `grep -q` here — it would close the pipe early, SIGPIPE unzip, and (with
# pipefail) make the whole pipeline look failed.
WHEEL_LISTING="$(unzip -l "$WHEEL" 2>/dev/null)"
if [[ "$(echo "$WHEEL_LISTING" | grep -c 'm3/_client_dist/index\.html')" -eq 0 ]]; then
  die "wheel built but m3/_client_dist/index.html is missing — check pyproject package data"
fi
# The asset bundles (JS + CSS) live under m3/_client_dist/assets/. Without
# them the FastAPI app crashes at boot mounting StaticFiles. Catching this
# in build is much cheaper than chasing it from a user's logs.
if [[ "$(echo "$WHEEL_LISTING" | grep -c 'm3/_client_dist/assets/')" -eq 0 ]]; then
  die "wheel built but m3/_client_dist/assets/ is empty — frontend probably wasn't built before this script ran"
fi

ok "Built $(basename "$WHEEL") ($(du -h "$WHEEL" | awk '{print $1}'))"
