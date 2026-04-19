"""SQLite FTS5 wrapper for keyword search over item extracted_text.

Shares the same sqlite file as vectors.py (`~/brain/index/vectors.sqlite`) so
a single db connection per process can back both. FTS5 is built into stdlib
sqlite3 on macOS and modern Linux; no extra dep.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from m3.brain.layout import BrainPaths


@dataclass
class FTSHit:
    id: str
    score: float
    snippet: str


class FTSIndex:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def open(cls, root: Path) -> "FTSIndex":
        p = BrainPaths(root)
        p.index_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(p.vectors_db)
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS items_fts "
            "USING fts5(id UNINDEXED, text, tokenize='porter unicode61')"
        )
        return cls(conn)

    def upsert_item(self, *, item_id: str, text: str) -> None:
        self._conn.execute("DELETE FROM items_fts WHERE id = ?", (item_id,))
        self._conn.execute("INSERT INTO items_fts(id, text) VALUES (?, ?)", (item_id, text))
        self._conn.commit()

    def search(self, query: str, *, k: int) -> list[FTSHit]:
        if not query.strip():
            return []
        # Use bm25() for scoring. FTS5 bm25() returns a negative number where
        # less-negative == better match. We invert so higher == better.
        rows = self._conn.execute(
            "SELECT id, bm25(items_fts) AS raw_score, "
            "snippet(items_fts, 1, '', '', ' … ', 16) AS snip "
            "FROM items_fts WHERE items_fts MATCH ? ORDER BY raw_score LIMIT ?",
            (_sanitize(query), k),
        ).fetchall()
        return [FTSHit(id=r[0], score=1.0 / (1.0 + float(r[1])), snippet=r[2] or "") for r in rows]

    def close(self) -> None:
        self._conn.close()


def _sanitize(q: str) -> str:
    """Escape FTS5 meta chars by wrapping each token in double quotes."""
    tokens = [t for t in q.split() if t]
    return " ".join(f'"{t.replace(chr(34), "")}"' for t in tokens) or '""'
