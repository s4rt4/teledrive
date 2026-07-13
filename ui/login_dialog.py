"""Halaman login TeleDrive — satu window, tiga langkah (nomor → OTP → 2FA).

Callback ask_* bersifat ASYNC: menampilkan halaman lalu menunggu
asyncio.Future yang di-set tombol submit. JANGAN ganti dengan dialog
modal (exec()) dari dalam coroutine login — nested event loop di bawah
qasync menghentikan task jaringan Telethon (RuntimeError "Cannot enter
into task ...") sehingga permintaan OTP tidak pernah terkirim.
"""
import asyncio
import re

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config import settings
from ui.styles import build_qss


class LoginCancelled(Exception):
    """User menutup window login di tengah flow."""


class RestartLogin(Exception):
    """User menekan "Ganti nomor" — ulangi flow dari awal."""


PAGE_PHONE, PAGE_CODE, PAGE_PASSWORD = 0, 1, 2

# Dipanggil ulang oleh Telethon di halaman yang sama = input ditolak
_REJECTED = {
    PAGE_PHONE: "Nomor ditolak Telegram. Periksa lagi formatnya.",
    PAGE_CODE: "Kode salah. Coba lagi.",
    PAGE_PASSWORD: "Password salah. Coba lagi.",
}

_BUSY_TEXT = "Menghubungi Telegram…"


def _normalize_phone(raw: str) -> str | None:
    """Bersihkan pemisah + lengkapi prefix; None kalau tetap tak valid.

    Telethon menolak nomor yang gagal parse dengan diam-diam meminta
    ulang — makanya validasi harus selesai di sini.
    """
    s = re.sub(r"[\s\-().]", "", raw)
    if s.startswith("00"):
        s = "+" + s[2:]
    elif s.startswith("0"):
        s = "+62" + s[1:]  # kebiasaan lokal: 08xx = +628xx
    elif not s.startswith("+"):
        s = "+" + s
    return s if re.fullmatch(r"\+\d{7,15}", s) else None


