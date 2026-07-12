"""Cache thumbnail dari Telegram untuk gambar/video.

Telegram otomatis membuat thumbnail untuk dokumen gambar/video.
Di-download sekali (bytes, bukan file — biar Telethon tidak mengubah
ekstensi), disimpan ke THUMB_DIR/<file_id>.jpg, dipakai sebagai icon
grid. Fetch sekuensial — thumbnail kecil, dan paralel ke channel yang
sama mengundang FloodWait.
"""
from pathlib import Path
from typing import Callable, Iterable, Optional

from telethon import TelegramClient

from config import settings
from core.db import FileRecord


def thumb_path(file_id: int) -> Path:
    return settings.THUMB_DIR / f"{file_id}.jpg"


async def fetch_thumbs(
    client: TelegramClient,
    channel,
    records: Iterable[FileRecord],
    on_ready: Optional[Callable[[int], None]] = None,
) -> int:
    """Download thumb untuk records yang belum punya cache. Return jumlah
    thumb baru. Caller yang memfilter jenis file (image/video)."""
    targets = [r for r in records if not thumb_path(r.id).exists()]
    if not targets:
        return 0

    msgs = await client.get_messages(
        channel, ids=[r.message_id for r in targets]
    )
    done = 0
    for rec, msg in zip(targets, msgs):
        if msg is None or msg.document is None:
            continue
        if not getattr(msg.document, "thumbs", None):
            continue  # Telegram tidak membuat thumb untuk file ini
        try:
            data = await client.download_media(msg, file=bytes, thumb=-1)
        except Exception:
            continue  # thumb gagal bukan alasan mengganggu UI
        if not data:
            continue
        thumb_path(rec.id).write_bytes(data)
        done += 1
        if on_ready:
            on_ready(rec.id)
    return done
