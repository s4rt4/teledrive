"""Ikon vektor custom, digambar runtime dengan QPainter.

Tanpa emoji dan tanpa file asset — semua bentuk digambar ke QPixmap
transparan lalu di-cache. Koordinat memakai kanvas acuan 48x48 yang
diskala ke ukuran piksel yang diminta.
"""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

# Palet ala Google Drive
BLUE = "#0b57d0"
RED = "#ea4335"
AMBER = "#f9ab00"
GRAY = "#5f6368"
INK = "#444746"

_cache: dict[tuple, QIcon] = {}


def _begin(px: int) -> tuple[QPixmap, QPainter, float]:
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pm, p, px / 48

def _icon(key: tuple, px: int, draw) -> QIcon:
    if (key, px) not in _cache:
        pm, p, s = _begin(px)
        draw(p, s)
        p.end()
        _cache[(key, px)] = QIcon(pm)
    return _cache[(key, px)]


def _stroke_pen(color: str, s: float, width: float = 4.0) -> QPen:
    pen = QPen(QColor(color), width * s)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


# ================= ikon UI (stroke) =================

def plus_icon(px: int = 20, color: str = INK) -> QIcon:
    def draw(p, s):
        p.setPen(_stroke_pen(color, s, 4.5))
        p.drawLine(QPointF(24 * s, 10 * s), QPointF(24 * s, 38 * s))
        p.drawLine(QPointF(10 * s, 24 * s), QPointF(38 * s, 24 * s))
    return _icon(("plus", color), px, draw)


