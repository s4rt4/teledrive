# Buildozer spec TeleDrive Android (Fase 6.3 — UI KivyMD penuh)
# Build butuh Linux: GitHub Actions (.github/workflows/android.yml)
# atau WSL2. Hasil: mobile/bin/*.apk
# core/ + config/ + data/icon*.png disiapkan CI ke folder ini (gitignored).

[app]
title = TeleDrive
package.name = teledrive
package.domain = com.s4rt4
# Versi dibaca dari appmeta.py (sumber tunggal — dialog "Tentang" di app
# memakai konstanta yang sama, jadi tak pernah melenceng dari APK).
# `version =` HARUS tetap dikomentari agar version.regex dipakai.
# version = 0.6
version.regex = __version__ = ['"]([^'"]*)['"]
version.filename = %(source.dir)s/appmeta.py

source.dir = .
source.include_exts = py

# Icon di-generate CI dari teledrive.svg. Adaptive icon (API 26+):
# foreground diberi margin safe-zone supaya TIDAK terpotong saat launcher
# memotong jadi lingkaran; background warna gelap senada app.
icon.filename = %(source.dir)s/data/icon.png
icon.adaptive_foreground.filename = %(source.dir)s/data/icon_fg.png
icon.adaptive_background.filename = %(source.dir)s/data/icon_bg.png
presplash.filename = %(source.dir)s/data/icon_fg.png
android.presplash_color = #101720

# Telethon murni Python; pyaes+rsa(+pyasn1) adalah dependensi crypto-nya.
# sqlite3 = recipe p4a agar modul sqlite3 Python tersedia (dipakai core.db).
# kivymd dipin 1.2.0 (API 2.x beda total); pillow dibutuhkan kivymd.
requirements = python3,kivy,kivymd==1.2.0,pillow,telethon,rsa,pyaes,pyasn1,sqlite3

orientation = portrait
fullscreen = 0

# WRITE/READ_EXTERNAL_STORAGE hanya dipakai runtime di API 24-28
# (download ke folder publik); API 29+ lewat MediaStore tanpa permission
android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
android.api = 34
android.minapi = 24
# build release menghasilkan APK (default buildozer baru = AAB)
android.release_artifact = apk
# Satu arch dulu — build lebih cepat; tambah armeabi-v7a saat rilis
android.archs = arm64-v8a
# File .session = akses penuh akun Telegram; jangan ikut backup Android
android.allow_backup = False

[buildozer]
log_level = 2
warn_on_root = 1
