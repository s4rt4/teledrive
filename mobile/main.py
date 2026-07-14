"""TeleDrive Android — Fase 6.3: UI KivyMD penuh (paritas desktop).

Reuse core/ tanpa perubahan (auth, channel, db, sync, uploader,
downloader, previewer, thumbs, renamer, deleter). core/ dan config/
disalin CI ke folder ini saat build (.github/workflows/android.yml) —
sumbernya tetap satu di root repo.

Kivy dan Telethon berbagi SATU event loop asyncio (async_run) — pola
qasync di desktop. Login memakai core.auth.login dengan callback async
yang await asyncio.Future dari tombol (pola ui/login_dialog.py — JANGAN
blokir loop dengan dialog modal).

Data (session/DB/cache) di storage privat app: config.settings membaca
env ANDROID_PRIVATE (diset python-for-android saat start).

Smoke test UI di PC (tanpa Telegram):
  TELEDRIVE_UI_SMOKE=login|browser python mobile/main.py
menyimpan screenshot lalu keluar — dipakai verifikasi layout sebelum
build APK.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# Di APK core/+config/ ada di sebelah main.py; saat dev di PC pakai
# source tree root repo
sys.path.insert(
    0, str(_HERE if (_HERE / "core").exists() else _HERE.parent)
)

_SMOKE = os.environ.get("TELEDRIVE_UI_SMOKE", "")
if _SMOKE:
    # Isolasi total dari data desktop: session yang sama dipakai dua
    # instance = AuthKeyDuplicated (auth key dicabut Telegram!)
    os.environ.setdefault(
        "TELEDRIVE_DATA_DIR", tempfile.mkdtemp(prefix="td_smoke_")
    )

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.screenmanager import NoTransition, ScreenManager
from kivymd.app import MDApp
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField
from kivymd.toast import toast

if _SMOKE:
    Window.size = (400, 800)

from config import settings
from core import auth
from core.channel import get_storage_channel
from core.db import Database

from browser import BrowserScreen, PreviewScreen

try:
    from apicreds import API_HASH, API_ID
except ImportError:
    API_ID, API_HASH = 0, ""


class LoginScreen(MDScreen):
    """Kartu login bertahap: (api_id/api_hash sekali) → nomor → OTP → 2FA.
    Input diserahkan lewat asyncio.Future — dipakai sebagai callback
    core.auth.login."""

    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self._fut = None
        self._allow_empty = False

        anchor = AnchorLayout(padding=dp(20))
        self.card = MDCard(
            orientation="vertical", padding=dp(24), spacing=dp(14),
            size_hint=(0.94, None), adaptive_height=True,
            radius=[dp(20)],
        )

        title = MDLabel(
            text="TeleDrive", font_style="H4", halign="center",
            size_hint_y=None, height=dp(48),
        )
        subtitle = MDLabel(
            text="Penyimpanan pribadi di Telegram", halign="center",
            theme_text_color="Secondary", font_style="Caption",
            size_hint_y=None, height=dp(20),
        )
        self.status = MDLabel(
            text="Menyiapkan…", halign="center",
            theme_text_color="Secondary",
            size_hint_y=None, height=dp(44),
        )
        self.in_api_id = MDTextField(
            hint_text="api_id (my.telegram.org/apps)", input_filter="int"
        )
        self.in_api_hash = MDTextField(hint_text="api_hash")
        self.field = MDTextField(
            hint_text="Nomor telepon, mis. +628123456789"
        )
        self.btn = MDRaisedButton(
            text="Lanjut", size_hint=(1, None), height=dp(48),
            disabled=True,
        )
        self.btn.bind(on_release=self._submit)

        for w in (title, subtitle, self.status, self.in_api_id,
                  self.in_api_hash, self.field, self.btn):
            self.card.add_widget(w)
        anchor.add_widget(self.card)
        self.add_widget(anchor)
        self.hide_api_fields()  # default: tampil hanya kalau creds kosong

    def show_api_fields(self):
        if self.in_api_id.parent is None:
            # sisip lagi di atas field utama (index dihitung dari akhir)
            idx = self.card.children.index(self.field) + 1
            self.card.add_widget(self.in_api_hash, index=idx)
            self.card.add_widget(self.in_api_id, index=idx + 1)

    def hide_api_fields(self):
        for w in (self.in_api_id, self.in_api_hash):
            if w.parent is not None:
                self.card.remove_widget(w)

    def read_api_fields(self) -> tuple[int, str]:
        try:
            api_id = int(self.in_api_id.text.strip())
        except ValueError:
            api_id = 0
        return api_id, self.in_api_hash.text.strip()

    def _submit(self, *_):
        if self._fut is not None and not self._fut.done():
            value = self.field.text.strip()
            if value or self._allow_empty:
                self._fut.set_result(value)

    async def ask(
        self, hint: str, btn_text: str = "Lanjut",
        password: bool = False, allow_empty: bool = False,
    ) -> str:
        self.field.text = ""
        self.field.hint_text = hint
        self.field.password = password
        self.btn.text = btn_text
        self.btn.disabled = False
        self._allow_empty = allow_empty
        self._fut = asyncio.get_running_loop().create_future()
        value = await self._fut
        self._fut = None
        self.btn.disabled = True
        return value


class TeleDriveApp(MDApp):
    title = "TeleDrive"

    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Blue"
        self.client = None
        self.db = None
        self.channel = None
        self.me = None
        self._phone = ""

        self.sm = ScreenManager(transition=NoTransition())
        self.login = LoginScreen(self, name="login")
        self.browser = BrowserScreen(self, name="browser")
        self.preview = PreviewScreen(self, name="preview")
        for s in (self.login, self.browser, self.preview):
            self.sm.add_widget(s)

        Window.bind(on_keyboard=self._on_key)
        return self.sm

    def on_start(self):
        if _SMOKE:
            self._smoke(_SMOKE)
            return
        self.run_task(self._bootstrap())

    def on_pause(self):
        return True  # jangan dibunuh saat pindah app — transfer lanjut

    def _on_key(self, window, key, *args):
        if key == 27:  # tombol back Android / Esc
            if self.sm.current == "preview":
                self.sm.current = "browser"
                return True
            if self.sm.current == "browser":
                return self.browser.handle_back()
        return False

    # ---- util task ----

    def run_task(self, coro):
        return asyncio.create_task(self._guarded(coro))

    async def _guarded(self, coro):
        try:
            await coro
        except Exception as e:
            try:
                toast(f"{type(e).__name__}: {e}")
            except Exception:
                pass

    # ---- kredensial & data ----

    def _migrate_poc_data(self):
        """Session/creds dari PoC 6.1 (Kivy user_data_dir) → DATA_DIR
        kalau lokasinya beda, supaya tidak perlu login ulang."""
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

    # ---- callback login (dipakai core.auth.login) ----

    async def _ask_phone(self) -> str:
        if self._phone:
            return self._phone
        return await self.login.ask(
            "Nomor telepon, mis. +628123456789", "Kirim Kode"
        )

    async def _ask_code(self) -> str:
        self.login.status.text = "Kode dikirim ke app Telegram Anda"
        return await self.login.ask("Kode OTP (cek app Telegram)", "Masuk")

    async def _ask_password(self) -> str:
        self.login.status.text = "Akun dilindungi verifikasi 2 langkah"
        return await self.login.ask("Password 2FA", "Masuk", password=True)

    # ---- flow ----

    async def _bootstrap(self):
        login = self.login
        self._migrate_poc_data()
        api_id, api_hash = self._load_creds()

        if not api_id:
            login.show_api_fields()
            login.status.text = (
                "Login pertama — isi kredensial API dari my.telegram.org/apps"
            )
            while True:
                phone = await login.ask(
                    "Nomor telepon, mis. +628123456789", "Kirim Kode"
                )
                api_id, api_hash = login.read_api_fields()
                if api_id and api_hash:
                    break
                login.status.text = "Isi api_id & api_hash dulu"
            self._save_creds(api_id, api_hash)
            self._phone = phone
            login.hide_api_fields()

        # settings.get_api_credentials() membaca env — pengganti .env
        os.environ["TELEGRAM_API_ID"] = str(api_id)
        os.environ["TELEGRAM_API_HASH"] = api_hash

        while True:
            try:
                if self.client is None:
                    self.client = auth.create_client()
                login.status.text = "Menghubungi Telegram…"
                await auth.login(
                    self.client, self._ask_phone,
                    self._ask_code, self._ask_password,
                )
                break
            except Exception as e:
                self._phone = ""  # jangan ulangi nomor yang gagal
                login.status.text = f"{type(e).__name__}: {e}"
                await login.ask(
                    "(ketuk untuk coba lagi)", "Coba Lagi", allow_empty=True
                )

        login.status.text = "Menyiapkan…"
        self.me = await self.client.get_me()
        if getattr(self.me, "premium", False):
            # akun Premium: limit upload Telegram 4 GB — pakai 3,5 GB aman
            settings.MAX_UPLOAD_SIZE = int(3.5 * 1024**3)
        self.db = Database()
        self.channel = await get_storage_channel(self.client, self.db)
        self.sm.current = "browser"
        self.browser.start()

    # ---- smoke test UI (tanpa Telegram, data dummy) ----

    def _smoke(self, mode: str):
        def to_browser(*_):
            self.db = Database()
            fid = self.db.create_folder("Dokumen")
            self.db.create_folder("Foto Liburan")
            demo = [
                ("Laporan Q2.pdf", "application/pdf", 2_400_000, None),
                ("Screenshot_16.jpg", "image/jpeg", 340_000, None),
                ("Backup proyek.zip", "application/zip", 88_000_000, None),
                ("catatan.txt", "text/plain", 4_200, None),
                ("video demo.mp4", "video/mp4", 154_000_000, fid),
            ]
            for i, (nm, mime, size, folder) in enumerate(demo, start=1):
                rid = self.db.add_file(
                    original_name=nm, channel_id=-100_1, message_id=i,
                    size_bytes=size, mime_type=mime,
                )
                self.db.move_file(rid, folder)
            self.sm.current = "browser"
            self.browser.start()

        if mode == "browser":
            # switch setelah frame pertama — meniru flow login sungguhan
            Clock.schedule_once(to_browser, 1)
        shot = os.environ.get(
            "TELEDRIVE_UI_SHOT", f"smoke_{mode}.png"
        )

        def snap(*_):
            # glReadPixels membaca back buffer — untuk scene statis isinya
            # frame basi; render dulu frame segar tanpa flip
            Window.dispatch("on_draw")
            Window.screenshot(name=shot)

        # Di async mode Windows, tick interval Kivy (transisi screen)
        # jalan sangat jarang — beri waktu longgar sebelum capture
        Clock.schedule_once(snap, 8)
        Clock.schedule_once(lambda *_: self.stop(), 9)


if __name__ == "__main__":
    asyncio.run(TeleDriveApp().async_run(async_lib="asyncio"))
