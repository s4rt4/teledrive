"""Login & session management.

Callback phone/code/password di-inject dari luar supaya modul ini dipakai
dua arah: CLI test (Fase 1, pakai input()) dan dialog PyQt6 (Fase 4)
tanpa perubahan kode di sini.
"""
from typing import Awaitable, Callable

from telethon import TelegramClient

from config import settings

# Boleh sync atau async — Telethon menerima keduanya
StrCallback = Callable[[], str] | Callable[[], Awaitable[str]]


def create_client() -> TelegramClient:
    api_id, api_hash = settings.get_api_credentials()
    return TelegramClient(
        str(settings.SESSION_PATH),
        api_id,
        api_hash,
        flood_sleep_threshold=settings.FLOOD_SLEEP_THRESHOLD,
    )


async def login(
    client: TelegramClient,
    phone_callback: StrCallback,
    code_callback: StrCallback,
    password_callback: StrCallback,
) -> bool:
    """Connect + login kalau perlu.

    Return True kalau session lama masih valid (reconnect tanpa OTP,
    tidak ada callback yang dipanggil), False kalau baru saja login.
    """
    await client.connect()
    if await client.is_user_authorized():
        return True

    await client.start(
        phone=phone_callback,
        code_callback=code_callback,
        password=password_callback,
    )
    return False


async def logout(client: TelegramClient) -> None:
    """Log out dan hapus session di sisi server."""
    await client.log_out()
