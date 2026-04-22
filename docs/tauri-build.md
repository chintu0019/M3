# Building the M3 desktop app

The desktop shell lives in `src-tauri/` and wraps the existing FastAPI + React app in a native window. It does NOT bundle Python — the shell expects the `m3` CLI to be installed separately. On startup it spawns `m3 start --port 7007` as a child process, waits for the server to come up, then loads the webview at `http://127.0.0.1:7007`. On window close it kills the child.

## Prerequisites

- **Rust**: install via `mise install rust` (recommended) or `curl https://sh.rustup.rs -sSf | sh`. Tauri needs `rustc >= 1.75`.
- **Tauri CLI**: `cargo install tauri-cli --version '^2'`
- **Platform toolchains**:
  - macOS: Xcode command-line tools (`xcode-select --install`)
  - Linux: `webkit2gtk`, `libayatana-appindicator`, `librsvg`, `libsoup`, `libjavascriptcoregtk-4.1-dev`. On Debian/Ubuntu: `sudo apt install libwebkit2gtk-4.1-dev build-essential curl wget file libssl-dev libayatana-appindicator3-dev librsvg2-dev`
- **m3 CLI**: `pipx install m3` (or symlink into `~/.local/bin`). The Tauri app searches `$PATH`, `/opt/homebrew/bin`, and `/usr/local/bin` for the `m3` binary.
- **Client bundle**: must exist at `client/dist/`. Run `cd client && npm run build` once.

## Dev run

```bash
cd src-tauri
cargo tauri dev
```

Launches a debug build with hot-reload. The Python server subprocess is spawned once per launch.

## Release build

```bash
cd src-tauri
cargo tauri build
```

Outputs:
- macOS: `src-tauri/target/release/bundle/macos/M3.app` and `src-tauri/target/release/bundle/dmg/M3_0.1.0_<arch>.dmg`
- Linux: `src-tauri/target/release/bundle/deb/m3-app_0.1.0_amd64.deb` and `src-tauri/target/release/bundle/appimage/m3-app_0.1.0_amd64.AppImage`

First build is ~10–20 minutes (downloading and compiling 400+ Rust crates). Incremental rebuilds are seconds.

## How it works

1. Tauri launches the compiled binary.
2. `setup` hook: looks for `m3` binary → `Command::new("m3 start --port 7007")` → pipes its stdout/stderr to the parent's terminal → stores the `Child` handle in Tauri state.
3. Polls `127.0.0.1:7007` until TCP opens (≤25s timeout); on failure, shows a native error dialog and quits.
4. Creates the main window with `navigate("http://127.0.0.1:7007")`.
5. On window close: state is dropped → child is killed.

If something else is already bound to port 7007, the shell assumes it's an existing M3 process and connects to it without spawning a new one.

## Customisation

- **Port**: change `DEFAULT_PORT` in `src-tauri/src/main.rs`. (Future: read from env or config.)
- **Icon**: replace the PNGs + `.icns` + `.ico` in `src-tauri/icons/`. They're generated placeholders — an actual designer can do better.
- **Window size**: edit the `windows[0]` object in `tauri.conf.json`.
- **Bundling Python**: replace `find_m3_binary` / `Command::new` with Tauri's sidecar mechanism. Requires `python-build-standalone` + the m3 wheel + deps packed into `src-tauri/binaries/`. Bundle size goes from ~15MB → ~60MB. See `https://tauri.app/v2/guide/building/sidecar/`.

## Troubleshooting

- **"M3 CLI not found on PATH"** → run `which m3` in a terminal; make sure that same PATH is inherited by the Tauri process. On macOS, launchd does NOT inherit login shell PATH, so `pipx` installs under `~/.local/bin` may be invisible. Fix: `sudo ln -s "$(which m3)" /usr/local/bin/m3`.
- **"M3 server startup timed out"** → Ollama isn't running, or `~/brain/` isn't initialized. Run `m3 init` and `ollama serve` separately, then relaunch the app.
- **Blank window** → client bundle missing. `cd client && npm run build` and rebuild the Tauri app.
- **Linux: `could not find webkit2gtk-4.1`** → install the platform toolchain packages listed above.
