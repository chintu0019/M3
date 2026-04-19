import json
import uuid
from pathlib import Path

from m3.brain.records import Record, write_record


def test_write_record_creates_dated_file(tmp_brain: Path):
    rec = Record(
        item_id=uuid.UUID("99999999-9999-9999-9999-999999999999"),
        amount=42.5, currency="USD", vendor="Uber",
        date="2026-04-15", category="transportation", due_date=None, reference_id="INV-1",
    )
    path = write_record(tmp_brain, rec)
    assert path == tmp_brain / "records" / "2026-04-15-uber.json"
    data = json.loads(path.read_text())
    assert data["amount"] == 42.5
    assert data["vendor"] == "Uber"
    assert data["item_id"] == str(rec.item_id)


def test_write_record_slugifies_vendor(tmp_brain: Path):
    rec = Record(
        item_id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        amount=10.0, currency="INR", vendor="HDFC Bank (Credit Card)",
        date="2026-03-01", category="banking", due_date="2026-04-01", reference_id=None,
    )
    path = write_record(tmp_brain, rec)
    assert path.name == "2026-03-01-hdfc-bank-credit-card.json"
