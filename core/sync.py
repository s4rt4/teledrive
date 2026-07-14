"""Sinkronisasi DB lokal dengan isi channel storage.

Dua arah dalam satu jalan:
- Dokumen di channel yang belum tercatat -> tambah record (recovery
  kalau DB hilang / dipakai di PC lain). Nama & folder diambil dari
  caption message (format core.captions), fallback ke atribut filename
  dokumen.
- Record 'synced' yang message-nya sudah tidak ada di channel ->
  status 'missing' (terhapus lewat aplikasi Telegram langsung).
  Kalau muncul lagi, dipulihkan ke 'synced'.
- Propagasi antar perangkat: rename/pindah folder di perangkat lain
  menulis caption; sync menerapkannya ke record lokal (caption =
  sumber kebenaran). Tanpa baris dir di caption, folder lokal TIDAK
  disentuh (file lama yang foldernya belum dipublikasikan).

Record hasil recovery tidak punya sha256 (hash butuh isi file penuh) —
downloader otomatis skip verifikasi kalau sha kosong.
"""
import asyncio
from dataclasses import dataclass
from typing import Callable, Optional

from telethon import TelegramClient, utils
from telethon.errors import MessageNotModifiedError
from telethon.tl.types import DocumentAttributeFilename

from core import captions
from core.db import Database


@dataclass
class SyncReport:
    scanned: int = 0
    added: int = 0
    restored: int = 0
    missing: int = 0
    renamed: int = 0
    moved: int = 0

    def summary(self) -> str:
        text = (
            f"{self.scanned} message dipindai: {self.added} file baru "
            f"ditambahkan, {self.restored} dipulihkan, "
            f"{self.missing} hilang di Telegram"
        )
        if self.renamed or self.moved:
            text += (
                f", {self.renamed} nama & {self.moved} folder "
                "diselaraskan dari perangkat lain"
            )
        return text


def _attr_name(msg) -> str:
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

        cap_name, cap_dir = captions.parse(msg.message or "")
        name = cap_name or _attr_name(msg)

        existing = db.find_by_message(cid, msg.id)
        if existing is None:
            db.add_file(
                original_name=name,
                channel_id=cid,
                message_id=msg.id,
                size_bytes=msg.document.size,
                mime_type=msg.document.mime_type,
                folder_id=db.ensure_folder_path(cap_dir),
            )
            report.added += 1
            continue

        if existing.status == "missing":
            db.set_status(existing.id, "synced")
            report.restored += 1
        # rename dari perangkat lain — hanya kalau caption eksplisit
        if cap_name and cap_name != existing.original_name:
            db.rename_file(existing.id, cap_name)
            report.renamed += 1
        # pindah folder dari perangkat lain — "dir: /" = eksplisit root;
        # tanpa baris dir, folder lokal dibiarkan
        if cap_dir is not None:
            target = db.ensure_folder_path(cap_dir)
            if target != existing.folder_id:
                db.move_file(existing.id, target)
                report.moved += 1

    for rec in db.list_files(include_deleted=False):
        if (
            rec.channel_id == cid
            and rec.message_id not in seen
            and rec.status in ("synced", "corrupt")
        ):
            db.set_status(rec.id, "missing")
            report.missing += 1

    return report


async def publish_folders(
    client: TelegramClient,
    channel,
    db: Database,
    progress: Optional[Callable[[int], None]] = None,
) -> int:
    """Migrasi satu arah: tulis baris dir ke caption untuk record
    berfolder yang caption-nya belum memuat info folder (file dari era
    sebelum folder ikut caption). Return jumlah caption yang diedit.

    Edit sekuensial + jeda — edit massal ke channel yang sama mengundang
    FloodWait.
    """
    targets = [
        r for r in db.list_files()
        if r.status == "synced" and r.folder_id is not None
    ]
    if not targets:
        return 0

    msgs = await client.get_messages(
        channel, ids=[r.message_id for r in targets]
    )
    edited = 0
    for rec, msg in zip(targets, msgs):
        if msg is None or msg.document is None:
            continue
        _, cap_dir = captions.parse(msg.message or "")
        if cap_dir is not None:
            continue  # sudah pernah dipublikasikan
        caption = captions.build(
            rec.original_name, db.folder_path(rec.folder_id)
        )
        try:
            await client.edit_message(channel, rec.message_id, caption)
        except MessageNotModifiedError:
            continue
        edited += 1
        if progress:
            progress(edited)
        await asyncio.sleep(0.7)
    return edited
