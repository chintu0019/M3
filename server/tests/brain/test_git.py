import subprocess
from pathlib import Path

from m3.brain.git import commit_ingest, has_changes


def test_has_changes_false_on_clean_brain(tmp_brain: Path):
    subprocess.run(["git", "add", "-A"], cwd=tmp_brain, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "baseline", "--allow-empty"], cwd=tmp_brain, check=True)
    assert has_changes(tmp_brain) is False


def test_commit_ingest_creates_commit_with_given_summary(tmp_brain: Path):
    subprocess.run(["git", "add", "-A"], cwd=tmp_brain, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "baseline", "--allow-empty"], cwd=tmp_brain, check=True)
    (tmp_brain / "self.md").write_text("# Self\n\n## Preferences\n\n- like tea\n")
    assert has_changes(tmp_brain) is True
    commit_ingest(tmp_brain, item_id="abc", summary="stance on tea")
    msg = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"], cwd=tmp_brain, check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert msg == "ingest abc: stance on tea"
    assert has_changes(tmp_brain) is False


def test_commit_ingest_is_noop_when_no_changes(tmp_brain: Path):
    subprocess.run(["git", "add", "-A"], cwd=tmp_brain, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "baseline", "--allow-empty"], cwd=tmp_brain, check=True)
    before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_brain, check=True, capture_output=True, text=True,
    ).stdout.strip()
    commit_ingest(tmp_brain, item_id="abc", summary="nothing changed")
    after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_brain, check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert before == after
