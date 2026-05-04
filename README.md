# M3 — Me, Myself, Mine

A self-hosted personal knowledge OS. Share things from anywhere in your life. An LLM organizes it all into a living, evolving knowledge base you browse, graph, and chat with.

No prescribed structure. No manual organizing. The system learns how you think.

## What it does

1. **Capture** from anywhere: Telegram, WhatsApp, email, voice notes, screenshots, URLs, files
2. **Organize** automatically: an LLM reads what you share, writes wiki pages, creates connections
3. **Visualize** as an interactive knowledge graph
4. **Chat** with your entire brain from any device
5. **Discover** insights and connections you'd never find manually

## Architecture

M3 is a local-first desktop app, not a server stack. The `.app` is fully self-contained — it ships with the Python backend bundled inside as a wheel and maintains its own private virtualenv for runtime. There is no `pipx`, no `docker`, no manual install of the backend.

Internally:

- **Tauri shell** (Rust) — owns the window, runs the auto-updater, manages a private venv at `~/Library/Application Support/local.m3.app/runtime/venv` and reconciles it against the bundled `m3-*.whl` on every launch.
- **`m3` Python backend** — stores everything as plain markdown at `~/brain/` and exposes a local HTTP API. Spawned as a child process by the shell.
- **React client** — bundled inside the `.app`, served from the local API.

Earlier phases of the project used a Postgres + MinIO + Redis stack. That's been removed; the current build is filesystem-first.

## Install

### Prerequisites

- macOS 12+ or Linux (Windows via WSL)
- A `python3` (3.12+) on your system — the .app uses it to bootstrap its private venv on first launch. Bundling Python directly into the .app is the planned next step.
- An Anthropic API key, or another supported LLM provider

### From a release build (recommended)

Grab the latest `.app` (macOS) or `.AppImage` (Linux) from [Releases](https://github.com/yourusername/m3/releases) and drag it into `/Applications`. Launch it.

On first launch the app sets up its private runtime — this takes ~30s and shows a splash screen. Subsequent launches are instant. Updates land via the in-app **Restart now** banner; the entire stack (shell + Python backend + frontend) updates atomically.

### From source

```bash
git clone https://github.com/yourusername/m3.git
cd m3
./scripts/update.sh    # builds wheel, frontend, and .app in one shot
```

The bundle lands at `src-tauri/target/release/bundle/macos/M3.app` (or the Linux equivalent under `bundle/`). Drag it into `/Applications`.

## Updating

For end users: the app auto-checks for updates in the background once release endpoints are configured (see [Release setup](#release-setup-maintainers) below) and shows an in-app banner offering to relaunch when a new version is downloaded. One click restarts the app and reconciles the bundled Python backend automatically — there's nothing else to run.

For source builds:

```bash
./scripts/update.sh
```

That pulls the latest commits, rebuilds the m3 wheel into `src-tauri/resources/`, rebuilds the frontend, and rebuilds the desktop app. Your data at `~/brain/` is untouched across any update path.

## Configuration

On first run M3 creates `~/.config/m3/config.yml`. Set your LLM API key via the in-app **Settings** page (it's persisted to that file). For headless setups, edit the file directly.

## macOS Gatekeeper

Unsigned `.app` bundles trip Gatekeeper's "Apple cannot check this for malicious software" dialog. Until releases are signed and notarized, work around it with one of:

- Right-click the app, choose **Open**, then click **Open** again in the dialog
- `xattr -d com.apple.quarantine /Applications/M3.app`
- Install via Homebrew Cask once a tap is published (Cask strips the quarantine attribute automatically)

## Philosophy

- **Single-user, always.** One instance = one person.
- **Local-first.** Your brain is markdown on your disk. M3 is a lens, not a vault.
- **No prescribed structure.** The LLM discovers categories organically.
- **Open-core.** The platform is MIT. The advanced compilation engine is pluggable and lives in a separate repo.
- **LLM-agnostic.** Anthropic by default; OpenAI and any OpenAI-compatible endpoint work too.

## Release setup (maintainers)

The Tauri auto-updater needs two things wired up before it'll actually deliver updates:

1. **Generate a signing keypair** (one-time):
   ```bash
   cd src-tauri && cargo tauri signer generate -w ~/.tauri/m3.key
   ```
   Keep the private key safe (e.g. as a `TAURI_SIGNING_PRIVATE_KEY` GitHub Actions secret). Paste the public key into `src-tauri/tauri.conf.json` under `plugins.updater.pubkey`.

2. **Publish releases** to a stable URL. The simplest path is GitHub Releases — set `plugins.updater.endpoints` to a `latest.json` you upload alongside the `.app` and `.AppImage` artifacts. A minimal CI workflow looks like:
   ```yaml
   - uses: tauri-apps/tauri-action@v0
     env:
       TAURI_SIGNING_PRIVATE_KEY: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}
     with:
       tagName: v__VERSION__
       releaseName: 'M3 v__VERSION__'
   ```

Until both are configured, the updater is a no-op — the app still launches normally.

## License

MIT
