"""Input login via dialog modal — jadi callback untuk core.auth.login.

Dengan qasync, dialog modal boleh dibuka dari dalam coroutine: exec()
memutar event loop Qt yang sama yang menjalankan asyncio.
"""
from PyQt6.QtWidgets import QInputDialog, QLineEdit


class LoginCancelled(Exception):
    """User menekan Cancel di tengah flow login."""


def _ask(label: str, echo: QLineEdit.EchoMode = QLineEdit.EchoMode.Normal) -> str:
    text, ok = QInputDialog.getText(None, "TeleDrive - Login", label, echo)
    text = text.strip()
    if not ok or not text:
        raise LoginCancelled
    return text


def ask_phone() -> str:
    return _ask("Nomor telepon (format internasional, mis. +628xx):")


def ask_code() -> str:
    return _ask("Kode OTP dari Telegram:")


def ask_password() -> str:
    return _ask("Password 2FA:", QLineEdit.EchoMode.Password)
