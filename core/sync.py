"""Sinkronisasi DB lokal dengan isi channel storage.

Dua arah dalam satu jalan:
- Dokumen di channel yang belum tercatat -> tambah record (recovery
  kalau DB hilang / dipakai di PC lain). Nama diambil dari caption
  message kalau ada (rename via app menulis caption), fallback ke
  atribut filename dokumen.
- Record 'synced' yang message-nya sudah tidak ada di channel ->
  status 'missing' (terhapus lewat aplikasi Telegram langsung).
  Kalau muncul lagi, dipulihkan ke 'synced'.

Record hasil recovery tidak punya sha256 (hash butuh isi file penuh) —
downloader otomatis skip verifikasi kalau sha kosong.
"""
from dataclasses import dataclass
from typing import Callable, Optional

from telethon import TelegramClient, utils
from telethon.tl.types import DocumentAttributeFilename

from core.db import Database


@dataclass
class SyncReport:
    scanned: int = 0
    added: int = 0
    restored: int = 0
    missing: int = 0

    def summary(self) -> str:
        return (
            f"{self.scanned} message dipindai: {self.added} file baru "
            f"ditambahkan, {self.restored} dipulihkan, "
            f"{self.missing} hilang di Telegram"
        )


def _doc_name(msg) -> str:
    caption = (msg.message or "").strip()
    if caption:
        return caption.splitlines()[0][:255]
    for attr in msg.document.attributes:
        if isinstance(attr, DocumentAttributeFilename):
            return attr.file_name
    return f"file_{msg.id}"


async def sync_channel(
    client: TelegramClient,
    channel,
    db: Database,
    progress: Optional[Callable[[int], None]] = None,
) -> SyncReport:
    report = SyncReport()
    seen: set[int] = set()

    # channel_id konsisten pakai marked id (-100...) seperti yang disimpan
    # uploader (msg.chat_id); row lama berformat telanjang dinormalisasi
    cid = utils.get_peer_id(channel)
    db.conn.execute(
        "UPDATE OR IGNORE files SET channel_id = ? WHERE channel_id = ?",
        (cid, channel.id),
    )
    db.conn.commit()

    async for msg in client.iter_messages(channel):
        report.scanned += 1
        if progress:
            progress(report.scanned)
        if msg.document is None:
            continue
        seen.add(msg.id)

        existing = db.find_by_message(cid, msg.id)
        if existing is None:
            db.add_file(
                original_name=_doc_name(msg),
                channel_id=cid,
                message_id=msg.id,
                size_bytes=msg.document.size,
                mime_type=msg.document.mime_type,
            )
            report.added += 1
        elif existing.status == "missing":
            db.set_status(existing.id, "synced")
            report.restored += 1

    for rec in db.list_files(include_deleted=False):
        if (
            rec.channel_id == cid
            and rec.message_id not in seen
            and rec.status in ("synced", "corrupt")
        ):
            db.set_status(rec.id, "missing")
            report.missing += 1

    return report
