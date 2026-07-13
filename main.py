"""Entry point GUI: PyQt6 + qasync.

Telethon dan Qt berbagi satu event loop (qasync.QEventLoop) — semua
operasi async via asyncio.create_task, tanpa QThread.

Jalankan:  python main.py
"""
import asyncio
import logging
import sys

import qasync
from PyQt6.QtCore import QLockFile
from PyQt6.QtWidgets import QApplication, QMessageBox
from telethon.errors import FloodWaitError

from config import settings
from core import auth, channel
from core.db import Database
from ui import login_dialog
from ui.main_window import MainWindow


def _friendly_error(e: Exception) -> str:
    if isinstance(e, FloodWaitError):
        return f"Terlalu banyak percobaan. Tunggu {e.seconds} detik lalu coba lagi."
    # str() beberapa error Telethon kosong — jangan tampilkan label kosong
    return str(e) or type(e).__name__


def main() -> None:
    # Exe windowed tidak punya konsol — tanpa log file, error mati diam-diam
    logging.basicConfig(
        filename=str(settings.DATA_DIR / "teledrive.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = QApplication(sys.argv)
    app.setApplicationName("TeleDrive")

    # Single instance: dua proses yang berbagi satu .session membuat
    # Telegram mencabut auth key-nya (AuthKeyDuplicatedError) — login ulang
    # paksa. QLockFile melepas lock otomatis saat proses mati/crash.
    lock = QLockFile(str(settings.DATA_DIR / "teledrive.lock"))
    if not lock.tryLock(100):
        QMessageBox.warning(
            None, "TeleDrive",
            "TeleDrive sudah berjalan (cek system tray). "
            "Dua instance bersamaan merusak session Telegram.",
        )
        return

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    close_event = asyncio.Event()
    app.aboutToQuit.connect(close_event.set)

    refs = {}  # jaga window & client tetap hidup (hindari GC)

    async def bootstrap() -> None:
        try:
            client = auth.create_client()
        except settings.ConfigError as e:
            QMessageBox.critical(None, "TeleDrive", str(e))
            app.quit()
            return

        db = Database()
        login_win = login_dialog.LoginWindow(theme=db.get_meta("theme") or "light")
        while True:
            try:
                await auth.login(
                    client,
                    login_win.ask_phone,
                    login_win.ask_code,
                    login_win.ask_password,
                )
                break
            except login_dialog.LoginCancelled:
                app.quit()
                return
            except login_dialog.RestartLogin:
                continue
            except Exception as e:
                logging.exception("Login gagal")
                login_win.show_error(_friendly_error(e))
                # Rem: error pra-interaksi (mis. offline) jangan spin ketat
                await asyncio.sleep(2)

        login_win.finish("Menyiapkan drive…")
        ch = await channel.get_storage_channel(client, db)

        me = await client.get_me()
        if getattr(me, "premium", False):
            # Premium boleh 4 GB per file; sisakan margin
            settings.MAX_UPLOAD_SIZE = int(3.5 * 1024**3)

        win = MainWindow(client, db, ch, me=me)
        refs.update(client=client, db=db, win=win)
        win.show()
        # Ditutup SETELAH MainWindow tampil: kalau login window jadi window
        # terakhir yang tertutup, Qt mengakhiri aplikasi lebih dulu
        login_win.close()

    with loop:
        loop.create_task(bootstrap())
        loop.run_until_complete(close_event.wait())


if __name__ == "__main__":
    main()
