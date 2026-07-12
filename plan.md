# TeleDrive Desktop — Technical Plan (Revisi)

## Stack
- Python 3.11+, PyQt6, Telethon (async), SQLite (modul `sqlite3` bawaan — tanpa SQLAlchemy), `python-dotenv`, `platformdirs`, `qasync`
- Packaging: PyInstaller (fase terakhir, terpisah dari integrasi UI)

## Keputusan Desain
- **Threading: `qasync` saja, tanpa QThread.** Telethon jalan di event loop Qt itu sendiri. Upload/download dipanggil via `asyncio.create_task(...)`, dan `progress_callback` boleh langsung update widget karena sudah berada di thread UI. Tidak ada thread juggling manual.
- **Limit ukuran file: tolak file > 1,5 GB.** Validasi ukuran sebelum masuk queue upload; file yang melebihi limit ditolak dengan pesan jelas di UI (tidak masuk DB, tidak ada splitting/chunking).
- **Upload sekuensial.** Queue upload memproses satu file pada satu waktu. Tidak ada upload paralel ke channel yang sama — mencegah FloodWait panjang.
- **Dedup via sha256.** Sebelum upload, cek hash di DB; kalau sudah ada file dengan sha256 sama, skip upload dan tawarkan referensi ke record yang ada.

## Lokasi File (Windows-aware)
Pakai `platformdirs.user_data_dir("TeleDrive")` untuk semua data runtime:
- File `.session` Telethon
- `teledrive.db`

**Jangan** taruh DB atau session di folder project/aplikasi — setelah di-package PyInstaller, folder aplikasi bisa read-only.

## Keamanan
- File `.session` = akses penuh ke akun Telegram. Jangan pernah masuk backup bersama, cloud sync, atau repo.
- `.gitignore` sejak hari pertama: `.env`, `*.session`, `*.db`.

## Struktur Project
```
teledrive/
├── core/
│   ├── auth.py          # login, session mgmt
│   ├── uploader.py      # upload sekuensial + retry + dedup + limit 1,5GB
│   ├── downloader.py    # download + verifikasi sha256
│   ├── deleter.py       # hapus message di channel + update DB
│   ├── db.py            # SQLite (sqlite3 bawaan): schema, queries, tabel meta
│   ├── channel.py       # cek/buat channel privat (raw API)
│   └── hasher.py        # SHA-256 chunked
├── ui/
│   ├── main_window.py
│   ├── login_dialog.py
│   ├── file_list_widget.py
│   └── upload_progress.py
├── config/
│   └── settings.py      # load .env, resolve path via platformdirs
├── .env
├── .gitignore
└── main.py
```

## DB Schema (SQLite)
```sql
CREATE TABLE files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_name TEXT NOT NULL,
    local_path TEXT,
    size_bytes INTEGER,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    sha256 TEXT,
    mime_type TEXT,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'synced',  -- synced/uploading/failed/corrupt/deleted
    UNIQUE(channel_id, message_id)
);

CREATE INDEX idx_original_name ON files(original_name);
CREATE INDEX idx_sha256 ON files(sha256);

CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
-- meta menyimpan antara lain: storage_channel_id
```

## Modul Detail

### 1. `core/auth.py`
- `TelegramClient(session=<path dari platformdirs>, api_id, api_hash, flood_sleep_threshold=60)`
- `flood_sleep_threshold` bikin Telethon otomatis sleep untuk FloodWait pendek — mengurangi retry manual.
- Flow: `client.start(phone=...)` → OTP + 2FA password via dialog UI (bukan `input()` CLI).
- `api_id`/`api_hash` dari `.env`.

### 2. `core/channel.py`
- `get_or_create_storage_channel()`: scan dialog list untuk channel bernama `TeleDrive_Storage`.
- Kalau belum ada, buat via **raw API** (Telethon tidak punya `client.create_channel`):
  ```python
  from telethon.tl import functions
  result = await client(functions.channels.CreateChannelRequest(
      title="TeleDrive_Storage", about="TeleDrive private storage", megagroup=False
  ))
  channel = result.chats[0]
  ```
- Simpan `channel_id` di tabel `meta`.

### 3. `core/uploader.py`
```python
MAX_SIZE = int(1.5 * 1024**3)  # 1,5 GB — tolak di atas ini

async def upload_file(path, progress_callback):
    size = os.path.getsize(path)
    if size > MAX_SIZE:
        raise FileTooLargeError(path, size)  # UI tampilkan pesan, tidak masuk DB

    sha = compute_sha256(path)
    if existing := db.find_by_sha256(sha):
        return existing  # dedup: skip upload, referensikan record lama

    for attempt in range(3):
        try:
            msg = await client.send_file(
                channel_id, path,
                progress_callback=progress_callback,
                force_document=True  # preserve original, tanpa re-encode/kompresi
            )
            break
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds)
        except (ConnectionError, TimeoutError):
            if attempt == 2:
                raise
            await asyncio.sleep(2 ** attempt)

    save_to_db(name, path, size, channel_id, msg.id, sha)
    await asyncio.sleep(1.5)  # delay flat kecil antar file, bukan formula per-size
```
- Queue di UI memanggil ini satu per satu (sekuensial).

