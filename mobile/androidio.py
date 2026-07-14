"""Integrasi Android via pyjnius: SAF picker, MediaStore Downloads, intent.

Semua fungsi aman dipanggil di desktop (no-op / return kosong) —
deteksi lewat kivy.utils.platform. autoclass dilakukan lazy di dalam
fungsi: kelas API 29+ (MediaStore$Downloads) tidak boleh di-resolve
saat import di device lama.

Transfer isi file dari/ke content:// memakai trik fd: openFileDescriptor
→ os.dup(getFd) → os.fdopen — cepat dan bebas masalah byte[] pyjnius.
"""
import os
import shutil
import threading
from pathlib import Path

from kivy.clock import Clock
from kivy.utils import platform

ANDROID = platform == "android"

REQUEST_PICK = 4271
_CLS = {}


def _cls(name):
    from jnius import autoclass

    if name not in _CLS:
        _CLS[name] = autoclass(name)
    return _CLS[name]


def _activity():
    from android import mActivity

    return mActivity


def _resolver():
    return _activity().getContentResolver()


def _sdk_int() -> int:
    return _cls("android.os.Build$VERSION").SDK_INT


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(1, 1000):
        cand = path.with_name(f"{stem} ({i}){suffix}")
        if not cand.exists():
            return cand
    return path


def _fd_open(uri, mode: str):
    """File object Python untuk content uri ('r' atau 'w')."""
    pfd = _resolver().openFileDescriptor(uri, mode)
    fd = os.dup(pfd.getFd())
    pfd.close()  # dup tetap valid setelah pfd ditutup
    return os.fdopen(fd, "rb" if mode == "r" else "wb")


def _display_name(uri) -> str:
    OpenableColumns = _cls("android.provider.OpenableColumns")
    cursor = _resolver().query(uri, None, None, None, None)
    try:
        if cursor is not None and cursor.moveToFirst():
            idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if idx >= 0 and cursor.getString(idx):
                return cursor.getString(idx)
    finally:
        if cursor is not None:
            cursor.close()
    return "file"


def pick_files(dest_dir: Path, on_done) -> None:
    """SAF picker multi-select. File terpilih DISALIN ke dest_dir
    (content:// tidak bisa dibaca uploader), lalu on_done(list[Path])
    dipanggil di thread UI. Salin jalan di thread terpisah — file besar
    tidak boleh memblokir UI."""
    if not ANDROID:
        on_done([])
        return
    from android import activity

    dest_dir.mkdir(parents=True, exist_ok=True)
    Intent = _cls("android.content.Intent")

    def on_result(request_code, result_code, intent):
        if request_code != REQUEST_PICK:
            return
        activity.unbind(on_activity_result=on_result)
        if result_code != -1 or intent is None:  # RESULT_OK = -1
            Clock.schedule_once(lambda *_: on_done([]))
            return
        uris = []
        clip = intent.getClipData()
        if clip is not None:
            for i in range(clip.getItemCount()):
                uris.append(clip.getItemAt(i).getUri())
        elif intent.getData() is not None:
            uris.append(intent.getData())

        def work():
            paths = []
            try:
                for uri in uris:
                    dest = _unique(dest_dir / _display_name(uri))
                    try:
                        with _fd_open(uri, "r") as src, open(dest, "wb") as out:
                            shutil.copyfileobj(src, out, 256 * 1024)
                        paths.append(dest)
                    except Exception:
                        dest.unlink(missing_ok=True)
            finally:
                try:
                    from jnius import detach

                    detach()
                except Exception:
                    pass
            Clock.schedule_once(lambda *_: on_done(paths))

        threading.Thread(target=work, daemon=True).start()

    activity.bind(on_activity_result=on_result)
    intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
    intent.addCategory(Intent.CATEGORY_OPENABLE)
    intent.setType("*/*")
    intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, True)
    _activity().startActivityForResult(intent, REQUEST_PICK)


def save_to_downloads(src: Path, name: str, mime: str | None):
    """Salin file privat ke Download/TeleDrive publik.

    Return (label_lokasi, uri) — uri untuk intent VIEW (None kalau tak
    tersedia). Di desktop return (None, None). Exception dilempar ke
    caller (toast di UI).
    """
    if not ANDROID:
        return None, None
    mime = mime or "application/octet-stream"

    if _sdk_int() >= 29:  # MediaStore.Downloads baru ada di API 29
        MediaColumns = _cls("android.provider.MediaStore$MediaColumns")
        Downloads = _cls("android.provider.MediaStore$Downloads")
        ContentValues = _cls("android.content.ContentValues")
        values = ContentValues()
        values.put(MediaColumns.DISPLAY_NAME, name)
        values.put(MediaColumns.MIME_TYPE, mime)
        values.put(MediaColumns.RELATIVE_PATH, "Download/TeleDrive")
        uri = _resolver().insert(Downloads.EXTERNAL_CONTENT_URI, values)
        if uri is None:
            raise OSError("MediaStore menolak insert")
        with open(src, "rb") as s, _fd_open(uri, "w") as out:
            shutil.copyfileobj(s, out, 256 * 1024)
        return f"Download/TeleDrive/{name}", uri

    # API 24-28: tulis langsung (butuh WRITE_EXTERNAL_STORAGE runtime)
    from android.permissions import Permission, request_permissions

    request_permissions(
        [Permission.WRITE_EXTERNAL_STORAGE, Permission.READ_EXTERNAL_STORAGE]
    )
    Environment = _cls("android.os.Environment")
    base = Environment.getExternalStoragePublicDirectory(
        Environment.DIRECTORY_DOWNLOADS
    ).getAbsolutePath()
    ddir = Path(base) / "TeleDrive"
    ddir.mkdir(parents=True, exist_ok=True)
    dest = _unique(ddir / name)
    shutil.copy2(src, dest)
    return str(dest), None  # file:// dilarang untuk intent sejak API 24


def view_uri(uri, mime: str | None) -> bool:
    """Buka content uri dengan app eksternal (ACTION_VIEW)."""
    if not ANDROID or uri is None:
        return False
    Intent = _cls("android.content.Intent")
    intent = Intent(Intent.ACTION_VIEW)
    if mime:
        intent.setDataAndType(uri, mime)
    else:
        intent.setData(uri)
    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    try:
        _activity().startActivity(intent)
        return True
    except Exception:
        return False
