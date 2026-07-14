"""Upload ke channel storage: limit 1,5 GB, retry, FloodWait, dedup hook.

Dipanggil sekuensial (satu file pada satu waktu) oleh queue di UI —
jangan paralel ke channel yang sama, itu jalan tercepat ke FloodWait
panjang.

Persistensi ke DB bukan urusan modul ini — caller (Fase 3: db.py, atau
script test Fase 2) yang menyimpan UploadResult. Dedup di-inject via
parameter find_by_sha256 dengan alasan yang sama.
"""
import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError

from config import settings
from core.hasher import compute_sha256


class FileTooLargeError(Exception):
    def __init__(self, path: str, size: int):
        limit_gb = settings.MAX_UPLOAD_SIZE / 1024**3
        super().__init__(
            f"{path} ({size / 1024**3:.2f} GB) melebihi limit {limit_gb:.1f} GB"
        )
        self.path = path
        self.size = size


@dataclass
class UploadResult:
    original_name: str
    local_path: str
    size_bytes: int
    channel_id: int
    message_id: int
    sha256: str
    mime_type: str | None
    deduped: bool = False  # True = file identik sudah ada, upload di-skip


MAX_RETRIES = 3
DELAY_BETWEEN_FILES = 1.5  # detik, flat antar file


async def upload_file(
    client: TelegramClient,
    channel,
    path: str | Path,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    find_by_sha256: Optional[Callable[[str], Optional[UploadResult]]] = None,
    caption: Optional[str] = None,
) -> UploadResult:
    path = str(path)
    size = os.path.getsize(path)
    if size > settings.MAX_UPLOAD_SIZE:
        raise FileTooLargeError(path, size)

    sha = compute_sha256(path)
    if find_by_sha256 and (existing := find_by_sha256(sha)):
        existing.deduped = True
        return existing

    msg = None
    for attempt in range(MAX_RETRIES):
        try:
            msg = await client.send_file(
                channel,
                path,
                caption=caption,  # nama+folder (core.captions) — kontrak resync
                progress_callback=progress_callback,
                force_document=True,  # preserve original, tanpa re-encode
            )
            break
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds)
        except (ConnectionError, TimeoutError):
            if attempt == MAX_RETRIES - 1:
                raise
            await asyncio.sleep(2**attempt)

    result = UploadResult(
        original_name=os.path.basename(path),
        local_path=path,
        size_bytes=size,
        channel_id=msg.chat_id,
        message_id=msg.id,
        sha256=sha,
        mime_type=msg.file.mime_type if msg.file else None,
    )
    await asyncio.sleep(DELAY_BETWEEN_FILES)
    return result
