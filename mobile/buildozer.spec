# Buildozer spec TeleDrive Android (PoC 6.1)
# Build butuh Linux: GitHub Actions (.github/workflows/android.yml)
# atau WSL2. Hasil: mobile/bin/*.apk

[app]
title = TeleDrive
package.name = teledrive
package.domain = com.s4rt4
version = 0.1

source.dir = .
source.include_exts = py

# Telethon murni Python; pyaes+rsa(+pyasn1) adalah dependensi crypto-nya
requirements = python3,kivy,telethon,rsa,pyaes,pyasn1

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
