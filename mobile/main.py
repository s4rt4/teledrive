"""TeleDrive Android — Fase 6.2: core/ dipakai penuh di Android.

Reuse core/ tanpa perubahan: auth (login via callback), channel (cache
id di meta), db (SQLite), sync (recovery channel→DB), downloader
(progress + verifikasi sha256). core/ dan config/ disalin CI ke folder
ini saat build (.github/workflows/android.yml) — di repo sumbernya
tetap satu, di root.

Session, DB, dan hasil download di storage privat app: config.settings
memakai env ANDROID_PRIVATE (diset python-for-android saat start).

Kivy dan Telethon berbagi SATU event loop asyncio (async_run) — pola
yang sama dengan qasync di desktop. Login memakai core.auth.login
dengan callback async yang await asyncio.Future dari tombol (pola
ui/login_dialog.py — JANGAN blokir loop dengan dialog modal).

Kredensial API: apicreds.py (ditulis CI dari repo secrets, tidak
di-commit) atau diminta sekali di UI lalu disimpan creds.json di
storage privat; keduanya di-export ke env supaya
settings.get_api_credentials() jalan tanpa .env.
"""
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# Di APK core/+config/ ada di sebelah main.py; saat dev di PC pakai
# source tree root repo
sys.path.insert(
    0, str(_HERE if (_HERE / "core").exists() else _HERE.parent)
)

from kivy.app import App
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from config import settings
from core import auth
from core.channel import get_storage_channel
from core.db import Database, FileRecord
from core.downloader import IntegrityError, download_file
from core.sync import sync_channel

try:
    from apicreds import API_HASH, API_ID
except ImportError:
    API_ID, API_HASH = 0, ""

BG = (0.07, 0.08, 0.10, 1)
CARD = (0.13, 0.15, 0.19, 1)
TEXT = (0.92, 0.94, 0.97, 1)
ACCENT = (0.15, 0.55, 0.91, 1)


