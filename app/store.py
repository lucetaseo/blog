"""글 보관함 — 만든 글과 사진을 SQLite + 파일로 보관한다."""

import json
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

STATUSES = ("draft", "scheduled", "done")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_when(value: str | None) -> str | None:
    """ISO 시각을 UTC ISO 문자열로 정규화한다. 빈 값이면 None."""
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("발행 예정 시각에 시간대 정보가 없습니다.")
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


class PostStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.photo_dir = self.data_dir / "photos"
        self.photo_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.data_dir / "blog.db", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                post_type TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                scheduled_at TEXT,
                body_html TEXT NOT NULL,
                paste_html TEXT NOT NULL,
                paste_text TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                checklist TEXT NOT NULL DEFAULT '[]',
                photos TEXT NOT NULL DEFAULT '[]',
                photo_order TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")
        self._db.commit()

    # ---------- 변환 ----------
    @staticmethod
    def _row(row: sqlite3.Row, full: bool = True) -> dict:
        d = dict(row)
        for k in ("tags", "checklist", "photos", "photo_order"):
            d[k] = json.loads(d[k])
        d["photo_count"] = len(d["photos"])
        if not full:
            for k in ("body_html", "paste_html", "paste_text", "checklist"):
                d.pop(k)
        return d

    # ---------- 쓰기 ----------
    def create(self, data: dict, photos: list[tuple[str, bytes]]) -> dict:
        """photos: [(원본 파일명, 내용)] — 업로드 순서가 곧 [사진 N] 번호."""
        post_id = uuid.uuid4().hex[:12]
        folder = self.photo_dir / post_id
        folder.mkdir()
        names = []
        for i, (filename, raw) in enumerate(photos, start=1):
            ext = Path(filename).suffix.lower()[:6] or ".jpg"
            name = f"{i:02d}{ext}"
            (folder / name).write_bytes(raw)
            names.append({"file": name, "original": filename})

        status, scheduled_at = self._status_fields(data)
        now = _now()
        with self._lock:
            self._db.execute(
                """INSERT INTO posts (id, title, post_type, status, scheduled_at, body_html, paste_html,
                   paste_text, tags, checklist, photos, photo_order, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (post_id, data["title"], data.get("post_type", ""), status, scheduled_at,
                 data["body_html"], data["paste_html"], data["paste_text"],
                 json.dumps(data.get("tags", []), ensure_ascii=False),
                 json.dumps(data.get("checklist", []), ensure_ascii=False),
                 json.dumps(names, ensure_ascii=False),
                 json.dumps(data.get("photo_order", [])), now, now),
            )
            self._db.commit()
        return self.get(post_id)

    def update(self, post_id: str, data: dict) -> dict | None:
        fields, values = [], []
        for k in ("title", "body_html", "paste_html", "paste_text"):
            if k in data:
                fields.append(f"{k} = ?")
                values.append(data[k])
        for k in ("tags", "photo_order"):
            if k in data:
                fields.append(f"{k} = ?")
                values.append(json.dumps(data[k], ensure_ascii=False))
        if "status" in data or "scheduled_at" in data:
            if "scheduled_at" not in data:  # 상태만 바꾸면 예정 시각은 그대로 둔다
                current = self.get(post_id)
                data = {**data, "scheduled_at": current["scheduled_at"] if current else None}
            status, scheduled_at = self._status_fields(data)
            fields += ["status = ?", "scheduled_at = ?"]
            values += [status, scheduled_at]
        if not fields:
            return self.get(post_id)
        fields.append("updated_at = ?")
        values += [_now(), post_id]
        with self._lock:
            cur = self._db.execute(f"UPDATE posts SET {', '.join(fields)} WHERE id = ?", values)
            self._db.commit()
        return self.get(post_id) if cur.rowcount else None

    @staticmethod
    def _status_fields(data: dict) -> tuple[str, str | None]:
        scheduled_at = parse_when(data.get("scheduled_at"))
        status = data.get("status") or ("scheduled" if scheduled_at else "draft")
        if status not in STATUSES:
            raise ValueError(f"알 수 없는 상태입니다: {status}")
        if status == "scheduled" and not scheduled_at:
            status = "draft"
        return status, scheduled_at

    def delete(self, post_id: str) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
            self._db.commit()
        shutil.rmtree(self.photo_dir / post_id, ignore_errors=True)
        return cur.rowcount > 0

    # ---------- 읽기 ----------
    def get(self, post_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        return self._row(row) if row else None

    def list_all(self) -> list[dict]:
        # 예정 글은 가까운 순, 나머지는 최근 수정 순
        with self._lock:
            rows = self._db.execute(
                """SELECT * FROM posts ORDER BY
                   CASE status WHEN 'scheduled' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END,
                   CASE WHEN status = 'scheduled' THEN scheduled_at END ASC,
                   updated_at DESC"""
            ).fetchall()
        return [self._row(r, full=False) for r in rows]

    def due(self) -> list[dict]:
        """예정 시각이 지났는데 아직 발행 완료 표시가 안 된 글."""
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM posts WHERE status = 'scheduled' AND scheduled_at <= ? ORDER BY scheduled_at",
                (_now(),),
            ).fetchall()
        return [self._row(r, full=False) for r in rows]

    def photo_path(self, post_id: str, n: int) -> Path | None:
        post = self.get(post_id)
        if not post or not 1 <= n <= len(post["photos"]):
            return None
        return self.photo_dir / post_id / post["photos"][n - 1]["file"]
