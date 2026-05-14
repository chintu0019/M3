"""M3 command-line interface."""

from __future__ import annotations

import asyncio
import json
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
    """Create or upgrade a brain directory.

    Also pre-warms the local embedding model so the first `m3 start` doesn't
    block for several minutes downloading ~250 MB while the desktop shell's
    startup-timeout dialog counts down.
    """
    target = brain or _default_brain()
    init_brain(target)
    typer.echo(f"initialized brain at {target}")

    # Pre-warm the embedding model. Doing it here (instead of lazily on the
    # first request) means a botched download fails `m3 init` loudly, not the
    # next `m3 start` silently.
    from m3.core.llm.embeddings import FastEmbedProvider, default_model_cache_dir
    cache_dir = default_model_cache_dir()
    typer.echo(f"preparing embedding model in {cache_dir} (one-time ~250 MB download)…")
    try:
        FastEmbedProvider()
    except Exception as e:
        typer.echo(
            f"warning: embedding model download failed: {e}\n"
            "the server will retry on first start; re-run `m3 init` if it keeps failing.",
            err=True,
        )
    else:
        typer.echo("embedding model ready")


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
    """Pick an LLM provider from config (env > config.yml > default).

    Supports: ollama | anthropic | local_agent | fake. The `fake` provider is
    only selected via M3_LLM_PROVIDER=fake and is used by smoke tests. The
    server path in app.py wraps construction failures in UnconfiguredProvider;
    here we surface them as typer.BadParameter so the CLI exits with a clear
    message.
    """
    from m3.core import config as _cfg
    # `fake` is env-only (never persisted to config.yml).
    if os.environ.get("M3_LLM_PROVIDER", "").lower() == "fake":
        return _FakeLLM()
    provider = _cfg.llm_provider().lower()
    if provider == "ollama":
        from m3.core.llm.ollama import OllamaProvider
        return OllamaProvider(host=_cfg.ollama_host(), model=_cfg.ollama_model())
    if provider == "anthropic":
        key = _cfg.anthropic_api_key()
        if not key:
            raise typer.BadParameter("anthropic provider selected but no API key configured")
        from m3.core.llm.anthropic import AnthropicProvider
        return AnthropicProvider(api_key=key, model=_cfg.anthropic_model())
    if provider == "local_agent":
        from m3.core.llm.local_agent import LocalAgentProvider
        try:
            return LocalAgentProvider(
                command=_cfg.local_agent_command(),
                args=_cfg.local_agent_args(),
            )
        except RuntimeError as e:
            raise typer.BadParameter(str(e))
    raise typer.BadParameter(f"unknown LLM provider: {provider!r}")


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
    topical: bool = typer.Option(
        False,
        "--topical",
        help="Rebuild only the topical signatures index used by the canvas v2 force layout.",
    ),
    labels: bool = typer.Option(
        False,
        "--labels",
        help="Backfill ItemMeta.title (deterministic) and ClaimMeta.headline (LLM call per claim).",
    ),
):
    """Rebuild FTS, hook, and vector indexes from items/meta.

    With ``--topical`` runs ONLY the topical signature backfill (the
    canvas v2 force-layout index) — does not touch FTS / hook / vector.
    Use this once on existing brains whose entities, claims, and
    syntheses predate the topical-refresh ingest hooks.

    With ``--labels`` walks every item / claim and backfills the
    ``title`` / ``headline`` fields used by the canvas v2 nodes — items
    deterministically (frontmatter title / first line / filename stem)
    and claims via a small LLM call per claim. Skips records that
    already have the field set so reruns are idempotent.
    """
    import asyncio as _asyncio
    brain_root = brain or _default_brain()
    if not (brain_root / "self.md").exists():
        typer.echo(f"brain at {brain_root} is not initialized", err=True)
        raise typer.Exit(code=1)

    if labels:
        n_items, n_claims, errors = _asyncio.run(_reindex_labels(brain_root, _make_llm()))
        typer.echo(f"updated {n_items} item titles and {n_claims} claim headlines.")
        for e in errors:
            typer.echo(f"  error: {e}", err=True)
        return

    if topical:
        n, errors = _asyncio.run(_reindex_topical(brain_root, _make_embedder()))
        typer.echo(f"refreshed {n} topical signatures.")
        for e in errors:
            typer.echo(f"  error: {e}", err=True)
        return

    from m3.brain.reindex import reindex_all
    result = _asyncio.run(reindex_all(brain_root, embedder=_make_embedder()))
    typer.echo(f"indexed {result.items_indexed} items")
    if result.errors:
        for e in result.errors:
            typer.echo(f"  error: {e}", err=True)


