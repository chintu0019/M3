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

step "Rebuilding React frontend bundle"
( cd client && npm install --no-audit --no-fund && npm run build )
ok "Frontend bundle ready at client/dist"

step "Building m3 wheel into src-tauri/resources/"
# Must run AFTER the frontend build: build-wheel.sh vendors client/dist into
# server/m3/_client_dist before packaging the wheel. If the order is flipped
# the wheel embeds whatever stale dist was lying around, and the running
# Python server ends up serving an index.html that references script hashes
# that no longer exist — leaving the webview blank on launch.
"$ROOT/scripts/build-wheel.sh"

step "Rebuilding Tauri desktop app"
# On macOS, Tauri's DMG bundler creates a writable temp image
# (rw.<pid>.<name>.dmg) and mounts it under /Volumes/dmg.XXXX while copying
# the .app inside. If a previous build was killed mid-bundle, that mount
# is left behind and the next `cargo tauri build` fails with
# "failed to run bundle_dmg.sh" because hdiutil refuses to attach an image
# that's already mounted. Detach any leftovers belonging to *this* build
# tree before invoking cargo, so a single rerun unsticks the loop.
if [[ "$(uname -s)" == "Darwin" ]]; then
  MAC_BUNDLE_DIR="$ROOT/src-tauri/target/release/bundle/macos"
  if [[ -d "$MAC_BUNDLE_DIR" ]]; then
    while IFS= read -r stuck_image; do
      [[ -z "$stuck_image" ]] && continue
      stuck_dev="$(hdiutil info | awk -v img="$stuck_image" '
        /^image-path/ { p = ($NF == img) }
        p && /^\/dev\/disk[0-9]+[[:space:]]+GUID/ { print $1; exit }
      ')"
      if [[ -n "$stuck_dev" ]]; then
        warn "Detaching stale DMG mount $stuck_dev ($stuck_image)"
        hdiutil detach "$stuck_dev" -force >/dev/null 2>&1 || true
      fi
      rm -f "$stuck_image"
    done < <(find "$MAC_BUNDLE_DIR" -maxdepth 1 -name 'rw.*.dmg' 2>/dev/null)
  fi
fi
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
