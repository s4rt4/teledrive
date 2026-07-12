"""Test Fase 1: login CLI + verifikasi session reconnect tanpa OTP.

(Dulu ini isi main.py; dipindah ke sini saat main.py jadi launcher GUI.)

Jalankan:  python scripts/test_phase1.py
"""
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from core import auth


def ask_phone() -> str:
    return input("Nomor telepon (format internasional, mis. +628xx): ").strip()


def ask_code() -> str:
    return input("Kode OTP dari Telegram: ").strip()


def ask_password() -> str:
    return getpass.getpass("Password 2FA (kalau ada): ")


async def main() -> None:
    client = auth.create_client()

    print(f"Session : {settings.SESSION_PATH}.session")
    print(f"Data dir: {settings.DATA_DIR}")

    reconnected = await auth.login(client, ask_phone, ask_code, ask_password)

    me = await client.get_me()
    label = "reconnect tanpa OTP" if reconnected else "login baru"
    print(f"\nOK ({label}) - masuk sebagai: {me.first_name} (id={me.id})")

    await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except settings.ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
