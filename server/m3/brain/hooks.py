"""Hook index: maps hook values back to item ids for fragment→entity retrieval.

A single sqlite table `item_hooks(item_id, hook_type, normalized_value, raw_value)`
under `~/brain/index/vectors.sqlite`. Case-insensitive substring matching.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from m3.brain.layout import BrainPaths

HookType = str   # "who" | "what" | "where" | "project" | "stance_entity"


@dataclass
class HookHit:
    item_id: str
    hook_type: str
    raw_value: str


class HookIndex:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def open(cls, root: Path) -> "HookIndex":
        p = BrainPaths(root)
        p.index_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(p.vectors_db)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS item_hooks ("
            "item_id TEXT NOT NULL, hook_type TEXT NOT NULL, "
            "normalized_value TEXT NOT NULL, raw_value TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_item_hooks_lookup "
            "ON item_hooks(hook_type, normalized_value)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_item_hooks_item ON item_hooks(item_id)")
        return cls(conn)

    def upsert_item_hooks(
        self, *, item_id: str,
        who: list[str], what: list[str], where: list[str],
        project: list[str], stance_entities: list[str],
    ) -> None:
        self._conn.execute("DELETE FROM item_hooks WHERE item_id = ?", (item_id,))
        rows: list[tuple[str, str, str, str]] = []
        for hook_type, values in (
            ("who", who), ("what", what), ("where", where),
            ("project", project), ("stance_entity", stance_entities),
        ):
            for v in values:
                v = (v or "").strip()
                if not v:
                    continue
                rows.append((item_id, hook_type, v.lower(), v))
        if rows:
            self._conn.executemany(
                "INSERT INTO item_hooks(item_id, hook_type, normalized_value, raw_value) "
                "VALUES (?, ?, ?, ?)", rows,
            )
        self._conn.commit()

    def search(self, fragment: str, *, types: list[HookType], k: int) -> list[HookHit]:
        frag = (fragment or "").strip().lower()
        if not frag or not types:
            return []
        placeholders = ",".join("?" for _ in types)
        rows = self._conn.execute(
            f"SELECT item_id, hook_type, raw_value FROM item_hooks "
            f"WHERE hook_type IN ({placeholders}) AND normalized_value LIKE ? "
            f"LIMIT ?",
            (*types, f"%{frag}%", k),
        ).fetchall()
        return [HookHit(item_id=r[0], hook_type=r[1], raw_value=r[2]) for r in rows]

    def delete_item(self, *, item_id: str) -> None:
        self._conn.execute("DELETE FROM item_hooks WHERE item_id = ?", (item_id,))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