async def _reindex_labels(brain_root: Path, llm) -> tuple[int, int, list[str]]:
    """Backfill item titles (deterministic) and claim headlines (LLM).

    Walks every persisted item / claim. Items get ``title`` filled from
    ``extract_title`` (frontmatter > first non-empty line > filename
    stem) — no LLM. Claims get ``headline`` from a single
    ``generate_headline`` LLM call each. Records that already have the
    field set are skipped, so reruns are idempotent. Per-record errors
    are collected and reported instead of aborting the walk.
    """
    from m3.brain.claims import iter_claims, write_claim
    from m3.brain.items import iter_metas, write_meta
    from m3.core.headline import generate_headline
    from m3.core.item_title import extract_title

    n_items = 0
    n_claims = 0
    errors: list[str] = []

    for meta in iter_metas(brain_root):
        if meta.title:
            continue
        new_title = extract_title(meta.extracted_text, meta.original_filename)
        if not new_title:
            continue
        meta.title = new_title
        try:
            write_meta(brain_root, meta)
            n_items += 1
        except Exception as e:
            errors.append(f"item:{meta.id}: {e}")

    for claim in iter_claims(brain_root):
        if claim.headline:
            continue
        try:
            new_headline = await generate_headline(proposition=claim.proposition, llm=llm)
            if new_headline:
                claim.headline = new_headline
                write_claim(brain_root, claim)
                n_claims += 1
        except Exception as e:
            errors.append(f"claim:{claim.id}: {e}")

    return n_items, n_claims, errors


async def _reindex_topical(brain_root: Path, embedder) -> tuple[int, list[str]]:
    """Walk every entity / item / claim / synthesis in the brain and refresh
    its topical signature. Returns (count, errors).

    Opens the TopicalIndex once for the whole backfill (so we don't reload
    the sqlite-vec extension + re-run CREATE VIRTUAL TABLE for every record)
    and passes it to each refresh helper. Per-record errors are collected
    rather than aborting the walk, matching the pattern in reindex_all.

    Kept private because it's only here to back the `--topical` flag — the
    canonical entry points for individual records are the per-type
    refresh helpers in m3.core.topical, called from the ingest pipeline.
    """
    from m3.brain import entity_doc
    from m3.brain.claims import iter_claims
    from m3.brain.items import iter_metas
    from m3.brain.layout import BrainPaths
    from m3.brain.synthesis import iter_syntheses
    from m3.brain.topical import TopicalIndex
    from m3.core.topical import (
        refresh_for_claim,
        refresh_for_entity,
        refresh_for_item,
        refresh_for_synthesis,
    )

    n = 0
    errors: list[str] = []
    idx = TopicalIndex.open(brain_root)
    try:
        # Entities — no iter_entities helper, so glob the dossier dir and reload.
        entities_dir = BrainPaths(brain_root).entities_dir
        if entities_dir.exists():
            for f in sorted(entities_dir.glob("*.md")):
                slug = f.stem
                doc = entity_doc.load(brain_root, slug=slug)
                if doc is None:
                    continue
                try:
                    await refresh_for_entity(
                        brain_root=brain_root, slug=slug, doc=doc,
                        embedder=embedder, idx=idx,
                    )
                    n += 1
                except Exception as e:
                    errors.append(f"entity:{slug}: {e}")

        for meta in iter_metas(brain_root):
            try:
                await refresh_for_item(
                    brain_root=brain_root,
                    item_id=meta.id,
                    extracted_text=meta.extracted_text,
                    embedder=embedder,
                    idx=idx,
                )
                n += 1
            except Exception as e:
                errors.append(f"item:{meta.id}: {e}")

        for claim in iter_claims(brain_root):
            try:
                await refresh_for_claim(
                    brain_root=brain_root, claim=claim, embedder=embedder, idx=idx,
                )
                n += 1
            except Exception as e:
                errors.append(f"claim:{claim.id}: {e}")

        for synth in iter_syntheses(brain_root):
            try:
                await refresh_for_synthesis(
                    brain_root=brain_root, synth=synth, embedder=embedder, idx=idx,
                )
                n += 1
            except Exception as e:
                errors.append(f"synthesis:{synth.entity_slug}: {e}")
    finally:
        idx.close()

    return n, errors


