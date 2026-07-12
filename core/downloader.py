"""Download dari channel storage + verifikasi integritas sha256."""
from pathlib import Path
from typing import Callable, Optional

from telethon import TelegramClient

from core.hasher import compute_sha256


class IntegrityError(Exception):
    """Hash file hasil download tidak cocok dengan record — file corrupt."""

    def __init__(self, path: str, expected: str, actual: str):
        super().__init__(
            f"sha256 mismatch untuk {path}: expected {expected}, got {actual}"
        )
        self.path = path
        self.expected = expected
        self.actual = actual


async def download_file(
    client: TelegramClient,
    channel,
    message_id: int,
    dest_path: str | Path,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    expected_sha256: Optional[str] = None,
) -> str:
    """Download media dari message_id ke dest_path, return path final.

    Kalau expected_sha256 diisi dan tidak cocok, raise IntegrityError —
    caller (Fase 3) yang menandai status='corrupt' di DB.
    """
    msg = await client.get_messages(channel, ids=message_id)
    if msg is None or msg.file is None:
        raise FileNotFoundError(
            f"Message {message_id} tidak ada atau tidak berisi file"
        )

    saved = await client.download_media(
        msg, file=str(dest_path), progress_callback=progress_callback
    )

    if expected_sha256:
        actual = compute_sha256(saved)
        if actual != expected_sha256:
            raise IntegrityError(saved, expected_sha256, actual)

    return str(saved)
