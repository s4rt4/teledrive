"""SQLite persistence — sqlite3 bawaan, tanpa ORM.

DB di user data dir (settings.DB_PATH), bukan folder project.
"""
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import settings
from core.uploader import UploadResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_name TEXT NOT NULL,
    local_path TEXT,
    size_bytes INTEGER,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    sha256 TEXT,
    mime_type TEXT,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'synced',  -- synced/uploading/failed/corrupt/deleted
    UNIQUE(channel_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_original_name ON files(original_name);
CREATE INDEX IF NOT EXISTS idx_sha256 ON files(sha256);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    parent_id INTEGER,  -- NULL = root; folder virtual, hanya ada di DB
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS upload_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_path TEXT NOT NULL,
    folder_id INTEGER,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass
class FileRecord:
    id: int
    original_name: str
    local_path: str | None
    size_bytes: int | None
    channel_id: int
    message_id: int
    sha256: str | None
    mime_type: str | None
    uploaded_at: str
    status: str
    folder_id: int | None = None


@dataclass
class FolderRecord:
    id: int
    name: str
    parent_id: int | None
    created_at: str


@dataclass
class QueueItem:
    id: int
    local_path: str
    folder_id: int | None
    added_at: str


def _to_record(row: sqlite3.Row) -> FileRecord:
    return FileRecord(**dict(row))


def _to_folder(row: sqlite3.Row) -> FolderRecord:
    return FolderRecord(**dict(row))


class Database:
    def __init__(self, path: str | Path | None = None):
        self.conn = sqlite3.connect(str(path or settings.DB_PATH))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        # DB lama (pra-folder) belum punya kolom folder_id
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(files)")]
        if "folder_id" not in cols:
            self.conn.execute("ALTER TABLE files ADD COLUMN folder_id INTEGER")
            self.conn.commit()

    # ---- files ----

    def save_upload(self, r: UploadResult, folder_id: int | None = None) -> int:
        return self.add_file(
            original_name=r.original_name,
            local_path=r.local_path,
            size_bytes=r.size_bytes,
            channel_id=r.channel_id,
            message_id=r.message_id,
            sha256=r.sha256,
            mime_type=r.mime_type,
            folder_id=folder_id,
        )

    def add_file(
        self,
        original_name: str,
        channel_id: int,
        message_id: int,
        local_path: str | None = None,
        size_bytes: int | None = None,
        sha256: str | None = None,
        mime_type: str | None = None,
        status: str = "synced",
        folder_id: int | None = None,
    ) -> int:
        """Insert record; kalau (channel_id, message_id) sudah ada, return
        id record lama (dipakai migrasi/re-sync biar idempotent)."""
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO files
               (original_name, local_path, size_bytes, channel_id,
                message_id, sha256, mime_type, status, folder_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (original_name, local_path, size_bytes, channel_id,
             message_id, sha256, mime_type, status, folder_id),
        )
        self.conn.commit()
        if cur.rowcount:
            return cur.lastrowid
        row = self.conn.execute(
            "SELECT id FROM files WHERE channel_id = ? AND message_id = ?",
            (channel_id, message_id),
        ).fetchone()
        return row["id"]

    def find_by_sha256(self, sha: str) -> Optional[UploadResult]:
        """Dedup hook untuk uploader.upload_file — hanya record synced."""
        row = self.conn.execute(
            "SELECT * FROM files WHERE sha256 = ? AND status = 'synced' LIMIT 1",
            (sha,),
        ).fetchone()
        if row is None:
            return None
        return UploadResult(
            original_name=row["original_name"],
            local_path=row["local_path"],
            size_bytes=row["size_bytes"],
            channel_id=row["channel_id"],
            message_id=row["message_id"],
            sha256=row["sha256"],
            mime_type=row["mime_type"],
        )

    def get_file(self, file_id: int) -> Optional[FileRecord]:
        row = self.conn.execute(
            "SELECT * FROM files WHERE id = ?", (file_id,)
        ).fetchone()
        return _to_record(row) if row else None

    def find_by_message(
        self, channel_id: int, message_id: int
    ) -> Optional[FileRecord]:
        row = self.conn.execute(
            "SELECT * FROM files WHERE channel_id = ? AND message_id = ?",
            (channel_id, message_id),
        ).fetchone()
        return _to_record(row) if row else None

    def rename_file(self, file_id: int, new_name: str) -> None:
        self.conn.execute(
            "UPDATE files SET original_name = ? WHERE id = ?",
            (new_name, file_id),
        )
        self.conn.commit()

    def list_files(self, include_deleted: bool = False) -> list[FileRecord]:
        sql = "SELECT * FROM files"
        if not include_deleted:
            sql += " WHERE status != 'deleted'"
        sql += " ORDER BY uploaded_at DESC, id DESC"
        return [_to_record(r) for r in self.conn.execute(sql)]

    def search(self, term: str) -> list[FileRecord]:
        return [
            _to_record(r)
            for r in self.conn.execute(
                """SELECT * FROM files
                   WHERE original_name LIKE ? AND status != 'deleted'
                   ORDER BY uploaded_at DESC, id DESC""",
                (f"%{term}%",),
            )
        ]

    def list_in_folder(self, folder_id: int | None) -> list[FileRecord]:
        """File non-deleted di satu folder (None = root) untuk browser UI."""
        if folder_id is None:
            sql = ("SELECT * FROM files WHERE folder_id IS NULL "
                   "AND status != 'deleted' ORDER BY original_name COLLATE NOCASE")
            rows = self.conn.execute(sql)
        else:
            sql = ("SELECT * FROM files WHERE folder_id = ? "
                   "AND status != 'deleted' ORDER BY original_name COLLATE NOCASE")
            rows = self.conn.execute(sql, (folder_id,))
        return [_to_record(r) for r in rows]

    def move_file(self, file_id: int, folder_id: int | None) -> None:
        self.conn.execute(
            "UPDATE files SET folder_id = ? WHERE id = ?", (folder_id, file_id)
        )
        self.conn.commit()

    def total_synced_bytes(self) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) AS n FROM files "
            "WHERE status = 'synced'"
        ).fetchone()
        return row["n"]

    def set_status(self, file_id: int, status: str) -> None:
        self.conn.execute(
            "UPDATE files SET status = ? WHERE id = ?", (status, file_id)
        )
        self.conn.commit()

    # ---- folders ----

    def create_folder(self, name: str, parent_id: int | None = None) -> int:
        # UNIQUE constraint tidak menangkap duplikat di root (NULL != NULL
        # di SQLite), jadi cek manual
        for f in self.list_folders(parent_id):
            if f.name.lower() == name.lower():
                raise ValueError(f"Folder '{name}' sudah ada di sini")
        cur = self.conn.execute(
            "INSERT INTO folders (name, parent_id) VALUES (?, ?)",
            (name, parent_id),
        )
        self.conn.commit()
        return cur.lastrowid

    def list_folders(self, parent_id: int | None = None) -> list[FolderRecord]:
        if parent_id is None:
            rows = self.conn.execute(
                "SELECT * FROM folders WHERE parent_id IS NULL "
                "ORDER BY name COLLATE NOCASE"
            )
        else:
            rows = self.conn.execute(
                "SELECT * FROM folders WHERE parent_id = ? "
                "ORDER BY name COLLATE NOCASE",
                (parent_id,),
            )
        return [_to_folder(r) for r in rows]

    def folder_path(self, folder_id: int | None) -> Optional[str]:
        """Path folder "A/B/C" untuk caption (core.captions); None = root."""
        if folder_id is None:
            return None
        parts: list[str] = []
        fid, seen = folder_id, set()
        while fid is not None and fid not in seen:
            seen.add(fid)
            row = self.conn.execute(
                "SELECT name, parent_id FROM folders WHERE id = ?", (fid,)
            ).fetchone()
            if row is None:
                break
            parts.append(row["name"])
            fid = row["parent_id"]
        return "/".join(reversed(parts)) or None

    def ensure_folder_path(self, path: Optional[str]) -> Optional[int]:
        """Buat (kalau perlu) rantai folder dari path caption; return id
        folder terdalam. None/"/" = root."""
        if not path or path.strip() in ("", "/"):
            return None
        fid: Optional[int] = None
        for part in path.split("/"):
            part = part.strip()
            if part:
                fid = self.get_or_create_folder(part, fid)
        return fid

    def get_or_create_folder(self, name: str,
                             parent_id: int | None = None) -> int:
        for f in self.list_folders(parent_id):
            if f.name.lower() == name.lower():
                return f.id
        return self.create_folder(name, parent_id)

    def list_all_folders(self) -> list[FolderRecord]:
        return [
            _to_folder(r)
            for r in self.conn.execute(
                "SELECT * FROM folders ORDER BY name COLLATE NOCASE"
            )
        ]

    def rename_folder(self, folder_id: int, new_name: str) -> None:
        row = self.conn.execute(
            "SELECT parent_id FROM folders WHERE id = ?", (folder_id,)
        ).fetchone()
        if row is None:
            return
        for f in self.list_folders(row["parent_id"]):
            if f.id != folder_id and f.name.lower() == new_name.lower():
                raise ValueError(f"Folder '{new_name}' sudah ada di sini")
        self.conn.execute(
            "UPDATE folders SET name = ? WHERE id = ?", (new_name, folder_id)
        )
        self.conn.commit()

    def folder_is_empty(self, folder_id: int) -> bool:
        n_sub = self.conn.execute(
            "SELECT COUNT(*) AS n FROM folders WHERE parent_id = ?", (folder_id,)
        ).fetchone()["n"]
        n_files = self.conn.execute(
            "SELECT COUNT(*) AS n FROM files WHERE folder_id = ? "
            "AND status != 'deleted'",
            (folder_id,),
        ).fetchone()["n"]
        return n_sub == 0 and n_files == 0

    def delete_folder(self, folder_id: int) -> None:
        """Hapus folder kosong; row file berstatus deleted yang masih
        menunjuk ke sini dipindah ke root biar tidak orphan."""
        self.conn.execute(
            "UPDATE files SET folder_id = NULL WHERE folder_id = ?", (folder_id,)
        )
        self.conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        self.conn.commit()

    # ---- upload queue (persist antar sesi) ----

    def queue_add(self, local_path: str, folder_id: int | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO upload_queue (local_path, folder_id) VALUES (?, ?)",
            (local_path, folder_id),
        )
        self.conn.commit()
        return cur.lastrowid

    def queue_next(self) -> Optional[QueueItem]:
        row = self.conn.execute(
            "SELECT * FROM upload_queue ORDER BY id LIMIT 1"
        ).fetchone()
        return QueueItem(**dict(row)) if row else None

    def queue_remove(self, queue_id: int) -> None:
        self.conn.execute("DELETE FROM upload_queue WHERE id = ?", (queue_id,))
        self.conn.commit()

    def queue_clear(self) -> None:
        self.conn.execute("DELETE FROM upload_queue")
        self.conn.commit()

    def queue_count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) AS n FROM upload_queue"
        ).fetchone()["n"]

    def queue_has_path(self, local_path: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM upload_queue WHERE local_path = ? LIMIT 1",
            (local_path,),
        ).fetchone() is not None

    def has_local_path(self, local_path: str) -> bool:
        """Pernah tercatat dari path ini (status apa pun) — dipakai
        auto-backup supaya file yang dihapus user tidak di-backup ulang."""
        return self.conn.execute(
            "SELECT 1 FROM files WHERE local_path = ? LIMIT 1",
            (local_path,),
        ).fetchone() is not None

    # ---- meta ----

    def get_meta(self, key: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
