"""Ganti nama / pindah folder: update DB + tulis caption message.

Atribut filename dokumen Telegram tidak bisa diubah tanpa re-upload,
jadi nama (dan folder — lihat core.captions) disimpan di caption.
core.sync memprioritaskan caption saat recovery, sehingga rename dan
struktur folder selamat dari rebuild DB dan tersinkron antar perangkat.
"""
from telethon import TelegramClient
from telethon.errors import MessageNotModifiedError

from core import captions
from core.db import Database, FileRecord


async def _edit_caption(
    client: TelegramClient, channel, message_id: int, caption: str
) -> None:
    try:
        await client.edit_message(channel, message_id, caption)
    except MessageNotModifiedError:
        pass  # caption sudah sama — DB tetap diupdate


async def rename_file(
    client: TelegramClient,
    channel,
    db: Database,
    record: FileRecord,
    new_name: str,
) -> None:
    caption = captions.build(new_name, db.folder_path(record.folder_id))
    await _edit_caption(client, channel, record.message_id, caption)
    db.rename_file(record.id, new_name)


async def move_file(
    client: TelegramClient,
    channel,
    db: Database,
    record: FileRecord,
    folder_id: int | None,
) -> None:
    """Pindah folder + publikasikan ke caption. Pindah KE root memakai
    penanda "dir: /" supaya perangkat lain ikut memindahkan."""
    path = db.folder_path(folder_id) if folder_id else captions.ROOT
    caption = captions.build(record.original_name, path)
    await _edit_caption(client, channel, record.message_id, caption)
    db.move_file(record.id, folder_id)
