from __future__ import annotations

from pathlib import Path

from m3.brain import folders as _folders


def test_list_folders_empty(tmp_brain: Path):
    assert _folders.list_folders(tmp_brain) == []


def test_create_folder_returns_record(tmp_brain: Path):
    f = _folders.create_folder(tmp_brain, name="Work")
    assert f["name"] == "Work"
    assert f["id"].startswith("f_")
    assert f["sort_order"] == 0


def test_list_folders_after_create(tmp_brain: Path):
    f1 = _folders.create_folder(tmp_brain, name="Work")
    f2 = _folders.create_folder(tmp_brain, name="Side")
    listed = _folders.list_folders(tmp_brain)
    assert [f["id"] for f in listed] == [f1["id"], f2["id"]]
    assert listed[1]["sort_order"] == 1


def test_update_folder_rename(tmp_brain: Path):
    f = _folders.create_folder(tmp_brain, name="Old")
    _folders.update_folder(tmp_brain, f["id"], name="New")
    assert _folders.list_folders(tmp_brain)[0]["name"] == "New"


def test_update_folder_reorder(tmp_brain: Path):
    f1 = _folders.create_folder(tmp_brain, name="A")
    f2 = _folders.create_folder(tmp_brain, name="B")
    _folders.update_folder(tmp_brain, f2["id"], sort_order=0)
    _folders.update_folder(tmp_brain, f1["id"], sort_order=1)
    ids = [f["id"] for f in _folders.list_folders(tmp_brain)]
    assert ids == [f2["id"], f1["id"]]


def test_update_unknown_folder_raises(tmp_brain: Path):
    import pytest
    with pytest.raises(KeyError):
        _folders.update_folder(tmp_brain, "f_nope", name="X")


def test_delete_folder(tmp_brain: Path):
    f = _folders.create_folder(tmp_brain, name="X")
    _folders.delete_folder(tmp_brain, f["id"])
    assert _folders.list_folders(tmp_brain) == []


def test_delete_folder_idempotent(tmp_brain: Path):
    _folders.delete_folder(tmp_brain, "f_nope")  # must not raise
