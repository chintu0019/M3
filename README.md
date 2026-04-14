# M3 — Me, Myself, Mine

A self-hosted personal knowledge OS. Share things from anywhere in your life. An LLM organizes it all into a living, evolving knowledge base.

No prescribed structure. No manual organizing. The system learns how you think.

## What it does

1. **Capture** from anywhere: Telegram, WhatsApp, email, voice notes, screenshots, URLs, files
2. **Organize** automatically: an LLM reads what you share, writes wiki pages, creates connections
3. **Visualize** as an interactive knowledge graph
4. **Chat** with your entire brain from any device
5. **Discover** insights and connections you'd never find manually

## Quick Start

```bash
git clone https://github.com/yourusername/m3.git
cd m3
cp config.example.yml config.yml
# Edit config.yml with your API keys
docker compose up -d
```

## Requirements

- Docker + Docker Compose
- An Anthropic API key (or any LLM provider)
- A Telegram bot token (for mobile capture)

## Philosophy

- **Single-user, always.** One instance = one person.
- **No prescribed structure.** The LLM discovers categories organically.
- **Open-core.** Platform is MIT. Compilation engine is pluggable.
- **Self-hosted.** Your server, your data, your rules.
- **LLM-agnostic.** Claude by default, swap anytime via config.

## License

MIT
