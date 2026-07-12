"""Panel transfer ala GDrive (pojok kanan bawah): baris per file.

Tiap file dapat baris sendiri — nama, persentase, dan progress bar
individual; status akhir per baris (Selesai/Gagal/Dedup). Baris lama
yang sudah selesai dipangkas otomatis supaya kartu tidak memanjang
tanpa batas.

Progress callback Telethon dipanggil di event loop yang sama dengan Qt
(qasync), jadi aman langsung update widget.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

SCALE = 1000  # permille, aman untuk file besar
NAME_WIDTH = 200  # px, nama file di-elide ke lebar ini


class TransferRow(QWidget):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.finished = False

        self._name = QLabel()
        self._name.setObjectName("TransferRowName")
        metrics = QFontMetrics(self._name.font())
        self._name.setText(
            metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, NAME_WIDTH)
        )
        self._name.setToolTip(name)

        self._status = QLabel("Menunggu")
        self._status.setObjectName("TransferRowStatus")

        self._bar = QProgressBar()
        self._bar.setRange(0, SCALE)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self._name)
        top.addStretch()
        top.addWidget(self._status)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(4)
        v.addLayout(top)
        v.addWidget(self._bar)

    def start(self) -> None:
        self._status.setText("0%")

    def set_progress(self, current: int, total: int) -> None:
        if total:
            self._bar.setValue(current * SCALE // total)
            self._status.setText(f"{current * 100 // total}%")

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def set_indeterminate(self) -> None:
        self._bar.setRange(0, 0)

    def finish(self, text: str, ok: bool = True) -> None:
        self.finished = True
        self._bar.setRange(0, SCALE)
        self._bar.setValue(SCALE if ok else 0)
        self._status.setText(text)
        self._status.setProperty("error", "false" if ok else "true")
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)


class TransferCard(QWidget):
    cancel_clicked = pyqtSignal()
    MAX_ROWS = 6  # baris selesai terlama dipangkas melebihi ini

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("TransferCard")
        self._rows: list[TransferRow] = []

        self._title = QLabel()
        self._title.setObjectName("TransferTitle")
        self._cancel = QPushButton("Batal")
        self._cancel.setObjectName("CancelButton")
        self._cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel.clicked.connect(self.cancel_clicked.emit)

        top = QHBoxLayout()
        top.addWidget(self._title)
        top.addStretch()
        top.addWidget(self._cancel)

        self._rows_box = QVBoxLayout()
        self._rows_box.setContentsMargins(0, 0, 0, 0)
        self._rows_box.setSpacing(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(4)
        layout.addLayout(top)
        layout.addLayout(self._rows_box)
        self.setFixedWidth(340)
        self.hide()

    # ---- lifecycle batch ----

    def relayout(self) -> None:
        """Hitung ulang layout SEBELUM adjustSize — tanpa activate(),
        sizeHint masih basi sesaat setelah addWidget dan kartu menyusut
        (isi terjepit, tombol/label kepotong)."""
        if self.layout() is not None:
            self.layout().activate()
        self.adjustSize()

    def begin_batch(self, title: str) -> None:
        self._clear_rows()
        self._title.setText(title)
        self.show()
        self.raise_()
        self.relayout()

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def add_item(self, name: str) -> TransferRow:
        # pangkas baris selesai terlama supaya kartu tidak memanjang terus
        while len(self._rows) >= self.MAX_ROWS:
            done = next((r for r in self._rows if r.finished), None)
            if done is None:
                break
            self._rows.remove(done)
            self._rows_box.removeWidget(done)
            done.setParent(None)
            done.deleteLater()
        row = TransferRow(name)
        self._rows.append(row)
        self._rows_box.addWidget(row)
        # tanpa show() eksplisit, row berstatus hidden sampai event loop
        # berikutnya — layout mengabaikannya dan tinggi kartu salah hitung
        row.show()
        self.relayout()
        self.raise_()
        return row

    def end(self) -> None:
        self.hide()
        self._clear_rows()

    def _clear_rows(self) -> None:
        for row in self._rows:
            self._rows_box.removeWidget(row)
            row.setParent(None)  # deleteLater saja masih dihitung layout
            row.deleteLater()
        self._rows.clear()
        self.relayout()
