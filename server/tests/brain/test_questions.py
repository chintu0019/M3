import uuid
from pathlib import Path

from m3.brain.questions import OpenQuestion, append, list_unresolved, resolve


def test_append_adds_checklist_line(tmp_brain: Path):
    item_id = uuid.UUID("55555555-5555-5555-5555-555555555555")
    q = OpenQuestion(item_id=item_id, question="Who is J?", context_snippet="call w/ J at 3pm")
    append(tmp_brain, q, created_date="2026-04-19")
    text = (tmp_brain / "open_questions.md").read_text()
    assert "- [ ]" in text
    assert "Who is J?" in text
    assert str(item_id) in text
    assert "2026-04-19" in text


def test_list_unresolved_parses_checkbox_state(tmp_brain: Path):
    q1 = OpenQuestion(item_id=uuid.UUID("66666666-6666-6666-6666-666666666666"), question="Q1?", context_snippet="c1")
    q2 = OpenQuestion(item_id=uuid.UUID("77777777-7777-7777-7777-777777777777"), question="Q2?", context_snippet="c2")
    append(tmp_brain, q1, created_date="2026-04-19")
    append(tmp_brain, q2, created_date="2026-04-19")
    unresolved = list_unresolved(tmp_brain)
    assert len(unresolved) == 2


def test_resolve_marks_checkbox_and_records_answer(tmp_brain: Path):
    q = OpenQuestion(item_id=uuid.UUID("88888888-8888-8888-8888-888888888888"), question="Who?", context_snippet="x")
    append(tmp_brain, q, created_date="2026-04-19")
    resolve(tmp_brain, question_text="Who?", answer="Jerome", resolved_date="2026-04-20")
    text = (tmp_brain / "open_questions.md").read_text()
    assert "- [x]" in text
    assert "Jerome" in text
    assert "2026-04-20" in text
    assert list_unresolved(tmp_brain) == []
