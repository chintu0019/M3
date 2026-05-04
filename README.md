# M3 — Me, Myself, Mine

A self-hosted personal knowledge OS. Forward things into M3, an LLM organizes
them into an entity-centric knowledge graph, and you chat with the result.
Single-user. Open-source. Your data, your server, your model.

## What it does

- **Capture** via direct upload (text, files, URLs) or a Telegram bot.
- **Organize** automatically: an LLM extracts entities and atomic facts,
  resolves "Kato" against "Kato AI" the way a person would, and renders a
  living wiki page per entity from the facts you've captured.
- **Visualize** the result as an interactive force-directed graph — every
  entity is a node, every co-occurrence or semantic edge is a link.
- **Chat** with your knowledge base; responses cite the entity pages and raw
  documents they came from.
- **Bring your own agent.** Point M3 at the Claude Code CLI you already have
  logged in (no API key needed), or plug in any Anthropic / OpenAI-compatible
  provider.

## Quick start

```bash
git clone https://github.com/chintu0019/m3.git
cd m3
./scripts/setup.sh
```

`setup.sh` probes for free host ports, writes them to `.env`, generates a M3
API key, and brings the stack up with `docker compose up -d --build`. It
prints the URL and API key when it's done.

Once the UI is up:

1. Paste the M3 API key in Settings.
2. Pick an AI agent. Either:
   - **Use my installed agent** — if the `claude` CLI (Claude Code) is on the
     server's PATH, hit "Use this." No API key required. Codex and Gemini
     CLIs are detected the same way.
   - **Add a provider** — Anthropic, OpenRouter, Groq, Together, MiniMax,
     Ollama, or any OpenAI-compatible endpoint. Paste a key and switch.
3. Drop something into Documents and watch the Workspace graph fill in.

If no agent is configured, the server still boots — the UI shows a "pick
one" prompt and chat is disabled until you do.

## Requirements

- Docker + Docker Compose
- One of:
  - The `claude` CLI installed and logged in on the server, or
  - An API key for any supported LLM provider

That's it. No GPU, no local model server, no Anthropic key required.

## Capture channels

| Channel             | Status                                            |
|---------------------|---------------------------------------------------|
| Direct upload (UI)  | Works — text, files, URLs                         |
| Telegram bot        | Works — set `TELEGRAM_BOT_TOKEN` in `.env`        |
| WhatsApp / email    | Not implemented                                   |
| Browser extension   | Not implemented                                   |

## UI

Two sections, plus a settings gear:

- **Documents** — every raw item you've captured, with status, retry, delete.
- **Workspace** — the entity graph + chat in one screen. Click a node for
  the rendered wiki page; type in the chat rail to query your knowledge.

## Configuration

All configuration lives in `config.yml` and `.env`. Defaults work out of the
box. Common overrides:

```yaml
# config.yml
llm:
  default_provider: local_agent  # uses the `claude` CLI by default
  providers:
    local_agent:
      type: local_agent
      command: claude
      args: ["-p"]
    claude:
      type: anthropic
      api_key: ""                 # set ANTHROPIC_API_KEY in .env
      model: claude-sonnet-4-20250514
```

```bash
# .env (excerpt -- setup.sh fills these in)
M3_API_KEY=...                    # generated for you
ANTHROPIC_API_KEY=                # optional, only if using the API
M3_HTTP_PORT=80                   # auto-set by setup.sh
M3_API_PORT=8000                  # auto-set by setup.sh
```

Environment variables follow Pydantic's nested form:
`M3_LLM__DEFAULT_PROVIDER=local_agent`,
`M3_CAPTURE__TELEGRAM__BOT_TOKEN=...`. Anything in `config.yml` is overridable
this way.

## Philosophy

- **Single-user, always.** One instance, one person.
- **No prescribed structure.** Entities and types emerge from your content.
- **BYO inference.** M3 ships zero models. Bring your own agent or API key.
- **Self-hosted.** Your server, your data, your rules. No telemetry.
- **Open-core.** Platform is MIT. The compilation engine is pluggable; a
  separate private engine can be loaded via `processing.engine_path`.

## License

MIT.
