"""SHA-256 integrity check — chunked, jangan load full file ke memory."""
import hashlib
from pathlib import Path

CHUNK_SIZE = 1024 * 1024  # 1 MB


def compute_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()
