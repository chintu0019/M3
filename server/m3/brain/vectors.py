"""sqlite-vec wrapper. Two tables: item vectors and entity vectors. No search surface in P1 — just upsert + nearest (used by ingest for candidate retrieval in Task 13)."""

from __future__ import annotations

import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path

import sqlite_vec

from m3.brain.layout import BrainPaths

VECTOR_DIM = 768


@dataclass
class Hit:
    id: str
    distance: float


def _pack(vec: list[float]) -> bytes:
    if len(vec) != VECTOR_DIM:
        raise ValueError(f"expected dim {VECTOR_DIM}, got {len(vec)}")
    return struct.pack(f"{VECTOR_DIM}f", *vec)


class VectorIndex:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def open(cls, root: Path) -> "VectorIndex":
        p = BrainPaths(root)
        p.index_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(p.vectors_db)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS items USING vec0(id TEXT PRIMARY KEY, embedding FLOAT[{VECTOR_DIM}])"
        )
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS entities USING vec0(id TEXT PRIMARY KEY, embedding FLOAT[{VECTOR_DIM}])"
        )
        return cls(conn)

    def upsert_item(self, *, item_id: str, embedding: list[float]) -> None:
        blob = _pack(embedding)
        self._conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        self._conn.execute("INSERT INTO items(id, embedding) VALUES (?, ?)", (item_id, blob))
        self._conn.commit()

    def upsert_entity(self, *, slug: str, embedding: list[float]) -> None:
        blob = _pack(embedding)
        self._conn.execute("DELETE FROM entities WHERE id = ?", (slug,))
        self._conn.execute("INSERT INTO entities(id, embedding) VALUES (?, ?)", (slug, blob))
        self._conn.commit()

    def nearest_items(self, *, query: list[float], k: int) -> list[Hit]:
        blob = _pack(query)
        rows = self._conn.execute(
            "SELECT id, distance FROM items WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (blob, k),
        ).fetchall()
        return [Hit(id=r[0], distance=float(r[1])) for r in rows]

    def nearest_entities(self, *, query: list[float], k: int) -> list[Hit]:
        blob = _pack(query)
        rows = self._conn.execute(
            "SELECT id, distance FROM entities WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (blob, k),
        ).fetchall()
        return [Hit(id=r[0], distance=float(r[1])) for r in rows]

    def count_items(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
