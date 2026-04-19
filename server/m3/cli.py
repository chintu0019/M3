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
