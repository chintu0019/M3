"""M3 command-line interface."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

import typer

from m3.brain.layout import init_brain
from m3.core.extract import ExtractionOutput
from m3.core.ingest import IngestInput, Ingester

app = typer.Typer(help="M3 personal brain CLI.")


def _default_brain() -> Path:
    return Path(os.environ.get("M3_BRAIN", str(Path.home() / "brain")))


@app.command()
def init(brain: Path = typer.Option(None, "--brain", help="Path to the brain directory.")):
    """Create or upgrade a brain directory."""
    target = brain or _default_brain()
    init_brain(target)
    typer.echo(f"initialized brain at {target}")


@app.command()
def ingest(
    path: Path = typer.Argument(..., help="Path to the file to ingest."),
    brain: Path = typer.Option(None, "--brain", help="Brain directory."),
    source: str = typer.Option("cli", "--source", help="Capture channel."),
):
    """Ingest one item into the brain."""
    brain_root = brain or _default_brain()
    if not (brain_root / "self.md").exists():
        typer.echo(
            f"brain at {brain_root} is not initialized; run `m3 init` first",
            err=True,
        )
        raise typer.Exit(code=1)

    text = path.read_text() if path.suffix in {".txt", ".md"} else ""
    original_bytes = path.read_bytes() if path.suffix not in {".txt", ".md"} else None

    llm = _make_llm()
    embedder = _make_embedder()
    ingester = Ingester(brain_root=brain_root, llm=llm, embedder=embedder)

    out = asyncio.run(
        ingester.ingest(
            IngestInput(
                item_id=uuid.uuid4(),
                source=source,
                original_bytes=original_bytes,
                original_filename=path.name,
                content_type=_guess_content_type(path),
                text=text,
            )
        )
    )
    typer.echo(
        f"ingested {out.item_id}: kind={out.kind} "
        f"confidence={out.confidence:.2f} self={out.self_touched} "
        f"entities={out.entities_touched} questions={out.questions_raised}"
    )


def _guess_content_type(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    if ext in {"txt", "md"}:
        return "text"
    if ext in {"pdf"}:
        return "pdf"
    if ext in {"png", "jpg", "jpeg", "webp", "gif"}:
        return "image"
    if ext in {"m4a", "mp3", "wav", "ogg"}:
        return "audio"
    return "file"


def _make_llm():
    """Pick an LLM provider from M3_LLM_PROVIDER. Supports: ollama | anthropic | fake."""
    provider = os.environ.get("M3_LLM_PROVIDER", "ollama").lower()
    if provider == "fake":
        return _FakeLLM()
    if provider == "ollama":
        from m3.core.llm.ollama import OllamaProvider

        return OllamaProvider(
            host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
            model=os.environ.get("OLLAMA_MODEL", "qwen2.5:14b"),
        )
    if provider == "anthropic":
        from m3.core.llm.anthropic import AnthropicProvider

        return AnthropicProvider(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        )
    raise typer.BadParameter(f"unknown M3_LLM_PROVIDER: {provider!r}")


def _make_embedder():
    from m3.core.llm.embeddings import FastEmbedProvider

    # Default 768-dim model matches VECTOR_DIM. If initialization fails (model
    # download, ONNX issues) we let it bubble up rather than silently swap in
    # a no-op embedder that would corrupt the vector index.
    return FastEmbedProvider()


@app.command()
def search(
    query: str = typer.Argument(..., help="Fragment to search for."),
    brain: Path = typer.Option(None, "--brain", help="Brain directory."),
    k: int = typer.Option(10, "--k", help="Max number of results."),
):
    """Search the brain by fragment."""
    import asyncio as _asyncio
    from m3.core.retrieve import Retriever
    brain_root = brain or _default_brain()
    if not (brain_root / "self.md").exists():
        typer.echo(f"brain at {brain_root} is not initialized", err=True)
        raise typer.Exit(code=1)
    retriever = Retriever(brain_root=brain_root, embedder=_make_embedder())
    hits = _asyncio.run(retriever.search(query, k=k))
    if not hits:
        typer.echo("(no hits)")
        return
    for i, h in enumerate(hits, 1):
        typer.echo(f"{i}. [{h.kind}] {h.when_iso or '----'} — {h.excerpt}")
        for r in h.reasons:
            typer.echo(f"     · {r}")
        typer.echo(f"     id: {h.item_id}  score: {h.score:.3f}")


@app.command()
def reindex(
    brain: Path = typer.Option(None, "--brain", help="Brain directory."),
):
    """Rebuild FTS, hook, and vector indexes from items/meta."""
    import asyncio as _asyncio
    from m3.brain.reindex import reindex_all
    brain_root = brain or _default_brain()
    if not (brain_root / "self.md").exists():
        typer.echo(f"brain at {brain_root} is not initialized", err=True)
        raise typer.Exit(code=1)
    result = _asyncio.run(reindex_all(brain_root, embedder=_make_embedder()))
    typer.echo(f"indexed {result.items_indexed} items")
    if result.errors:
        for e in result.errors:
            typer.echo(f"  error: {e}", err=True)


@app.command()
def start(
    brain: Path = typer.Option(None, "--brain", help="Brain directory."),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host."),
    port: int = typer.Option(7007, "--port", help="Bind port."),
):
    """Start the local M3 server."""
    import os as _os
    if brain:
        _os.environ["M3_BRAIN"] = str(brain)
    _os.environ["M3_HOST"] = host
    _os.environ["M3_PORT"] = str(port)
    from m3.app import run as _run
    _run()


telegram_app = typer.Typer(
    help="Telegram capture — ingest messages from a personal bot.",
    invoke_without_command=True,
    no_args_is_help=False,
)
app.add_typer(telegram_app, name="telegram")


@telegram_app.callback()
def _telegram_default(ctx: typer.Context):
    """Default action when `m3 telegram` is run with no subcommand: start the bot."""
    if ctx.invoked_subcommand is not None:
        return
    import asyncio as _asyncio
    from m3.capture.telegram import run as _tg_run
    from m3.core import config as _cfg
    if not _cfg.telegram_token():
        typer.echo("No Telegram bot configured yet. Run `m3 telegram init` to set one up.", err=True)
        raise typer.Exit(code=1)
    try:
        _asyncio.run(_tg_run())
    except KeyboardInterrupt:
        typer.echo("\ntelegram bot stopped")


@telegram_app.command("init")
def telegram_init():
    """First-run wizard. Creates a bot config in ~/.config/m3/config.yml."""
    import asyncio as _asyncio
    from m3.capture.telegram_setup import run_wizard
    try:
        code = _asyncio.run(run_wizard())
    except KeyboardInterrupt:
        typer.echo("\naborted")
        code = 130
    raise typer.Exit(code=code)


@telegram_app.command("install-service")
def telegram_install_service():
    """Install `m3 start` + `m3 telegram` as a background service that runs on login.

    macOS: ~/Library/LaunchAgents/local.m3.{server,telegram}.plist
    Linux: ~/.config/systemd/user/m3-{server,telegram}.service
    """
    from m3.capture.telegram_service import ServiceError, install
    try:
        paths = install()
    except ServiceError as e:
        typer.echo(f"install failed: {e}", err=True)
        raise typer.Exit(code=1)
    typer.echo("installed:")
    for p in paths:
        typer.echo(f"  {p}")


@telegram_app.command("uninstall-service")
def telegram_uninstall_service():
    """Remove the m3 launchd / systemd units installed by install-service."""
    from m3.capture.telegram_service import ServiceError, uninstall
    try:
        paths = uninstall()
    except ServiceError as e:
        typer.echo(f"uninstall failed: {e}", err=True)
        raise typer.Exit(code=1)
    if not paths:
        typer.echo("no m3 services were installed; nothing to remove.")
        return
    typer.echo("removed:")
    for p in paths:
        typer.echo(f"  {p}")


@telegram_app.command("status")
def telegram_status():
    """Show the effective Telegram config (token redacted)."""
    from m3.core import config as _cfg
    token = _cfg.telegram_token()
    chats = _cfg.telegram_allowed_chats()
    server = _cfg.telegram_server_url()
    typer.echo(f"token:       {'<set>' if token else '(not configured — run `m3 telegram init`)'}")
    typer.echo(f"allow-list:  {sorted(chats) if chats else '(open — anyone)'}")
    typer.echo(f"server-url:  {server}")
    typer.echo(f"config path: {_cfg.config_path()}")


class _FakeLLM:
    supports_tools = True
    supports_vision = False
    supports_audio = False

    async def complete_tool(
        self,
        messages,
        tools,
        system=None,
        tool_choice=None,
        max_tokens=4096,
        temperature=0.2,
    ):
        from m3.core.llm.base import ToolResult

        minimal: dict[str, Any] = {
            "kind": "personal",
            "interpretation": {
                "what_happened": "fake-llm placeholder output",
                "when": {"iso": None, "source": "unknown"},
                "confidence": 0.0,
            },
            "open_questions": [],
            "hooks": {},
            "self_updates": [],
            "entity_updates": [],
        }
        ExtractionOutput.model_validate(minimal)  # assert schema-valid
        return ToolResult(tool_name=tool_choice or "process_item", input=minimal)