@app.command()
def start(
    brain: Path = typer.Option(None, "--brain", help="Brain directory."),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host."),
    port: int = typer.Option(7007, "--port", help="Bind port."),
    parent_pid: int = typer.Option(
        None, "--parent-pid",
        help="If set, exit when this PID disappears. Used by the desktop shell "
             "so a force-killed Tauri parent doesn't leave a stranded server.",
    ),
):
    """Start the local M3 server."""
    import os as _os
    if brain:
        _os.environ["M3_BRAIN"] = str(brain)
    _os.environ["M3_HOST"] = host
    _os.environ["M3_PORT"] = str(port)
    if parent_pid is not None:
        _start_parent_watchdog(parent_pid)
    from m3.app import run as _run
    _run()


def _start_parent_watchdog(parent_pid: int) -> None:
    """Background daemon thread: poll the parent PID, self-exit when it vanishes.

    This is the only reliable cleanup for the case where the Tauri shell is
    force-killed (kill -9, system shutdown, OOM). On Unix we use os.kill with
    signal 0, which raises ProcessLookupError when the process is gone but
    doesn't actually deliver a signal.
    """
    import os as _os
    import signal as _signal
    import threading
    import time as _time

    def _watch():
        while True:
            try:
                _os.kill(parent_pid, 0)
            except ProcessLookupError:
                # Parent gone, take down the whole process group so uvicorn
                # workers and any subprocess agents die with us.
                try:
                    _os.killpg(_os.getpgrp(), _signal.SIGTERM)
                except OSError:
                    pass
                _os._exit(0)
            except PermissionError:
                # Parent exists but we can't signal it; treat as alive.
                pass
            _time.sleep(2)

    threading.Thread(target=_watch, daemon=True, name="parent-watchdog").start()


