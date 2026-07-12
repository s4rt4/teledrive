"""Test Fase 2 (tanpa UI): channel + uploader + downloader + sha256.

Jalankan:  python scripts/test_phase2.py [path_file_test]
Kalau path tidak diberikan, dibuat file random 5 MB di %TEMP%.

Butuh session Fase 1 yang sudah valid (tidak akan minta OTP).
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from core import auth, channel, downloader, uploader
from core.hasher import compute_sha256


def make_test_file() -> str:
    path = os.path.join(tempfile.gettempdir(), "teledrive_test_5mb.bin")
    with open(path, "wb") as f:
        for _ in range(5):
            f.write(os.urandom(1024 * 1024))
    return path


def progress(current: int, total: int) -> None:
    pct = current * 100 // total if total else 0
    print(f"\r  {pct:3d}% ({current}/{total} bytes)", end="", flush=True)


def fail_if_prompted() -> str:
    print("FAIL: session tidak valid - jalankan `python main.py` dulu (Fase 1)")
    sys.exit(1)


async def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else make_test_file()
    print(f"File test : {src} ({os.path.getsize(src)} bytes)")

    client = auth.create_client()
    reconnected = await auth.login(
        client, fail_if_prompted, fail_if_prompted, fail_if_prompted
    )
    assert reconnected, "harusnya reconnect dari session Fase 1"
    print("1. Login    : OK (reconnect tanpa OTP)")

    ch = await channel.get_or_create_storage_channel(client)
    print(f"2. Channel  : OK - '{ch.title}' (id={ch.id})")

    # Tes limit: kecilkan limit sementara, file 5 MB harus ditolak
    real_limit = settings.MAX_UPLOAD_SIZE
    settings.MAX_UPLOAD_SIZE = 1024
    try:
        await uploader.upload_file(client, ch, src)
        print("3. Limit    : FAIL - file besar tidak ditolak")
        sys.exit(1)
    except uploader.FileTooLargeError:
        print("3. Limit    : OK - FileTooLargeError ter-raise")
    finally:
        settings.MAX_UPLOAD_SIZE = real_limit

    print("4. Upload   :")
    result = await uploader.upload_file(client, ch, src, progress_callback=progress)
    print(f"\n   OK - message_id={result.message_id}, sha256={result.sha256[:16]}...")

    dest = os.path.join(tempfile.gettempdir(), "teledrive_test_download.bin")
    print("5. Download :")
    saved = await downloader.download_file(
        client, ch, result.message_id, dest,
        progress_callback=progress, expected_sha256=result.sha256,
    )
    print(f"\n   OK - tersimpan di {saved}, sha256 cocok")

    assert compute_sha256(saved) == compute_sha256(src)
    print("\nSEMUA TES FASE 2 LOLOS")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
