#!/usr/bin/env bash
# Update an existing source-built M3 install in place.
#
# Pulls latest, builds the m3 wheel into src-tauri/resources/, rebuilds the
# React bundle, and rebuilds the Tauri desktop app. The user's data at
# ~/brain/ is never touched.
#
# Run from the repo root:  ./scripts/update.sh
#
# The .app fully self-contains its Python install at runtime — there is no
# pipx step here. The shell maintains its own venv at
# ~/Library/Application Support/local.m3.app/runtime/venv (Mac) and reconciles
# it on launch against the wheel bundled inside the .app.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

step() { printf "\n\033[1;36m▸ %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✓ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m! %s\033[0m\n" "$*"; }
die()  { printf "\033[1;31m✗ %s\033[0m\n" "$*" >&2; exit 1; }

require() { command -v "$1" >/dev/null 2>&1 || die "Missing prerequisite: $1"; }

step "Checking prerequisites"
require git
require python3
require npm
require cargo
ok "All required tools found"

step "Pulling latest from origin"
if [[ -n "$(git status --porcelain)" ]]; then
  warn "Working tree has uncommitted changes — skipping git pull"
  warn "Stash or commit your changes, then re-run if you want the latest source"
else
  git pull --ff-only
  ok "Repo up to date at $(git rev-parse --short HEAD)"
fi

step "Building m3 wheel into src-tauri/resources/"
"$ROOT/scripts/build-wheel.sh"

step "Rebuilding React frontend bundle"
( cd client && npm install --no-audit --no-fund && npm run build )
ok "Frontend bundle ready at client/dist"

step "Rebuilding Tauri desktop app"
( cd src-tauri && cargo tauri build )

# Find the freshly built bundle and tell the user where it is.
BUNDLE_DIR="$ROOT/src-tauri/target/release/bundle"
case "$(uname -s)" in
  Darwin)
    APP_PATH="$(find "$BUNDLE_DIR/macos" -maxdepth 1 -name '*.app' -print -quit 2>/dev/null || true)"
    if [[ -n "$APP_PATH" ]]; then
      ok "Built: $APP_PATH"
      echo
      echo "  To replace your installed copy:"
      echo "    rm -rf /Applications/M3.app && cp -R \"$APP_PATH\" /Applications/"
    fi
    ;;
  Linux)
    APPIMAGE="$(find "$BUNDLE_DIR/appimage" -maxdepth 1 -name '*.AppImage' -print -quit 2>/dev/null || true)"
    DEB="$(find "$BUNDLE_DIR/deb" -maxdepth 2 -name '*.deb' -print -quit 2>/dev/null || true)"
    [[ -n "$APPIMAGE" ]] && ok "Built: $APPIMAGE"
    [[ -n "$DEB" ]]      && ok "Built: $DEB"
    ;;
esac

step "Done"
echo "Your data at ~/brain/ is untouched. Launch the new app and it will"
echo "reconcile its private venv against the bundled wheel automatically."
