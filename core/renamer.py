"""Ganti nama file: update DB + tulis nama baru sebagai caption message.

Atribut filename dokumen Telegram tidak bisa diubah tanpa re-upload,
jadi nama baru disimpan di caption — core.sync memprioritaskan caption
saat recovery, sehingga rename selamat dari rebuild DB.
"""
from telethon import TelegramClient
from telethon.errors import MessageNotModifiedError

from core.db import Database, FileRecord


async def rename_file(
    client: TelegramClient,
    channel,
    db: Database,
    record: FileRecord,
    new_name: str,
) -> None:
    try:
        await client.edit_message(channel, record.message_id, new_name)
    except MessageNotModifiedError:
        pass  # caption sudah sama — DB tetap diupdate
    db.rename_file(record.id, new_name)
