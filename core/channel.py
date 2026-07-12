"""Cek/buat channel privat untuk storage.

Telethon tidak punya client.create_channel — harus raw API
(functions.channels.CreateChannelRequest).

channel_id di-cache di tabel meta biar tidak scan seluruh dialog tiap
start — pakai get_storage_channel(client, db).
"""
from telethon import TelegramClient
from telethon.tl import functions, types

from config import settings

META_CHANNEL_ID = "storage_channel_id"


async def get_storage_channel(client: TelegramClient, db=None):
    """Resolve channel storage, pakai cache meta kalau ada.

    db opsional (core.db.Database) — tanpa db, selalu scan dialog.
    """
    if db is not None:
        cached = db.get_meta(META_CHANNEL_ID)
        if cached:
            try:
                return await client.get_entity(types.PeerChannel(int(cached)))
            except (ValueError, TypeError):
                pass  # channel dihapus / session baru — fallback ke scan

    ch = await get_or_create_storage_channel(client)
    if db is not None:
        db.set_meta(META_CHANNEL_ID, str(ch.id))
    return ch


async def get_or_create_storage_channel(client: TelegramClient):
    """Return entity channel storage; buat kalau belum ada.

    Return entity (bukan cuma id) supaya bisa langsung dipakai
    send_file/get_messages tanpa resolusi ulang.
    """
    async for dialog in client.iter_dialogs():
        if dialog.is_channel and dialog.title == settings.STORAGE_CHANNEL_TITLE:
            return dialog.entity

    result = await client(
        functions.channels.CreateChannelRequest(
            title=settings.STORAGE_CHANNEL_TITLE,
            about="TeleDrive private storage - jangan hapus channel ini",
            megagroup=False,
        )
    )
    return result.chats[0]