### 4. `core/downloader.py`
```python
async def download_file(message_id, dest_path, progress_callback):
    msg = await client.get_messages(channel_id, ids=message_id)
    await client.download_media(msg, file=dest_path, progress_callback=progress_callback)
    # verifikasi sha256 vs record DB; mismatch → status='corrupt' + peringatan di UI
```

### 5. `core/deleter.py`
- `delete_file(record)`: konfirmasi di UI → `client.delete_messages(channel_id, [message_id])` → set `status='deleted'` di DB (soft-delete di DB, hard-delete di Telegram).
- Row berstatus `deleted` disembunyikan dari list default (bisa ditampilkan via filter).

### 6. `core/hasher.py`
- `compute_sha256(path)` — chunked read (misal 1 MB per chunk), jangan load full file ke memory.
- Dipakai dua arah: dedup sebelum upload, verifikasi setelah download.

## UI Flow (PyQt6 + qasync)
1. `login_dialog.py` — input phone → OTP → 2FA password (kalau ada) → sukses → tutup dialog.
2. `main_window.py` — QTableView bind ke DB (nama, ukuran, tanggal, status), toolbar (Upload, Download, Delete, Search bar dengan `LIKE` query).
3. Upload: `QFileDialog` multi-select → validasi ukuran (tolak > 1,5 GB dengan pesan) → masuk queue sekuensial → progress bar per file. Semua via `asyncio.create_task`, **tanpa QThread**.
4. Download: pilih row → `QFileDialog.getExistingDirectory` → progress bar → verifikasi sha256.
5. Delete: pilih row → dialog konfirmasi → hapus.

## Fase Implementasi

| Fase | Deliverable Teknis |
|---|---|
| 1 | `auth.py` jalan standalone (CLI test dulu), `.env` loader, path via `platformdirs`, session tersimpan & reconnect tanpa OTP ulang |
| 2 | `uploader.py` + `downloader.py` + `channel.py` tested via script (belum UI): limit 1,5 GB, retry loop, FloodWait handling, sha256 verify, dedup |
| 3 | `db.py` schema final (termasuk `meta` + `channel_id` + UNIQUE constraint), migrasi hasil test Fase 2 ke DB, query search/list, `deleter.py` |
| 4 | Integrasi PyQt6 + qasync: hubungkan semua modul ke UI, queue upload sekuensial, progress bar, delete flow |
| 5 | Packaging PyInstaller (fase sendiri — biasanya butuh iterasi: hidden imports, data files, dll) |
| 6 | App Android: reuse `core/` (bebas Qt) + UI baru KivyMD, build APK via Buildozer |

## Fase 6 — TeleDrive Android

### Keputusan Arsitektur
- **Kivy + KivyMD + Telethon** via python-for-android/Buildozer — bukan
  rewrite Flutter/TDLib. Alasan: `core/` (auth, uploader, downloader,
  sync, db, hasher, channel, previewer, sharer, renamer) sudah bebas
  dari PyQt6, bisa dipakai ulang hampir utuh. Yang ditulis ulang hanya
  lapisan UI (PyQt6 → KivyMD, Material Design).
- Repo yang sama, folder `mobile/` untuk UI Android + `buildozer.spec`;
  `core/` dan `config/` di-share. Guard: `core/` DILARANG import Qt
  (tetap murni Python + Telethon).
- Satu akun bisa dipakai di desktop & Android sekaligus — session
  Telethon terpisah per device, DB dibangun via **Sinkronkan** (fitur
  recovery yang sudah ada; inilah kenapa sync dari channel penting).

### Sub-fase
| Sub | Deliverable |
|---|---|
| 6.1 | PoC headless: APK minimal (Buildozer di WSL2), Telethon connect + login OTP + list isi channel di Android |
| 6.2 | Core jalan penuh: db/sync/uploader/downloader dengan progress; session+DB di app-private storage (`android_storage`), bukan `platformdirs` |
| 6.3 | UI KivyMD: login, browser grid/list + thumbnail, search/filter, upload via SAF picker, download ke `Download/`, pratinjau gambar in-app (tipe lain via intent ke app eksternal) |
| 6.4 | Integrasi Android: foreground service untuk upload/auto-backup + notifikasi progress, share-sheet "Kirim ke TeleDrive", polish + APK release |

### Risiko & Mitigasi
- **Buildozer butuh Linux** → build via WSL2 di PC ini; CI GitHub Actions
  sebagai alternatif build ulang yang reproducible.
- **Background limits Android (Doze)** → semua transfer lewat foreground
  service dengan notifikasi; auto-backup dijalankan saat app dibuka +
  WorkManager-style periodic, bukan watcher terus-menerus.
- **FloodWait di jaringan seluler tidak stabil** → retry/backoff yang
  sudah ada di uploader dipertahankan; queue persist jadi makin penting.
- **Ukuran APK ±40–60 MB** (Python runtime + Kivy) → diterima untuk v1.
- **Jalan buntu p4a/Telethon** → fallback plan: rewrite Flutter + TDLib
  (effort jauh lebih besar, keputusan terpisah).

## Dependencies (`requirements.txt`)
```
telethon
PyQt6
qasync
python-dotenv
platformdirs
```
