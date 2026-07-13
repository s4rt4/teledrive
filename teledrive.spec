# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec TeleDrive (mode onedir).

Build:  pyinstaller teledrive.spec --noconfirm
Hasil:  dist/TeleDrive/TeleDrive.exe

Catatan:
- teledrive.svg ikut sebagai data — dipakai setWindowIcon (PROJECT_ROOT
  di settings.py menunjuk sys._MEIPASS saat frozen).
- PyQt6.QtSvg wajib di hiddenimports: QIcon(*.svg) butuh plugin
  iconengines/qsvgicon yang hanya di-bundle kalau modul ini terdeteksi.
- QtPdf/QtMultimedia ter-import eksplisit di ui/preview_dialog.py,
  hook PyQt6 menangani plugin & DLL-nya otomatis.
"""

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('teledrive.svg', '.')],
    hiddenimports=['PyQt6.QtSvg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TeleDrive',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon='teledrive.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='TeleDrive',
)