@app.command("eval")
def eval_cmd(
    json_out: Path = typer.Option(None, "--json-out", help="Write raw results to this JSON file."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Also print per-case summaries."),
    case: str = typer.Option(None, "--case", help="Run only the named case."),
):
    """Run the extraction eval suite against the configured LLM.

    Uses whatever provider _make_llm picks — same as ingest / chat — so this
    measures real quality on the same code path users hit.
    """
    import asyncio as _asyncio
    from m3.evals.corpus import CORPUS
    from m3.evals.runner import export_json, format_report, run_suite

    cases = None
    if case:
        cases = [c for c in CORPUS if c.name == case]
        if not cases:
            names = ", ".join(c.name for c in CORPUS)
            typer.echo(f"no case named {case!r} — available: {names}", err=True)
            raise typer.Exit(code=2)

    llm = _make_llm()
    suite = _asyncio.run(run_suite(llm=llm, cases=cases))
    typer.echo(format_report(suite, verbose=verbose))
    if json_out:
        export_json(suite, json_out)
        typer.echo(f"  wrote results to {json_out}")
    if suite.pass_rate < 1.0:
        raise typer.Exit(code=1)


@app.command()
def reprocess(
    item_id: str = typer.Argument(None, help="Item UUID. Omit and pass --all or --all-unknown for bulk."),
    brain: Path = typer.Option(None, "--brain", help="Brain directory."),
    all_items: bool = typer.Option(False, "--all", help="Wipe derived state and replay every item."),
    only_unknown: bool = typer.Option(False, "--all-unknown", help="Re-extract only items with kind=unknown."),
    yes: bool = typer.Option(False, "--yes", help="Skip --all confirmation prompt."),
):
    """Re-run extraction against existing items using the current LLM/prompt.

    Single item: leaves prior self/entity state alone; may duplicate some content.
    --all: wipes all derived state (entities, self, records, signals, open questions,
    changelog) and replays every item. Items themselves are preserved.
    --all-unknown: re-extracts only items that landed in the kind=unknown fallback.
    """
    import asyncio as _asyncio
    import uuid as _uuid

    from m3.core.reprocess import reprocess_all, reprocess_all_unknown, reprocess_one

    if sum([bool(item_id), all_items, only_unknown]) != 1:
        typer.echo("Pass exactly one of: <item_id>, --all, --all-unknown", err=True)
        raise typer.Exit(code=2)

    brain_root = brain or _default_brain()
    if not (brain_root / "self.md").exists():
        typer.echo(f"brain at {brain_root} is not initialized", err=True)
        raise typer.Exit(code=1)

    llm = _make_llm()
    embedder = _make_embedder()

    if item_id:
        try:
            uid = _uuid.UUID(item_id)
        except ValueError:
            typer.echo(f"invalid uuid: {item_id}", err=True)
            raise typer.Exit(code=2)
        result = _asyncio.run(reprocess_one(brain_root=brain_root, item_id=uid, llm=llm, embedder=embedder))
    elif only_unknown:
        result = _asyncio.run(reprocess_all_unknown(brain_root=brain_root, llm=llm, embedder=embedder))
    else:
        # --all: confirm before wiping.
        if not yes:
            count = len(list((brain_root / "items" / "meta").glob("*.json")))
            typer.echo(
                f"This will wipe all derived brain state (entities, self, records, "
                f"signals, open questions, changelog) and replay {count} items "
                f"through the current LLM."
            )
            typer.echo("Items themselves (originals + meta) are preserved.")
            if not typer.confirm("Continue?", default=False):
                typer.echo("aborted")
                raise typer.Exit(code=1)
        result = _asyncio.run(reprocess_all(brain_root=brain_root, llm=llm, embedder=embedder))

    typer.echo(f"processed: {result.items_processed}")
    typer.echo(f"skipped:   {result.items_skipped}")
    if result.errors:
        typer.echo("errors:")
        for e in result.errors:
            typer.echo(f"  {e}")
        raise typer.Exit(code=1)


@app.command()
def synthesize(
    entity: str = typer.Option(None, "--entity", help="Entity slug to synthesize. Omit for stale-only batch pass."),
    brain: Path = typer.Option(None, "--brain", help="Brain directory."),
    force: bool = typer.Option(False, "--force", help="Regenerate even if up-to-date."),
    limit: int = typer.Option(None, "--limit", help="Cap entities synthesized in batch mode."),
):
    """Roll up an entity's claims into a synthesized note.

    With `--entity`, synthesize that one entity (regenerating if stale or
    `--force`). Without it, sweep every entity whose synthesis is missing or
    stale and regenerate the lot.
    """
    import asyncio as _asyncio

    from m3.core.synthesize import synthesize_entity, synthesize_stale

    brain_root = brain or _default_brain()
    if not (brain_root / "self.md").exists():
        typer.echo(f"brain at {brain_root} is not initialized", err=True)
        raise typer.Exit(code=1)

    llm = _make_llm()

    if entity:
        result = _asyncio.run(synthesize_entity(
            brain_root=brain_root, entity_slug=entity, llm=llm, force=force,
        ))
        if result.written:
            typer.echo(f"synthesized {entity}")
        else:
            typer.echo(f"skipped {entity}: {result.skipped_reason}")
        return

    results = _asyncio.run(synthesize_stale(
        brain_root=brain_root, llm=llm, limit=limit,
    ))
    written = sum(1 for r in results if r.written)
    typer.echo(f"synthesized {written} / {len(results)} stale entities")
    for r in results:
        if not r.written:
            typer.echo(f"  skipped {r.entity_slug}: {r.skipped_reason}")


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


@app.command()
def stats(
    days: int = typer.Option(7, "--days", help="Look back window in days."),
):
    """Summarize LLM call log: call count, total tokens, avg latency.

    Reads ~/.local/state/m3/llm-calls.jsonl (or $M3_LOG_DIR override),
    groups by (provider, model) over the last N days, and prints totals.
    """
    import datetime as _dt
    from collections import defaultdict

    from m3.core.llm_log import log_path

    p = log_path()
    if not p.exists():
        typer.echo("no llm-calls.jsonl yet")
        return

    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)
    groups: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {
        "calls": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0,
    })
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        try:
            ts = _dt.datetime.fromisoformat(d["ts"])
        except (KeyError, ValueError, TypeError):
            continue
        if ts < cutoff:
            continue
        key = (d.get("provider", "?"), d.get("model", "?"))
        g = groups[key]
        g["calls"] += 1
        if str(d.get("status", "")).startswith("error"):
            g["errors"] += 1
        g["input_tokens"] += int(d.get("input_tokens") or 0)
        g["output_tokens"] += int(d.get("output_tokens") or 0)
        g["latency_ms"] += int(d.get("latency_ms") or 0)

    if not groups:
        typer.echo(f"no calls in the last {days} days")
        return

    typer.echo(f"M3 LLM usage (last {days} days):")
    for (provider, model), g in sorted(groups.items()):
        avg = g["latency_ms"] // g["calls"] if g["calls"] else 0
        typer.echo(
            f"  {provider:<12} {model:<36}  calls={g['calls']:>4}  "
            f"errors={g['errors']:>3}  in={g['input_tokens']:>6}  "
            f"out={g['output_tokens']:>6}  avg={avg}ms"
        )


