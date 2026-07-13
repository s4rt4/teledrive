"""Konfigurasi terpusat: load .env + resolve semua path via platformdirs.

Session Telethon dan teledrive.db disimpan di user data dir, BUKAN di folder
project — folder aplikasi bisa read-only setelah di-package PyInstaller.
"""
import sys
from pathlib import Path

from dotenv import load_dotenv
from platformdirs import user_data_dir
import os

# Saat frozen (PyInstaller), source tree tidak ada — aset (teledrive.svg)
# di-bundle ke sys._MEIPASS; saat dev, root project = folder di atas config/
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys._MEIPASS)
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

APP_NAME = "TeleDrive"

# Semua data runtime di sini, misal di Windows:
# C:\Users\<user>\AppData\Local\TeleDrive
# appauthor=False: tanpa ini Windows dapat path dobel (TeleDrive\TeleDrive)
DATA_DIR = Path(user_data_dir(APP_NAME, appauthor=False))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# .env: DATA_DIR menang (satu-satunya lokasi saat sudah di-package),
# root project sebagai fallback saat dev. load_dotenv tidak menimpa
# variabel yang sudah ter-load, jadi urutan = prioritas.
load_dotenv(DATA_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")

SESSION_PATH = DATA_DIR / "teledrive"  # Telethon menambah .session sendiri
DB_PATH = DATA_DIR / "teledrive.db"

THUMB_DIR = DATA_DIR / "thumbs"  # cache thumbnail dari Telegram
THUMB_DIR.mkdir(parents=True, exist_ok=True)

PREVIEW_DIR = DATA_DIR / "preview_cache"  # file utuh untuk pratinjau
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
PREVIEW_CACHE_MAX = 1024**3  # 1 GB — terlama dihapus saat melebihi

STORAGE_CHANNEL_TITLE = "TeleDrive_Storage"

MAX_UPLOAD_SIZE = int(1.5 * 1024**3)  # tolak file > 1,5 GB

# FloodWait di bawah ambang ini di-sleep otomatis oleh Telethon
FLOOD_SLEEP_THRESHOLD = 60


class ConfigError(Exception):
    """Kredensial .env tidak ada / tidak valid."""


def get_api_credentials() -> tuple[int, str]:
    api_id = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()

    if not api_id or not api_hash:
        raise ConfigError(
            "TELEGRAM_API_ID / TELEGRAM_API_HASH belum diisi. "
            f"Buat file .env di {DATA_DIR} lalu isi dari https://my.telegram.org/apps"
        )
    if not api_id.isdigit():
        raise ConfigError("TELEGRAM_API_ID harus angka.")

    return int(api_id), api_hash
