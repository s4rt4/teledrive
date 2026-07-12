"""Smoke test Fase 4+: boot GUI penuh, verifikasi fitur, auto-close.

Butuh session valid (tidak akan muncul dialog login).
Jalankan:  python scripts/smoke_ui.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import qasync
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from core import auth, channel, sync
from core.db import Database
from ui.main_window import MainWindow


def fail_if_prompted() -> str:
    print("FAIL: session tidak valid")
    sys.exit(1)


def main() -> None:
    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    close_event = asyncio.Event()
    app.aboutToQuit.connect(close_event.set)

    refs = {}
    checks = {"ok": False}

    async def bootstrap() -> None:
        try:
            await run_checks()
            checks["ok"] = True
        except Exception:
            import traceback
            traceback.print_exc()
        QTimer.singleShot(6000 if checks["ok"] else 0, app.quit)

    async def run_checks() -> None:
        client = auth.create_client()
        db = Database()
        reconnected = await auth.login(
            client, fail_if_prompted, fail_if_prompted, fail_if_prompted
        )
        assert reconnected
        print("1. Login    : OK (reconnect tanpa OTP)")

        ch = await channel.get_storage_channel(client, db)
        print(f"2. Channel  : OK - id={ch.id}")

        # antrian sisa bikin dialog "lanjutkan upload?" modal — blok smoke
        db.queue_clear()
        win = MainWindow(client, db, ch)
        refs.update(client=client, db=db, win=win)
        win.show()
        rows = win.browser.count()
        print(f"3. Window   : OK - tampil, browser berisi {rows} item dari DB")

        # Probe search dengan record buatan sendiri — jangan bergantung
        # pada sisa data test fase sebelumnya (bisa sudah dihapus).
        probe = "smoke_search_probe_9f3.bin"
        pid = db.add_file(probe, channel_id=ch.id, message_id=10**9)
        try:
            win.search_edit.setText("probe_9f3")
            assert win.browser.count() == 1, "search probe harusnya 1 hit"
            win.search_edit.setText("")
        finally:
            db.conn.execute("DELETE FROM files WHERE id = ?", (pid,))
            db.conn.commit()
        win.refresh()
        print("4. Search   : OK - filter live jalan")

        fid = db.create_folder("Folder Uji Smoke")
        win.refresh()
        kinds = [win.browser.entry(i)[0] for i in range(win.browser.count())]
        assert "folder" in kinds, "folder baru harusnya muncul di browser"
        db.rename_folder(fid, "Folder Uji Rename")
        win.refresh()
        names = [
            e[1].name for i in range(win.browser.count())
            if (e := win.browser.entry(i))[0] == "folder"
        ]
        assert "Folder Uji Rename" in names, "rename folder harusnya terlihat"
        db.delete_folder(fid)
        win.refresh()
        print("5. Folder   : OK - buat, rename & hapus folder virtual jalan")

        grid_count = win.browser.count()
        win.browser.set_display_mode("list")
        win.refresh()
        assert win.browser.count() == grid_count, \
            "mode list harusnya berisi item yang sama"
        win.browser.set_display_mode("grid")
        win.refresh()
        print("6. ListMode : OK - toggle grid/list konsisten")

        qid = db.queue_add(r"C:\tidak\ada\file.bin", None)
        assert db.queue_count() == 1
        item = db.queue_next()
        assert item.id == qid and item.local_path.endswith("file.bin")
        db.queue_remove(qid)
        assert db.queue_count() == 0
        print("7. Queue    : OK - persist queue roundtrip jalan")

        report = await sync.sync_channel(client, ch, db)
        assert report.scanned >= 1, "channel harusnya punya message"
        win.refresh()
        print(f"8. Sync     : OK - {report.summary()}")

    with loop:
        loop.create_task(bootstrap())
        loop.run_until_complete(close_event.wait())

    if checks["ok"]:
        print("\nSMOKE TEST LOLOS")
    else:
        print("\nSMOKE TEST GAGAL")
        sys.exit(1)


if __name__ == "__main__":
    main()