def search_icon(px: int = 20, color: str = INK) -> QIcon:
    def draw(p, s):
        p.setPen(_stroke_pen(color, s, 4.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(8 * s, 8 * s, 24 * s, 24 * s))
        p.drawLine(QPointF(30 * s, 30 * s), QPointF(40 * s, 40 * s))
    return _icon(("search", color), px, draw)


def list_icon(px: int = 18, color: str = INK) -> QIcon:
    def draw(p, s):
        p.setPen(_stroke_pen(color, s, 4.5))
        for y in (12, 24, 36):
            p.drawLine(QPointF(9 * s, y * s), QPointF(39 * s, y * s))
    return _icon(("list", color), px, draw)


def grid_icon(px: int = 18, color: str = INK) -> QIcon:
    def draw(p, s):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        for x, y in ((9, 9), (27, 9), (9, 27), (27, 27)):
            p.drawRoundedRect(QRectF(x * s, y * s, 12 * s, 12 * s), 3 * s, 3 * s)
    return _icon(("grid", color), px, draw)


def caret_icon(px: int = 16, color: str = INK) -> QIcon:
    """Chevron ke bawah untuk chip dropdown."""
    def draw(p, s):
        p.setPen(_stroke_pen(color, s, 4.5))
        p.drawLine(QPointF(12 * s, 19 * s), QPointF(24 * s, 31 * s))
        p.drawLine(QPointF(24 * s, 31 * s), QPointF(36 * s, 19 * s))
    return _icon(("caret", color), px, draw)


def sync_icon(px: int = 20, color: str = INK) -> QIcon:
    """Panah melingkar (refresh/sync)."""
    def draw(p, s):
        p.setPen(_stroke_pen(color, s, 4.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        rect = QRectF(10 * s, 10 * s, 28 * s, 28 * s)
        path.arcMoveTo(rect, 60)
        path.arcTo(rect, 60, 300)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawPolygon(QPolygonF([
            QPointF(29 * s, 3 * s),
            QPointF(41 * s, 11 * s),
            QPointF(29 * s, 18 * s),
        ]))
    return _icon(("sync", color), px, draw)


def play_icon(px: int = 20, color: str = INK) -> QIcon:
    def draw(p, s):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawPolygon(QPolygonF([
            QPointF(15 * s, 10 * s), QPointF(38 * s, 24 * s),
            QPointF(15 * s, 38 * s),
        ]))
    return _icon(("play", color), px, draw)


def pause_icon(px: int = 20, color: str = INK) -> QIcon:
    def draw(p, s):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(13 * s, 10 * s, 8 * s, 28 * s), 2 * s, 2 * s)
        p.drawRoundedRect(QRectF(27 * s, 10 * s, 8 * s, 28 * s), 2 * s, 2 * s)
    return _icon(("pause", color), px, draw)


def gear_icon(px: int = 20, color: str = INK) -> QIcon:
    """Roda gigi sederhana: lingkaran + 8 gigi."""
    def draw(p, s):
        p.setPen(_stroke_pen(color, s, 4.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(15 * s, 15 * s, 18 * s, 18 * s))
        import math
        for i in range(8):
            a = math.radians(i * 45)
            x1 = 24 + 11.5 * math.cos(a)
            y1 = 24 + 11.5 * math.sin(a)
            x2 = 24 + 17 * math.cos(a)
            y2 = 24 + 17 * math.sin(a)
            p.drawLine(QPointF(x1 * s, y1 * s), QPointF(x2 * s, y2 * s))
    return _icon(("gear", color), px, draw)


def cloud_icon(px: int = 26, color: str = BLUE) -> QIcon:
    def draw(p, s):
        path = QPainterPath()
        path.addEllipse(QRectF(11 * s, 14 * s, 22 * s, 22 * s))
        path.addEllipse(QRectF(24 * s, 18 * s, 17 * s, 17 * s))
        path.addEllipse(QRectF(5 * s, 22 * s, 15 * s, 15 * s))
        path.addRoundedRect(QRectF(10 * s, 27 * s, 28 * s, 10 * s), 5 * s, 5 * s)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawPath(path.simplified())
    return _icon(("cloud", color), px, draw)


def drive_icon(px: int = 20, color: str = "#001d35") -> QIcon:
    """Hard drive: kotak rounded + dua lampu indikator."""
    def draw(p, s):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(6 * s, 15 * s, 36 * s, 18 * s), 6 * s, 6 * s)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(31 * s, 22 * s, 4 * s, 4 * s))
        p.drawEllipse(QRectF(24 * s, 22 * s, 4 * s, 4 * s))
    return _icon(("drive", color), px, draw)


# ================= folder & file =================

def folder_icon(px: int = 48, color: str = GRAY) -> QIcon:
    def draw(p, s):
        body = QPainterPath()
        body.addRoundedRect(QRectF(4 * s, 12 * s, 40 * s, 28 * s), 4 * s, 4 * s)
        tab = QPainterPath()
        tab.addRoundedRect(QRectF(4 * s, 7 * s, 18 * s, 12 * s), 4 * s, 4 * s)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawPath(body.united(tab).simplified())
    return _icon(("folder", color), px, draw)


def _draw_page(p, s: float, color: str) -> None:
    """Halaman dokumen rounded + sudut terlipat (dog-ear) di kanan atas."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(7 * s, 5 * s, 34 * s, 38 * s), 5 * s, 5 * s)
    ear = QPolygonF([
        QPointF(31 * s, 5 * s),
        QPointF(41 * s, 15 * s),
        QPointF(31 * s, 15 * s),
    ])
    p.setBrush(QColor(255, 255, 255, 90))
    p.drawPolygon(ear)


def _glyph_lines(p, s: float) -> None:
    p.setBrush(QColor("#ffffff"))
    for y in (22, 28, 34):
        p.drawRoundedRect(QRectF(14 * s, y * s, 20 * s, 3 * s), 1.5 * s, 1.5 * s)


def _file_icon(kind: str, color: str, glyph, px: int) -> QIcon:
    def draw(p, s):
        _draw_page(p, s, color)
        glyph(p, s)
    return _icon(("file", kind), px, draw)


def file_kind(mime: str | None) -> str:
    """Kategori file dari mime: image/video/audio/pdf/archive/doc.
    Dipakai bersama oleh ikon dan filter 'Jenis'."""
    m = (mime or "").lower()
    if m.startswith("image/"):
        return "image"
    if m.startswith("video/"):
        return "video"
    if m.startswith("audio/"):
        return "audio"
    if "pdf" in m:
        return "pdf"
    if any(x in m for x in ("zip", "rar", "7z", "tar", "compressed")):
        return "archive"
    return "doc"


def icon_for_mime(mime: str | None, px: int = 48) -> QIcon:
    kind = file_kind(mime)

    if kind == "image":
        def draw(p, s):  # foto landscape: matahari + gunung
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(RED))
            p.drawRoundedRect(QRectF(5 * s, 10 * s, 38 * s, 28 * s), 5 * s, 5 * s)
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QRectF(12 * s, 15 * s, 6 * s, 6 * s))
            p.drawPolygon(QPolygonF([
                QPointF(9 * s, 34 * s), QPointF(19 * s, 22 * s),
                QPointF(25 * s, 29 * s), QPointF(30 * s, 24 * s),
                QPointF(39 * s, 34 * s),
            ]))
        return _icon(("file", "image"), px, draw)

    if kind == "video":
        def glyph(p, s):  # tombol play
            p.setBrush(QColor("#ffffff"))
            p.drawPolygon(QPolygonF([
                QPointF(19 * s, 17 * s), QPointF(33 * s, 26 * s),
                QPointF(19 * s, 35 * s),
            ]))
        return _file_icon("video", RED, glyph, px)

    if kind == "audio":
        def glyph(p, s):  # not balok
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QRectF(16 * s, 30 * s, 8 * s, 6 * s))
            p.drawRoundedRect(QRectF(22 * s, 14 * s, 2.6 * s, 20 * s), s, s)
            p.drawRoundedRect(QRectF(22 * s, 14 * s, 10 * s, 3 * s), s, s)
        return _file_icon("audio", AMBER, glyph, px)

    if kind == "pdf":
        def glyph(p, s):  # garis teks + bar tebal ala header PDF
            p.setBrush(QColor("#ffffff"))
            p.drawRoundedRect(QRectF(16 * s, 20 * s, 16 * s, 5 * s), 2 * s, 2 * s)
            for y in (29, 35):
                p.drawRoundedRect(QRectF(16 * s, y * s, 16 * s, 3 * s),
                                  1.5 * s, 1.5 * s)
        return _file_icon("pdf", RED, glyph, px)

    if kind == "archive":
        def glyph(p, s):  # ritsleting
            p.setBrush(QColor("#ffffff"))
            for y in (8, 15, 22):
                p.drawRoundedRect(QRectF(22.5 * s, y * s, 3 * s, 4.5 * s), s, s)
            p.setPen(_stroke_pen("#ffffff", s, 2.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(20 * s, 30 * s, 8 * s, 8 * s), 2 * s, 2 * s)
        return _file_icon("archive", GRAY, glyph, px)

    return _file_icon("doc", BLUE, _glyph_lines, px)
