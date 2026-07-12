"""Kirim salinan file dari channel storage ke chat Telegram lain.

Pakai send_file dengan media message asal (bukan forward_messages)
supaya penerima tidak melihat header "diteruskan dari
TeleDrive_Storage" — file sampai sebagai kiriman biasa, tanpa
re-upload (media di-referensikan by id di sisi server).
"""
from telethon import TelegramClient

from core.db import FileRecord


async def send_copy(
    client: TelegramClient, channel, target, record: FileRecord
) -> None:
    msg = await client.get_messages(channel, ids=record.message_id)
    if msg is None or msg.document is None:
        raise FileNotFoundError(
            f"Message {record.message_id} tidak ada atau tidak berisi file"
        )
    await client.send_file(target, msg.media, caption=record.original_name)
