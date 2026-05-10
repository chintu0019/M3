"""Topical-signature embeddings, keyed by canvas node id.

One row per node; vector is a fastembed embedding of a node-type-specific
"signature text" (entity dossier, claim proposition, item extracted text,
synthesis summary). Used by the canvas v2 force layout to attract topically
similar nodes.

Shape mirrors `m3.brain.vectors` but lives in its own DB so a reindex of
topical signatures doesn't disturb the existing item/entity vectors.
"""

from __future__ import annotations

import sqlite3
import struct
from collections.abc import Iterable
from pathlib import Path

import sqlite_vec

from m3.brain.layout import BrainPaths

TOPICAL_DIM = 768


def _pack(vec: list[float]) -> bytes:
    if len(vec) != TOPICAL_DIM:
        raise ValueError(f"expected dim {TOPICAL_DIM}, got {len(vec)}")
    return struct.pack(f"{TOPICAL_DIM}f", *vec)


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{TOPICAL_DIM}f", blob))


class TopicalIndex:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def open(cls, root: Path) -> "TopicalIndex":
        p = BrainPaths(root)
        p.index_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(p.topical_db)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS topical USING vec0("
            f"node_id TEXT PRIMARY KEY, embedding FLOAT[{TOPICAL_DIM}])"
        )
        return cls(conn)

    def upsert(self, node_id: str, vec: list[float]) -> None:
        blob = _pack(vec)
        self._conn.execute("DELETE FROM topical WHERE node_id = ?", (node_id,))
        self._conn.execute(
            "INSERT INTO topical(node_id, embedding) VALUES (?, ?)", (node_id, blob)
        )
        self._conn.commit()

    def delete(self, node_id: str) -> None:
        self._conn.execute("DELETE FROM topical WHERE node_id = ?", (node_id,))
        self._conn.commit()

    def get(self, node_id: str) -> list[float] | None:
        row = self._conn.execute(
            "SELECT embedding FROM topical WHERE node_id = ?", (node_id,)
        ).fetchone()
        return _unpack(row[0]) if row else None

    def iter_all(self) -> Iterable[tuple[str, list[float]]]:
        for nid, blob in self._conn.execute("SELECT node_id, embedding FROM topical"):
            yield nid, _unpack(blob)

    def close(self) -> None:
        self._conn.close()