class TeleDriveApp(App):
    title = "TeleDrive"

    def build(self):
        Window.clearcolor = BG
        self.client = None
        self.db = None
        self.channel = None
        self._pending = None  # Future menunggu input tombol
        self._phone = ""
        self._busy = False  # satu transfer pada satu waktu

        root = BoxLayout(
            orientation="vertical", padding=dp(16), spacing=dp(8)
        )

        self.status = Label(
            text="Menyiapkan…", size_hint_y=None, height=dp(56),
            color=TEXT, halign="center", valign="middle",
        )
        self.status.bind(
            size=lambda w, s: setattr(w, "text_size", (s[0], s[1]))
        )
        root.add_widget(self.status)

        self.progress = ProgressBar(
            max=1, value=0, size_hint_y=None, height=dp(6), opacity=0
        )
        root.add_widget(self.progress)

        self.in_api_id = self._input(
            "api_id (my.telegram.org/apps)", input_filter="int"
        )
        self.in_api_hash = self._input("api_hash")
        self.in_value = self._input("Nomor telepon, mis. +628123456789")
        for w in (self.in_api_id, self.in_api_hash, self.in_value):
            root.add_widget(w)

        self.btn = Button(
            text="Lanjut", size_hint_y=None, height=dp(52),
            background_normal="", background_color=ACCENT, color=TEXT,
        )
        self.btn._full_height = dp(52)
        self.btn.bind(on_release=self._on_button)
        root.add_widget(self.btn)

        self.btn_sync = Button(
            text="Sinkronkan", size_hint_y=None, height=dp(52),
            background_normal="", background_color=ACCENT, color=TEXT,
        )
        self.btn_sync._full_height = dp(52)
        self.btn_sync.bind(
            on_release=lambda *_: asyncio.create_task(self._sync())
        )
        self._hide(self.btn_sync)
        root.add_widget(self.btn_sync)

        self.filebox = BoxLayout(
            orientation="vertical", size_hint_y=None, spacing=dp(4)
        )
        self.filebox.bind(
            minimum_height=lambda w, h: setattr(w, "height", h)
        )
        scroll = ScrollView()
        scroll.add_widget(self.filebox)
        root.add_widget(scroll)

        return root

    @staticmethod
    def _input(hint: str, **kwargs) -> TextInput:
        w = TextInput(
            hint_text=hint, multiline=False, size_hint_y=None,
            height=dp(48), **kwargs
        )
        w._full_height = dp(48)
        return w

    @staticmethod
    def _hide(w):
        w.opacity = 0
        w.disabled = True
        w.height = 0

    @staticmethod
    def _show(w):
        w.opacity = 1
        w.disabled = False
        w.height = w._full_height

    def on_start(self):
        asyncio.create_task(self._bootstrap())

    # ---- kredensial & data ----

    def _migrate_poc_data(self):
        """Session + creds dari PoC 6.1 (Kivy user_data_dir) pindah ke
        settings.DATA_DIR kalau lokasinya beda — supaya tidak login ulang."""
        try:
            old = Path(self.user_data_dir)
        except Exception:
            return
        if old == settings.DATA_DIR:
            return
        for name in ("teledrive.session", "creds.json"):
            src, dst = old / name, settings.DATA_DIR / name
            try:
                if src.exists() and not dst.exists():
                    shutil.copy2(src, dst)
            except OSError:
                pass

    def _creds_path(self) -> Path:
        return settings.DATA_DIR / "creds.json"

    def _load_creds(self) -> tuple[int, str]:
        if API_ID and API_HASH:
            return API_ID, API_HASH
        try:
            with open(self._creds_path(), encoding="utf-8") as f:
                data = json.load(f)
            return int(data["api_id"]), data["api_hash"]
        except (OSError, ValueError, KeyError):
            return 0, ""

    def _save_creds(self, api_id: int, api_hash: str) -> None:
        with open(self._creds_path(), "w", encoding="utf-8") as f:
            json.dump({"api_id": api_id, "api_hash": api_hash}, f)

    # ---- input via Future (callback async untuk core.auth.login) ----

    def _on_button(self, *_):
        if self._pending is not None and not self._pending.done():
            value = self.in_value.text.strip()
            if value:
                self._pending.set_result(value)

    async def _ask_input(
        self, hint: str, btn_text: str = "Lanjut", password: bool = False
    ) -> str:
        self.in_value.text = ""
        self.in_value.hint_text = hint
        self.in_value.password = password
        self.btn.text = btn_text
        self._show(self.in_value)
        self._show(self.btn)
        self._pending = asyncio.get_running_loop().create_future()
        value = await self._pending
        self._pending = None
        self.btn.disabled = True
        return value

    async def _ask_phone(self) -> str:
        if self._phone:
            return self._phone
        return await self._ask_input(
            "Nomor telepon, mis. +628123456789", "Kirim Kode"
        )

    async def _ask_code(self) -> str:
        self.status.text = "Kode dikirim ke app Telegram Anda"
        return await self._ask_input("Kode OTP (cek app Telegram)", "Masuk")

    async def _ask_password(self) -> str:
        self.status.text = "Akun dilindungi verifikasi 2 langkah"
        return await self._ask_input("Password 2FA", "Masuk", password=True)

    # ---- flow ----

    async def _bootstrap(self):
        self._migrate_poc_data()
        api_id, api_hash = self._load_creds()

        if not api_id:
            self.status.text = (
                "Login pertama: isi kredensial API dari my.telegram.org/apps"
            )
            self._show(self.in_api_id)
            self._show(self.in_api_hash)
            while True:
                phone = await self._ask_input(
                    "Nomor telepon, mis. +628123456789", "Kirim Kode"
                )
                try:
                    api_id = int(self.in_api_id.text.strip())
                except ValueError:
                    api_id = 0
                api_hash = self.in_api_hash.text.strip()
                if api_id and api_hash:
                    break
                self.status.text = "Isi api_id & api_hash dulu"
            self._save_creds(api_id, api_hash)
            self._phone = phone
        self._hide(self.in_api_id)
        self._hide(self.in_api_hash)

        # settings.get_api_credentials() membaca env — tanpa .env di Android
        os.environ["TELEGRAM_API_ID"] = str(api_id)
        os.environ["TELEGRAM_API_HASH"] = api_hash

        try:
            self.client = auth.create_client()
            self.status.text = "Menghubungi Telegram…"
            await auth.login(
                self.client,
                self._ask_phone,
                self._ask_code,
                self._ask_password,
            )
        except Exception as e:
            self.status.text = f"{type(e).__name__}: {e}"
            self._show(self.btn)
            return

        self._hide(self.in_value)
        self._hide(self.btn)
        await self._main_flow()

    async def _main_flow(self):
        me = await self.client.get_me()
        name = me.first_name or me.username or "?"
        self.status.text = f"Masuk sebagai {name} — mencari channel…"
        self.db = Database()
        self.channel = await get_storage_channel(self.client, self.db)
        self._show(self.btn_sync)
        await self._sync()

    async def _sync(self):
        if self._busy:
            return
        self._busy = True
        self.btn_sync.disabled = True
        self.status.text = "Sinkronisasi…"

        def prog(n: int):
            if n % 25 == 0:
                self.status.text = f"Sinkronisasi… {n} message dipindai"

        try:
            report = await sync_channel(
                self.client, self.channel, self.db, progress=prog
            )
        except Exception as e:
            self.status.text = f"{type(e).__name__}: {e}"
            return
        finally:
            self._busy = False
            self.btn_sync.disabled = False

        self._refresh_list()
        total_mb = self.db.total_synced_bytes() / 1024**2
        self.status.text = (
            f"{report.summary()} — total {total_mb:.0f} MB tersinkron"
        )

    def _refresh_list(self):
        self.filebox.clear_widgets()
        for rec in self.db.list_files():
            if rec.status != "synced":
                continue
            size_mb = (rec.size_bytes or 0) / 1024**2
            btn = Button(
                text=f"{rec.original_name}  —  {size_mb:.1f} MB",
                size_hint_y=None, height=dp(52),
                background_normal="", background_color=CARD, color=TEXT,
                halign="left", valign="middle",
                shorten=True, shorten_from="right",
            )
            btn.bind(
                size=lambda b, s: setattr(
                    b, "text_size", (s[0] - dp(16), s[1])
                )
            )
            btn.bind(
                on_release=lambda b, r=rec: asyncio.create_task(
                    self._download(r)
                )
            )
            self.filebox.add_widget(btn)

    async def _download(self, rec: FileRecord):
        """Unduh ke storage privat app dengan progress + verifikasi sha256.
        Simpan ke Download/ publik (SAF) menyusul di 6.3."""
        if self._busy:
            return
        self._busy = True
        dest_dir = settings.DATA_DIR / "downloads"
        dest_dir.mkdir(parents=True, exist_ok=True)
        self.progress.value = 0
        self.progress.max = rec.size_bytes or 1
        self.progress.opacity = 1
        self.status.text = f"Mengunduh {rec.original_name}…"

        def prog(cur: int, total: int):
            self.progress.max = total or 1
            self.progress.value = cur

        try:
            path = await download_file(
                self.client,
                self.channel,
                rec.message_id,
                dest_dir / rec.original_name,
                progress_callback=prog,
                expected_sha256=rec.sha256,
            )
        except IntegrityError:
            self.db.set_status(rec.id, "corrupt")
            self.status.text = f"File corrupt: {rec.original_name}"
            self._refresh_list()
            return
        except Exception as e:
            self.status.text = f"{type(e).__name__}: {e}"
            return
        finally:
            self.progress.opacity = 0
            self._busy = False

        self.status.text = f"Tersimpan: {path}"


if __name__ == "__main__":
    asyncio.run(TeleDriveApp().async_run(async_lib="asyncio"))
