# Buildozer spec TeleDrive Android (Fase 6.2 — reuse core/)
# Build butuh Linux: GitHub Actions (.github/workflows/android.yml)
# atau WSL2. Hasil: mobile/bin/*.apk
# core/ + config/ + data/icon.png disiapkan CI ke folder ini (gitignored).

[app]
title = TeleDrive
package.name = teledrive
package.domain = com.s4rt4
version = 0.2

source.dir = .
source.include_exts = py

# Icon & presplash di-generate CI dari teledrive.svg (rsvg-convert)
icon.filename = %(source.dir)s/data/icon.png
presplash.filename = %(source.dir)s/data/icon.png

# Telethon murni Python; pyaes+rsa(+pyasn1) adalah dependensi crypto-nya.
# sqlite3 = recipe p4a agar modul sqlite3 Python tersedia (dipakai core.db)
requirements = python3,kivy,telethon,rsa,pyaes,pyasn1,sqlite3

orientation = portrait
fullscreen = 0

android.permissions = INTERNET
android.api = 34
android.minapi = 24
# Satu arch dulu — build lebih cepat; tambah armeabi-v7a saat rilis
android.archs = arm64-v8a
# File .session = akses penuh akun Telegram; jangan ikut backup Android
android.allow_backup = False

[buildozer]
log_level = 2
warn_on_root = 1
