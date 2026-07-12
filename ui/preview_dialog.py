"""Window pratinjau file: gambar, video/audio, PDF, markdown, teks, docx.

Non-modal (bisa buka beberapa sekaligus), pakai frame window standar
supaya gampang di-resize/maximize. Konten dirender dari file cache
(core/previewer.fetch). Tipe tak didukung / gagal render → tombol
"Buka dengan aplikasi lain".
"""
import os
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtPdfWidgets import QPdfView
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core import previewer
from core.db import FileRecord
from ui.file_list_widget import human_size
from ui.icons import pause_icon, play_icon
from ui.styles import icon_ink


def _fmt_ms(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


class _ImageView(QLabel):
    """Gambar fit-to-window, rescale saat resize."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self._pixmap = QPixmap(path)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(1, 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._pixmap.isNull():
            self.setPixmap(self._pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def failed(self) -> bool:
        return self._pixmap.isNull()


class PreviewWindow(QDialog):
    def __init__(self, parent, record: FileRecord, path, kind: str,
                 theme: str = "light", on_download=None) -> None:
        super().__init__(parent)
        self.setObjectName("PreviewWindow")
        self.setWindowFlags(Qt.WindowType.Window)  # frame standar, resizable
        self.setWindowTitle(record.original_name)
        self.resize(920, 640)
        self._record = record
        self._path = str(path)
        self._player: QMediaPlayer | None = None
        self._ink = icon_ink(theme)

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(8)

        head = QHBoxLayout()
        name = QLabel(record.original_name)
        name.setObjectName("TransferTitle")
        head.addWidget(name)
        size_lbl = QLabel(human_size(record.size_bytes))
        size_lbl.setObjectName("SectionLabel")
        head.addWidget(size_lbl)
        head.addStretch()
        if on_download is not None:
            btn_dl = QPushButton("Simpan ke...")
            btn_dl.setObjectName("GhostButton")
            btn_dl.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_dl.clicked.connect(on_download)
            head.addWidget(btn_dl)
        btn_ext = QPushButton("Buka dengan aplikasi lain")
        btn_ext.setObjectName("GhostButton")
        btn_ext.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ext.clicked.connect(self._open_external)
        head.addWidget(btn_ext)
        v.addLayout(head)

        content = self._build_content(kind)
        v.addWidget(content, stretch=1)

    # ---- konten per jenis ----

    def _build_content(self, kind: str) -> QWidget:
        try:
            if kind == "image":
                view = _ImageView(self._path)
                if view.failed():
                    return self._fallback("Format gambar tidak dikenali")
                return view
            if kind == "media":
                return self._build_media()
            if kind == "pdf":
                return self._build_pdf()
            if kind == "markdown":
                edit = self._text_edit()
                edit.setMarkdown(previewer.read_text(Path(self._path)))
                return edit
            if kind == "text":
                edit = self._text_edit()
                edit.setPlainText(previewer.read_text(Path(self._path)))
                return edit
            if kind == "docx":
                edit = self._text_edit()
                text = previewer.read_docx_text(Path(self._path))
                edit.setPlainText(text or "(dokumen kosong)")
                return edit
        except Exception as e:
            return self._fallback(f"Gagal merender pratinjau: {e}")
        return self._fallback("Jenis file ini belum didukung pratinjau")

    @staticmethod
    def _text_edit() -> QTextEdit:
        edit = QTextEdit()
        edit.setObjectName("PreviewText")
        edit.setReadOnly(True)
        return edit

    def _fallback(self, reason: str) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.addStretch()
        lbl = QLabel(f"{reason}.\nGunakan \"Buka dengan aplikasi lain\".")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setObjectName("SectionLabel")
        lay.addWidget(lbl)
        lay.addStretch()
        return box

    def _build_pdf(self) -> QWidget:
        doc = QPdfDocument(self)
        doc.load(self._path)
        if doc.status() == QPdfDocument.Status.Error:
            return self._fallback("PDF tidak bisa dibuka")
        view = QPdfView(self)
        view.setDocument(doc)
        view.setPageMode(QPdfView.PageMode.MultiPage)
        view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        return view

    def _build_media(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        video = QVideoWidget()
        lay.addWidget(video, stretch=1)

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(video)

        controls = QHBoxLayout()
        self._btn_play = QPushButton()
        self._btn_play.setObjectName("GhostButton")
        self._btn_play.setIcon(pause_icon(32, self._ink))
        self._btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_play.clicked.connect(self._toggle_play)
        controls.addWidget(self._btn_play)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.sliderMoved.connect(self._player.setPosition)
        controls.addWidget(self._slider, stretch=1)

        self._time = QLabel("0:00 / 0:00")
        self._time.setObjectName("SectionLabel")
        controls.addWidget(self._time)
        lay.addLayout(controls)

        self._player.durationChanged.connect(
            lambda d: self._slider.setRange(0, d)
        )
        self._player.positionChanged.connect(self._on_position)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.setSource(QUrl.fromLocalFile(self._path))
        self._player.play()
        return box

    def _on_position(self, pos: int) -> None:
        if not self._slider.isSliderDown():
            self._slider.setValue(pos)
        dur = self._player.duration() if self._player else 0
        self._time.setText(f"{_fmt_ms(pos)} / {_fmt_ms(dur)}")

    def _on_state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        icon = pause_icon if playing else play_icon
        self._btn_play.setIcon(icon(32, self._ink))

    def _toggle_play(self) -> None:
        if self._player is None:
            return
        if (self._player.playbackState()
                == QMediaPlayer.PlaybackState.PlayingState):
            self._player.pause()
        else:
            self._player.play()

    def _open_external(self) -> None:
        os.startfile(self._path)

    def closeEvent(self, event) -> None:
        if self._player is not None:
            self._player.stop()
        super().closeEvent(event)
