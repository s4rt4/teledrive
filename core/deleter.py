"""Hapus file: hard-delete message di Telegram, soft-delete di DB.

Row berstatus 'deleted' disembunyikan dari list default
(db.list_files(include_deleted=False)).
"""
from telethon import TelegramClient

from core.db import Database, FileRecord


async def delete_file(
    client: TelegramClient, channel, db: Database, record: FileRecord
) -> None:
    await client.delete_messages(channel, [record.message_id])
    db.set_status(record.id, "deleted")
