# M3 — Me, Myself, Mine

A local-first personal knowledge OS. Forward things into M3, an LLM extracts
entities and atomic facts into a `~/brain/` markdown corpus, and you chat with
the result. Single-user. Open-source. Bring your own AI agent.

No prescribed structure. No manual organizing. The system learns how you think.

## What it does

1. **Capture** via direct upload (text, files) or a Telegram bot.
2. **Organize** automatically: an LLM extracts entities + facts into plain
   markdown under `~/brain/`, builds an entity graph, and surfaces a cluster
   visualization for each query.
3. **Chat** with your brain — the agent loop searches, opens entities, and
   cites the underlying items.
4. **Bring your own AI CLI.** Reuse the `claude`, `codex`, `gemini`, `aider`,
   `mods`, or `llm` CLI you already have logged in. No M3-managed API key.

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
- One of:
  - An **AI CLI you already have** (Claude Code, Codex, Gemini CLI, Aider, mods, llm). M3 detects it on PATH and reuses your existing login — no API key required.
  - An **Anthropic API key**, or
  - **Ollama** running locally.

If none of these are present, M3 still launches — it just shows a "pick an
agent" prompt in Settings and disables chat until you do.

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

On first run M3 creates `~/.config/m3/config.yml`. Use the in-app **Settings**
page (persisted there) for the common case; for headless setups edit the file
directly.

### Bring your own AI CLI

Settings → **Use my installed AI agent** lists every supported CLI it finds on
PATH. Click **Use this** for any of:

- **Claude Code** (`claude`) — Anthropic
- **Codex** (`codex`) — OpenAI
- **Gemini CLI** (`gemini`) — Google
- **Aider** (`aider`) — multi-backend coding agent
- **mods** (`mods`) — Charm's CLI; supports OpenAI + Anthropic
- **llm** (`llm`) — Simon Willison's plugin ecosystem

Authentication is whatever the CLI is already configured with. If you have a
Codex Plus subscription wired into the `codex` CLI, M3 picks it up the same
way it picks up Claude Code Max — no separate key in `~/.config/m3/`.

Got a CLI we don't list? Settings has a **Custom command** form: type the
binary name and a space-separated arg list, and the same provider runs it.
Anything that "accepts text on stdin, emits text on stdout" works.

The other two providers in Settings:

- **Ollama** — point at a local instance for fully offline inference.
- **Anthropic API** — paste an `sk-ant-…` key for direct API access. Best
  quality + native tool use, but requires Anthropic billing.

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
- **Bring your own AI agent.** M3 ships zero inference. Pick whichever CLI
  you already have logged in (Claude Code, Codex, Gemini, Aider, mods, llm)
  or plug in Anthropic / Ollama directly. Switch in one click in Settings.

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
