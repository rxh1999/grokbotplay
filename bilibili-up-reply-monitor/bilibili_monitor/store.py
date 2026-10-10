from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class SeenStore:
    """Persist seen reply ids so restarts do not re-notify."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_replies (
                rpid INTEGER PRIMARY KEY,
                bvid TEXT NOT NULL,
                first_seen_at INTEGER NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    def is_baselined(self, bvid: str) -> bool:
        return self.get_meta(f"baseline:{bvid}") == "1"

    def mark_baselined(self, bvid: str) -> None:
        self.set_meta(f"baseline:{bvid}", "1")

    def known(self, rpid: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen_replies WHERE rpid = ?", (rpid,)
        ).fetchone()
        return row is not None

    def add_many(self, bvid: str, rpids: list[int], *, ts: int) -> int:
        added = 0
        for rpid in rpids:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO seen_replies(rpid, bvid, first_seen_at) "
                "VALUES(?, ?, ?)",
                (int(rpid), bvid, ts),
            )
            added += cur.rowcount
        self._conn.commit()
        return added

    def all_rpids(self, bvid: str | None = None) -> set[int]:
        if bvid:
            rows = self._conn.execute(
                "SELECT rpid FROM seen_replies WHERE bvid = ?", (bvid,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT rpid FROM seen_replies").fetchall()
        return {int(r[0]) for r in rows}

    def export_json(self, out: Path) -> None:
        data = {
            "meta": dict(self._conn.execute("SELECT key, value FROM meta")),
            "seen": [
                {"rpid": r[0], "bvid": r[1], "first_seen_at": r[2]}
                for r in self._conn.execute(
                    "SELECT rpid, bvid, first_seen_at FROM seen_replies"
                )
            ],
        }
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
