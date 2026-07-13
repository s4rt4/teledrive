"""Entry point GUI: PyQt6 + qasync.

Telethon dan Qt berbagi satu event loop (qasync.QEventLoop) — semua
operasi async via asyncio.create_task, tanpa QThread.

Jalankan:  python main.py
"""
import asyncio
import sys

import qasync
from PyQt6.QtCore import QLockFile
from PyQt6.QtWidgets import QApplication, QMessageBox

from config import settings
from core import auth, channel
from core.db import Database
from ui import login_dialog
from ui.main_window import MainWindow


def main() -> None:
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
        try:
            await auth.login(
                client,
                login_dialog.ask_phone,
                login_dialog.ask_code,
                login_dialog.ask_password,
            )
        except login_dialog.LoginCancelled:
            app.quit()
            return
        except Exception as e:
            QMessageBox.critical(None, "TeleDrive - Login gagal", str(e))
            app.quit()
            return

        ch = await channel.get_storage_channel(client, db)

        me = await client.get_me()
        if getattr(me, "premium", False):
            # Premium boleh 4 GB per file; sisakan margin
            settings.MAX_UPLOAD_SIZE = int(3.5 * 1024**3)

        win = MainWindow(client, db, ch, me=me)
        refs.update(client=client, db=db, win=win)
        win.show()

    with loop:
        loop.create_task(bootstrap())
        loop.run_until_complete(close_event.wait())


if __name__ == "__main__":
    main()
