"""Pratinjau file tanpa flow download manual.

File ditarik dari Telegram ke PREVIEW_DIR (sekali — buka berikutnya
instan dari cache), lalu dirender in-app oleh ui/preview_dialog.
Cache dipangkas dari yang paling lama diakses saat melebihi
PREVIEW_CACHE_MAX.

Ekstraksi teks .docx dilakukan manual (zipfile + ElementTree, docx =
zip berisi XML) supaya tidak menambah dependency.
"""
import os
import re
import zipfile
from pathlib import Path
from typing import Callable, Optional
from xml.etree import ElementTree

from telethon import TelegramClient

from config import settings
from core import downloader
from core.db import FileRecord

TEXT_EXTS = {
    ".txt", ".log", ".csv", ".json", ".xml", ".ini", ".yaml", ".yml",
    ".py", ".js", ".ts", ".php", ".html", ".css", ".sql", ".sh", ".bat",
}
DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
MAX_TEXT_PREVIEW = 2 * 1024**2  # teks di atas 2 MB dipotong


def kind_for(record: FileRecord) -> Optional[str]:
    """'image'/'media'/'pdf'/'markdown'/'text'/'docx', None = tak didukung."""
    mime = (record.mime_type or "").lower()
    ext = os.path.splitext(record.original_name)[1].lower()
    if mime.startswith("image/") and "svg" not in mime:
        return "image"
    if mime.startswith(("video/", "audio/")):
        return "media"
    if "pdf" in mime or ext == ".pdf":
        return "pdf"
    if ext in (".md", ".markdown"):
        return "markdown"
    if mime.startswith("text/") or ext in TEXT_EXTS:
        return "text"
    if mime == DOCX_MIME or ext == ".docx":
        return "docx"
    return None


def cache_path(record: FileRecord) -> Path:
    safe = re.sub(r'[\\/:*?"<>|]', "_", record.original_name)
    return settings.PREVIEW_DIR / f"{record.id}_{safe}"


def is_cached(record: FileRecord) -> bool:
    p = cache_path(record)
    if not p.exists():
        return False
    if record.size_bytes is not None and p.stat().st_size != record.size_bytes:
        return False  # kemungkinan sisa download terputus
    return True


async def fetch(
    client: TelegramClient,
    channel,
    record: FileRecord,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Path:
    dest = cache_path(record)
    if is_cached(record):
        os.utime(dest)  # sentuh mtime — dipakai urutan pemangkasan cache
        return dest
    await downloader.download_file(
        client, channel, record.message_id, dest,
        progress_callback=progress_callback,
        expected_sha256=record.sha256,
    )
    return dest


def prune_cache(max_bytes: int | None = None) -> None:
    max_bytes = max_bytes or settings.PREVIEW_CACHE_MAX
    files = [p for p in settings.PREVIEW_DIR.iterdir() if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    if total <= max_bytes:
        return
    for p in sorted(files, key=lambda p: p.stat().st_mtime):
        try:
            total -= p.stat().st_size
            p.unlink()
        except OSError:
            continue
        if total <= max_bytes:
            break


def read_text(path: Path) -> str:
    data = path.read_bytes()[:MAX_TEXT_PREVIEW]
    text = data.decode("utf-8", errors="replace")
    if path.stat().st_size > MAX_TEXT_PREVIEW:
        text += "\n\n[... dipotong — file terlalu besar untuk pratinjau]"
    return text


def read_docx_text(path: Path) -> str:
    """Ekstrak teks polos dari .docx (formatting dibuang)."""
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as e:
        raise ValueError(f"Bukan file docx yang valid: {e}")
    root = ElementTree.fromstring(xml)
    paragraphs = []
    for p in root.iter(f"{ns}p"):
        parts = []
        for node in p.iter():
            if node.tag == f"{ns}t" and node.text:
                parts.append(node.text)
            elif node.tag in (f"{ns}tab",):
                parts.append("\t")
            elif node.tag in (f"{ns}br",):
                parts.append("\n")
        paragraphs.append("".join(parts))
    return "\n".join(paragraphs)