auth_app = typer.Typer(help="API key management for the HTTP surface.")
app.add_typer(auth_app, name="auth")


@auth_app.command("generate-key")
def auth_generate_key():
    """Generate a fresh API key, store it in config.yml, and enable auth.

    Prints the key to stdout so it can be piped into a secret manager or
    pasted into the client once. The server picks up the new key on the
    next request — no restart needed.
    """
    from m3.api.auth import generate_key
    from m3.core import config as _cfg

    key = generate_key()

    def _set(c: _cfg.M3Config) -> _cfg.M3Config:
        c.auth.api_key = key
        c.auth.require_auth = True
        return c

    _cfg.update(_set)
    typer.echo(key)


@auth_app.command("show-key")
def auth_show_key():
    """Print the configured API key (or note that none is configured)."""
    from m3.core import config as _cfg

    key = _cfg.auth_api_key()
    if not key:
        typer.echo("(no key configured)")
        raise typer.Exit(code=1)
    typer.echo(key)


@auth_app.command("disable")
def auth_disable():
    """Turn auth off. Leaves the key in config.yml in case you want to re-enable."""
    from m3.core import config as _cfg

    def _set(c: _cfg.M3Config) -> _cfg.M3Config:
        c.auth.require_auth = False
        return c

    _cfg.update(_set)
    typer.echo("auth disabled")


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
