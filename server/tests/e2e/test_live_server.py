"""End-to-end smoke: spin up `m3 start`, hit every critical endpoint, tear down.

Catches whole classes of bugs that per-module tests miss:
- Import-time failures (a missing module doesn't crash tests but crashes `m3 start`).
- Config resolution paths that only matter in the real entrypoint.
- LaunchAgent-style env misconfiguration (here simulated by only passing
  M3_LLM_PROVIDER=fake + M3_BRAIN + M3_CONFIG_DIR, nothing else).
- Drift between `cli._make_llm` and `app._make_llm` (the bug this session hit
  because of hardcoded defaults in a LaunchAgent).
- Process-level lifecycle: port binding, clean teardown, startup timing.

The subprocess runs under M3_LLM_PROVIDER=fake so we don't need Ollama or an
API key; we're testing plumbing, not extraction quality.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from m3.brain.layout import init_brain


def _reserve_port() -> int:
    """Pick an unused high port. There is a race between us releasing the
    socket and `m3 start` binding it, but for a local smoke the collision rate
    is effectively zero."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_server(base_url: str, proc: subprocess.Popen, timeout_secs: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_secs
    while time.monotonic() < deadline:
        # Fail fast if the subprocess died during startup.
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(
                f"server exited during startup with code {proc.returncode}. Output:\n{out}"
            )
        try:
            r = httpx.get(f"{base_url}/api/v1/status", timeout=1.0)
            if r.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise TimeoutError(f"server at {base_url} didn't become ready in {timeout_secs}s")


@pytest.fixture
def live_server(tmp_path):
    """Start `m3 start` in a subprocess with an isolated tmp brain.

    Yields the base URL. Tears down via SIGTERM (SIGKILL if it lingers > 3s).
    Fails the test if the subprocess exited before teardown — that means
    something crashed mid-request.
    """
    brain = tmp_path / "brain"
    init_brain(brain)

    # Isolate user config so we don't clobber the dev's ~/.config/m3/config.yml
    # with fake-provider state, and so the server doesn't pick up any
    # anthropic_api_key / ollama_host from there.
    config_dir = tmp_path / "m3_config"
    config_dir.mkdir()

    port = _reserve_port()

    m3_bin = shutil.which("m3")
    assert m3_bin, "m3 CLI not on PATH — run `pip install -e .` in server/ first"

    # Minimal env — this is what a LaunchAgent-style launch would actually look
    # like. PATH is needed so uvicorn/fastembed can find their deps; HOME is
    # set to an empty dir so anything that walks ~/ (fastembed cache, etc.)
    # doesn't pick up dev state. We pass M3_LLM_PROVIDER here rather than via
    # --llm-provider because that's how a real deployment sets it.
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path / "home"),
        "M3_BRAIN": str(brain),
        "M3_CONFIG_DIR": str(config_dir),
        "M3_LLM_PROVIDER": "fake",
        # Dev identity so brain's git auto-commit doesn't fail if it runs.
        "GIT_AUTHOR_NAME": "m3-test",
        "GIT_AUTHOR_EMAIL": "test@m3.local",
        "GIT_COMMITTER_NAME": "m3-test",
        "GIT_COMMITTER_EMAIL": "test@m3.local",
    }
    (tmp_path / "home").mkdir()

    # `m3 start` typer command unconditionally overwrites M3_HOST/M3_PORT from
    # argparse defaults (127.0.0.1:7007) — so we MUST pass them as CLI flags,
    # not just as env. Same with --brain; we pass both belt-and-suspenders.
    proc = subprocess.Popen(
        [m3_bin, "start", "--brain", str(brain), "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_server(base_url, proc, timeout_secs=20.0)
    except (TimeoutError, RuntimeError) as e:
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        pytest.fail(f"server didn't start: {e}\n--- subprocess output ---\n{out}")

    try:
        yield base_url
    finally:
        if proc.poll() is not None:
            # Died during the test.
            out = proc.stdout.read() if proc.stdout else ""
            pytest.fail(
                f"server exited during test with code {proc.returncode}. Output:\n{out}"
            )
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def test_status(live_server):
    r = httpx.get(f"{live_server}/api/v1/status", timeout=5.0)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "brain_root" in body


def test_ingest_text_end_to_end(live_server):
    r = httpx.post(
        f"{live_server}/api/v1/ingest/text",
        json={"text": "smoke test note — coffee with Aditya", "source": "e2e"},
        timeout=30.0,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # With the fake LLM we get a minimal but valid ExtractionOutput; the item
    # still lands and kind comes from the classifier's fallback.
    assert "kind" in body
    assert "item_id" in body
    assert "confidence" in body


def test_self_has_seven_slots(live_server):
    r = httpx.get(f"{live_server}/api/v1/self", timeout=5.0)
    assert r.status_code == 200
    slots = r.json()["slots"]
    assert set(slots.keys()) == {
        "Preferences", "People", "Projects", "Goals", "Context", "Beliefs", "Timeline",
    }


def test_entities_endpoint(live_server):
    r = httpx.get(f"{live_server}/api/v1/entities", timeout=5.0)
    assert r.status_code == 200
    body = r.json()
    assert "entities" in body
    assert isinstance(body["entities"], list)


def test_open_questions_endpoint(live_server):
    r = httpx.get(f"{live_server}/api/v1/open-questions", timeout=5.0)
    assert r.status_code == 200
    body = r.json()
    assert "questions" in body
    assert isinstance(body["questions"], list)


def test_retrieve_endpoint(live_server):
    # Any text query is valid — an empty brain just returns no hits.
    r = httpx.get(f"{live_server}/api/v1/retrieve", params={"q": "smoke"}, timeout=5.0)
    assert r.status_code == 200
    body = r.json()
    assert "hits" in body
    assert isinstance(body["hits"], list)


def test_settings_endpoint(live_server):
    r = httpx.get(f"{live_server}/api/v1/settings", timeout=5.0)
    assert r.status_code == 200
    body = r.json()
    # We started with M3_LLM_PROVIDER=fake, so the effective provider is fake
    # and env_overrides should list M3_LLM_PROVIDER.
    assert body["provider"] == "fake"
    assert "M3_LLM_PROVIDER" in body["env_overrides"]
    assert body["anthropic_api_key_present"] is False
