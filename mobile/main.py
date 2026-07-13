"""TeleDrive Android — PoC sub-fase 6.1.

Bukti python-for-android sanggup menjalankan Telethon: login
(nomor → OTP → 2FA) lalu tampilkan isi channel TeleDrive_Storage.
Sengaja self-contained (belum reuse core/) — berbagi core/ mulai 6.2.

Kivy dan Telethon berbagi SATU event loop asyncio (async_run), pola
yang sama dengan qasync di desktop: UI tidak pernah diblokir, semua
operasi jaringan lewat asyncio.create_task.

Kredensial API: dari apicreds.py (ditulis CI dari repo secrets, tidak
di-commit) — kalau tidak ada, diminta sekali di UI dan disimpan di
storage privat app.
"""
import asyncio
import json
import os

from kivy.app import App
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

try:
    from apicreds import API_HASH, API_ID
except ImportError:
    API_ID, API_HASH = 0, ""

CHANNEL_TITLE = "TeleDrive_Storage"


class TeleDrivePoC(App):
    title = "TeleDrive PoC"

    def build(self):
        self.client = None
        self.phone = ""
        self.state = "phone"

        root = BoxLayout(
            orientation="vertical", padding=dp(16), spacing=dp(10)
        )

        self.status = Label(
            text="Menyiapkan…", size_hint_y=None, height=dp(48)
        )
        root.add_widget(self.status)

        self.in_api_id = TextInput(
            hint_text="api_id (my.telegram.org/apps)",
            multiline=False,
            input_filter="int",
            size_hint_y=None,
            height=dp(48),
        )
        self.in_api_hash = TextInput(
            hint_text="api_hash",
            multiline=False,
            size_hint_y=None,
            height=dp(48),
        )
        root.add_widget(self.in_api_id)
        root.add_widget(self.in_api_hash)

        self.in_value = TextInput(
            hint_text="Nomor telepon, mis. +628123456789",
            multiline=False,
            size_hint_y=None,
            height=dp(48),
        )
        root.add_widget(self.in_value)

        self.btn = Button(text="Kirim Kode", size_hint_y=None, height=dp(52))
        self.btn.bind(on_release=self._on_button)
        root.add_widget(self.btn)

        scroll = ScrollView()
        self.out = Label(text="", size_hint_y=None, halign="left")
        # label di dalam ScrollView butuh tinggi eksplisit mengikuti isi
        self.out.bind(
            texture_size=lambda lbl, size: setattr(lbl, "height", size[1])
        )
        self.out.bind(width=lambda lbl, w: setattr(lbl, "text_size", (w, None)))
        scroll.add_widget(self.out)
        root.add_widget(scroll)

        return root

    def on_start(self):
        asyncio.create_task(self._bootstrap())

    # ---- kredensial ----

    def _creds_path(self) -> str:
        return os.path.join(self.user_data_dir, "creds.json")

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

    # ---- flow ----

    async def _bootstrap(self):
        api_id, api_hash = self._load_creds()
        if api_id:
            self.in_api_id.opacity = 0
            self.in_api_id.disabled = True
            self.in_api_id.height = 0
            self.in_api_hash.opacity = 0
            self.in_api_hash.disabled = True
            self.in_api_hash.height = 0
            try:
                await self._ensure_client(api_id, api_hash)
                if await self.client.is_user_authorized():
                    await self._show_files()
                    return
            except Exception as e:
                self.status.text = f"{type(e).__name__}: {e}"
                return
        self.status.text = "Masukkan nomor telepon"

    async def _ensure_client(self, api_id: int, api_hash: str):
        if self.client is None:
            session = os.path.join(self.user_data_dir, "teledrive")
            self.client = TelegramClient(session, api_id, api_hash)
        if not self.client.is_connected():
            await self.client.connect()

    def _on_button(self, *_):
        if self.btn.disabled:
            return
        value = self.in_value.text.strip()
        if not value:
            return
        asyncio.create_task(self._advance(value))

    async def _advance(self, value: str):
        self.btn.disabled = True
        self.status.text = "Menghubungi Telegram…"
        try:
            if self.state == "phone":
                api_id, api_hash = self._load_creds()
                if not api_id:
                    api_id = int(self.in_api_id.text.strip() or 0)
                    api_hash = self.in_api_hash.text.strip()
                    if not api_id or not api_hash:
                        self.status.text = "Isi api_id & api_hash dulu"
                        return
                await self._ensure_client(api_id, api_hash)
                self.phone = value
                await self.client.send_code_request(value)
                self._save_creds(api_id, api_hash)
                self.state = "code"
                self.in_value.text = ""
                self.in_value.hint_text = "Kode OTP (cek app Telegram)"
                self.btn.text = "Masuk"
                self.status.text = "Kode dikirim ke app Telegram Anda"
            elif self.state == "code":
                try:
                    await self.client.sign_in(self.phone, code=value)
                except SessionPasswordNeededError:
                    self.state = "password"
                    self.in_value.text = ""
                    self.in_value.hint_text = "Password 2FA"
                    self.in_value.password = True
                    self.status.text = "Akun dilindungi verifikasi 2 langkah"
                    return
                await self._show_files()
            elif self.state == "password":
                await self.client.sign_in(password=value)
                await self._show_files()
        except Exception as e:
            self.status.text = f"{type(e).__name__}: {e}"
        finally:
            self.btn.disabled = False

    async def _show_files(self):
        me = await self.client.get_me()
        name = me.first_name or me.username or "?"
        self.status.text = f"Masuk sebagai {name} — mencari channel…"

        channel = None
        async for dialog in self.client.iter_dialogs():
            if dialog.is_channel and dialog.title == CHANNEL_TITLE:
                channel = dialog.entity
                break
        if channel is None:
            self.status.text = f"Channel {CHANNEL_TITLE} tidak ditemukan"
            return

        lines = []
        async for msg in self.client.iter_messages(channel, limit=100):
            if not msg.document:
                continue
            # Caption = sumber nama (kontrak rename desktop); fallback
            # ke atribut filename dokumen
            fname = (msg.message or "").strip()
            if not fname:
                fname = next(
                    (
                        a.file_name
                        for a in msg.document.attributes
                        if hasattr(a, "file_name")
                    ),
                    f"(msg {msg.id})",
                )
            lines.append(f"{fname}  —  {msg.document.size / 1024**2:.1f} MB")

        self.in_value.opacity = 0
        self.in_value.disabled = True
        self.btn.opacity = 0
        self.btn.disabled = True
        self.out.text = "\n".join(lines) if lines else "(channel kosong)"
        self.status.text = f"{len(lines)} file di {CHANNEL_TITLE}"


if __name__ == "__main__":
    asyncio.run(TeleDrivePoC().async_run(async_lib="asyncio"))
