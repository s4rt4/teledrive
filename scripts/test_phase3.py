"""Test Fase 3 (tanpa UI): db.py + deleter.py + meta cache + dedup.

Jalankan:  python scripts/test_phase3.py
Butuh session Fase 1 valid dan channel dari Fase 2.

Yang dites:
1. Schema DB terbentuk di user data dir
2. Channel resolve via cache meta (run kedua tidak scan dialog)
3. Migrasi: message lama di channel (hasil test Fase 2) masuk ke DB
4. Upload dengan dedup hook -> tersimpan di DB
5. Upload file yang sama lagi -> deduped, tidak ada message baru
6. list_files + search
7. Delete: message hilang di Telegram, status='deleted' di DB
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from core import auth, channel, deleter, uploader
from core.db import Database


def make_test_file() -> str:
    path = os.path.join(tempfile.gettempdir(), "teledrive_test_1mb.bin")
    with open(path, "wb") as f:
        f.write(os.urandom(1024 * 1024))
    return path


def fail_if_prompted() -> str:
    print("FAIL: session tidak valid - jalankan `python main.py` dulu")
    sys.exit(1)


async def import_channel_history(client, ch, db: Database) -> int:
    """Masukkan semua message berisi file yang belum ada di DB.

    Dipakai untuk migrasi hasil Fase 2, dan berguna umum sebagai
    recovery kalau DB hilang (rebuild dari channel).
    """
    imported = 0
    known = {r.message_id for r in db.list_files(include_deleted=True)}
    async for msg in client.iter_messages(ch):
        if msg.file is None or msg.id in known:
            continue
        db.add_file(
            original_name=msg.file.name or f"file_{msg.id}",
            channel_id=ch.id,
            message_id=msg.id,
            size_bytes=msg.file.size,
            mime_type=msg.file.mime_type,
        )
        imported += 1
    return imported


async def main() -> None:
    db = Database()
    print(f"1. Schema   : OK - {settings.DB_PATH}")

    client = auth.create_client()
    await auth.login(client, fail_if_prompted, fail_if_prompted, fail_if_prompted)

    ch = await channel.get_storage_channel(client, db)
    cached = db.get_meta(channel.META_CHANNEL_ID)
    assert cached == str(ch.id), "channel_id harusnya tersimpan di meta"
    ch2 = await channel.get_storage_channel(client, db)  # run kedua: via cache
    assert ch2.id == ch.id
    print(f"2. Channel  : OK - id={ch.id} (cached di meta)")

    n = await import_channel_history(client, ch, db)
    print(f"3. Migrasi  : OK - {n} message lama diimpor ke DB")

    src = make_test_file()
    result = await uploader.upload_file(
        client, ch, src, find_by_sha256=db.find_by_sha256
    )
    assert not result.deduped
    file_id = db.save_upload(result)
    print(f"4. Upload   : OK - message_id={result.message_id}, db id={file_id}")

    again = await uploader.upload_file(
        client, ch, src, find_by_sha256=db.find_by_sha256
    )
    assert again.deduped, "upload kedua harusnya kena dedup"
    assert again.message_id == result.message_id, "tidak boleh ada message baru"
    print("5. Dedup    : OK - upload kedua di-skip, tidak ada message baru")

    names = [r.original_name for r in db.list_files()]
    assert "teledrive_test_1mb.bin" in names
    hits = db.search("1mb")
    assert len(hits) == 1 and hits[0].id == file_id
    print(f"6. Query    : OK - list={len(names)} file, search '1mb' -> 1 hit")

    record = db.get_file(file_id)
    await deleter.delete_file(client, ch, db, record)
    gone = await client.get_messages(ch, ids=record.message_id)
    assert gone is None, "message harusnya sudah terhapus di Telegram"
    assert db.get_file(file_id).status == "deleted"
    assert file_id not in [r.id for r in db.list_files()], "deleted harus tersembunyi"
    print("7. Delete   : OK - hilang di Telegram, status='deleted', tersembunyi dari list")

    print("\nSEMUA TES FASE 3 LOLOS")
    print("\nIsi DB sekarang (termasuk deleted):")
    for r in db.list_files(include_deleted=True):
        size = f"{(r.size_bytes or 0) / 1024**2:.1f} MB"
        print(f"  [{r.id}] {r.original_name}  {size}  msg={r.message_id}  {r.status}")

    db.close()
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