class LoginWindow(QWidget):
    def __init__(self, theme: str = "light") -> None:
        super().__init__()
        self.setWindowTitle("TeleDrive")
        self.setWindowIcon(QIcon(str(settings.PROJECT_ROOT / "teledrive.svg")))
        self.setObjectName("Root")
        self.setStyleSheet(build_qss(theme))
        self.setFixedSize(420, 560)

        self._future: asyncio.Future | None = None
        self._last_page: int | None = None
        self._error_pending: str | None = None
        self._closed = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 30, 30, 30)

        card = QFrame()
        card.setObjectName("DialogCard")
        outer.addWidget(card)

        v = QVBoxLayout(card)
        v.setContentsMargins(32, 36, 32, 32)
        v.setSpacing(6)

        logo = QLabel()
        logo.setPixmap(QIcon(str(settings.PROJECT_ROOT / "teledrive.svg")).pixmap(64, 64))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(logo)

        title = QLabel("TeleDrive")
        title.setObjectName("AppTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(title)

        subtitle = QLabel("Masuk dengan akun Telegram Anda")
        subtitle.setObjectName("LoginSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(subtitle)

        v.addSpacing(22)

        self.stack = QStackedWidget()
        v.addWidget(self.stack)
        v.addStretch()

        self._pages = [
            self._build_page(
                section="Nomor telepon",
                placeholder="+62 812 3456 7890",
                info="Format internasional. Nomor lokal 08xx juga dikenali.",
                button="Kirim Kode",
            ),
            self._build_page(
                section="Kode verifikasi",
                placeholder="12345",
                info="Kode dikirim ke aplikasi Telegram Anda, ke chat "
                "“Telegram” (bukan SMS).",
                button="Masuk",
                ghost="Ganti nomor",
            ),
            self._build_page(
                section="Password 2FA",
                placeholder="Password verifikasi dua langkah",
                info="Akun Anda dilindungi verifikasi dua langkah.",
                button="Masuk",
                password=True,
            ),
        ]

    def _build_page(
        self,
        section: str,
        placeholder: str,
        info: str,
        button: str,
        password: bool = False,
        ghost: str | None = None,
    ) -> dict:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        lbl = QLabel(section.upper())
        lbl.setObjectName("SectionLabel")
        lay.addWidget(lbl)

        edit = QLineEdit()
        edit.setObjectName("DialogInput")
        edit.setPlaceholderText(placeholder)
        edit.setMinimumHeight(40)
        if password:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        edit.returnPressed.connect(self._on_submit)
        lay.addWidget(edit)

        info_lbl = QLabel(info)
        info_lbl.setObjectName("InfoLabel")
        info_lbl.setWordWrap(True)
        lay.addWidget(info_lbl)

        err = QLabel()
        err.setObjectName("ErrorLabel")
        err.setWordWrap(True)
        err.hide()
        lay.addWidget(err)

        lay.addSpacing(8)

        btn = QPushButton(button)
        btn.setObjectName("PrimaryButton")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(40)
        btn.clicked.connect(self._on_submit)
        lay.addWidget(btn)

        ghost_btn = None
        if ghost:
            ghost_btn = QPushButton(ghost)
            ghost_btn.setObjectName("GhostButton")
            ghost_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            ghost_btn.clicked.connect(self._on_restart)
            lay.addWidget(ghost_btn)

        self.stack.addWidget(page)
        return {
            "edit": edit,
            "err": err,
            "btn": btn,
            "btn_text": button,
            "ghost": ghost_btn,
        }

    # ---- callback async untuk core.auth.login ----

    async def ask_phone(self) -> str:
        return await self._ask(PAGE_PHONE)

    async def ask_code(self) -> str:
        return await self._ask(PAGE_CODE)

    async def ask_password(self) -> str:
        return await self._ask(PAGE_PASSWORD)

    async def _ask(self, page: int) -> str:
        if self._closed:
            raise LoginCancelled

        if self._last_page == page and self._error_pending is None:
            self._error_pending = _REJECTED[page]
        self._last_page = page

        p = self._pages[page]
        if page != PAGE_PHONE:  # nomor dibiarkan agar bisa dikoreksi
            p["edit"].clear()
        p["edit"].setEnabled(True)
        p["btn"].setEnabled(True)
        p["btn"].setText(p["btn_text"])
        if p["ghost"]:
            p["ghost"].setEnabled(True)

        if self._error_pending:
            p["err"].setText(self._error_pending)
            p["err"].show()
            self._error_pending = None
        else:
            p["err"].hide()

        self.stack.setCurrentIndex(page)
        self.show()
        p["edit"].setFocus()

        self._future = asyncio.get_event_loop().create_future()
        try:
            return await self._future
        finally:
            self._future = None

    # ---- interaksi ----

    def _on_submit(self) -> None:
        if self._future is None or self._future.done():
            return
        page = self.stack.currentIndex()
        p = self._pages[page]
        text = p["edit"].text().strip()
        if not text:
            return

        if page == PAGE_PHONE:
            normalized = _normalize_phone(text)
            if normalized is None:
                p["err"].setText("Format nomor tidak valid. Contoh: +628123456789")
                p["err"].show()
                return
            text = normalized
            p["edit"].setText(normalized)

        p["err"].hide()
        p["edit"].setEnabled(False)
        p["btn"].setEnabled(False)
        p["btn"].setText(_BUSY_TEXT)
        if p["ghost"]:
            p["ghost"].setEnabled(False)
        self._future.set_result(text)

    def _on_restart(self) -> None:
        if self._future is not None and not self._future.done():
            self._future.set_exception(RestartLogin())

    def show_error(self, message: str) -> None:
        """Tampilkan error global pada permintaan halaman berikutnya."""
        self._error_pending = message
        self._last_page = None

    def finish(self, status: str) -> None:
        """Login sukses — tahan window dengan status sampai MainWindow siap."""
        p = self._pages[self.stack.currentIndex()]
        p["btn"].setText(status)

    def closeEvent(self, event) -> None:
        self._closed = True
        if self._future is not None and not self._future.done():
            self._future.set_exception(LoginCancelled())
        event.accept()
