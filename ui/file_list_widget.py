"""Browser file/folder dua mode: grid kartu ala GDrive dan list berkolom.

FileBrowser = QStackedWidget berisi QListWidget (grid) + QTreeWidget
(list: Nama/Ukuran/Diupload/Status). MainWindow hanya bicara lewat
facade: populate/count/entry/selected_entries/set_display_mode/
update_thumb dan tiga signal. Item menyimpan ("folder", FolderRecord)
atau ("file", FileRecord) di UserRole.

Icon file memakai thumbnail cache (core.thumbs) kalau ada, fallback ke
icon vektor per-mime.
"""
from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
)

from core.db import FileRecord, FolderRecord
from core.thumbs import thumb_path
from ui.icons import folder_icon, icon_for_mime

KIND_ROLE = Qt.ItemDataRole.UserRole

GRID_ICON = 96                 # thumbnail besar ala GDrive
GRID_CELL = QSize(128, 152)    # sel grid (rapat)
GRID_CARD = QSize(120, 144)    # kartu = sel minus margin QSS 4px

STATUS_LABEL = {
    "synced": "Tersinkron",
    "missing": "Hilang di Telegram",
    "corrupt": "Corrupt",
    "failed": "Gagal",
    "uploading": "Mengupload",
}


def human_size(n: int | None) -> str:
    if n is None:
        return "-"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def _file_icon(r: FileRecord, px: int) -> QIcon:
    tp = thumb_path(r.id)
    if tp.exists():
        return QIcon(str(tp))
    return icon_for_mime(r.mime_type, px)


def _tooltip(r: FileRecord) -> str:
    return (
        f"{r.original_name}\n{human_size(r.size_bytes)}"
        f"\nDiupload: {r.uploaded_at} UTC"
        f"\nStatus: {STATUS_LABEL.get(r.status, r.status)}"
    )


class FileBrowser(QStackedWidget):
    folder_opened = pyqtSignal(object)          # FolderRecord
    file_activated = pyqtSignal(object)         # FileRecord (double-click)
    context_requested = pyqtSignal(object, QPoint)  # (entry|None, pos global)

    def __init__(self) -> None:
        super().__init__()
        self._mode = "grid"

        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setIconSize(QSize(GRID_ICON, GRID_ICON))
        self.grid.setGridSize(GRID_CELL)
        self.grid.setWordWrap(True)
        self.grid.setSpacing(0)
        self.grid.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.itemDoubleClicked.connect(self._on_grid_double)
        self.grid.customContextMenuRequested.connect(self._on_grid_context)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Nama", "Ukuran", "Diupload", "Status"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setIconSize(QSize(22, 22))
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.itemDoubleClicked.connect(self._on_tree_double)
        self.tree.customContextMenuRequested.connect(self._on_tree_context)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )

        self.addWidget(self.grid)
        self.addWidget(self.tree)

    # ================= facade =================

    def set_display_mode(self, mode: str) -> None:
        """'grid' = kartu, 'list' = baris berkolom."""
        self._mode = mode
        self.setCurrentWidget(self.grid if mode == "grid" else self.tree)

    def display_mode(self) -> str:
        return self._mode

    def populate(self, folders: list[FolderRecord],
                 files: list[FileRecord]) -> None:
        if self._mode == "grid":
            self._populate_grid(folders, files)
        else:
            self._populate_tree(folders, files)

    def count(self) -> int:
        if self._mode == "grid":
            return self.grid.count()
        return self.tree.topLevelItemCount()

    def entry(self, i: int) -> tuple[str, object]:
        if self._mode == "grid":
            return self.grid.item(i).data(KIND_ROLE)
        return self.tree.topLevelItem(i).data(0, KIND_ROLE)

    def selected_entries(self) -> list[tuple[str, object]]:
        if self._mode == "grid":
            return [it.data(KIND_ROLE) for it in self.grid.selectedItems()]
        return [it.data(0, KIND_ROLE) for it in self.tree.selectedItems()]

    def update_thumb(self, file_id: int) -> None:
        """Dipanggil saat thumbnail selesai di-download — ganti icon item."""
        tp = thumb_path(file_id)
        if not tp.exists():
            return
        icon = QIcon(str(tp))
        for i in range(self.count()):
            kind, rec = self.entry(i)
            if kind == "file" and rec.id == file_id:
                if self._mode == "grid":
                    self.grid.item(i).setIcon(icon)
                else:
                    self.tree.topLevelItem(i).setIcon(0, icon)
                return

    # ================= isi view =================

    def _populate_grid(self, folders, files) -> None:
        self.grid.clear()
        align = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        for f in folders:
            item = QListWidgetItem(folder_icon(GRID_ICON), f.name)
            item.setData(KIND_ROLE, ("folder", f))
            item.setToolTip(f"Folder: {f.name}")
            item.setTextAlignment(align)
            # sizeHint di-fix selebar sel — tanpa ini kartu menyusut
            # mengikuti lebar teks dan jarak antar kartu jadi lebar
            item.setSizeHint(GRID_CARD)
            self.grid.addItem(item)
        for r in files:
            item = QListWidgetItem(_file_icon(r, GRID_ICON), r.original_name)
            item.setData(KIND_ROLE, ("file", r))
            item.setToolTip(_tooltip(r))
            item.setTextAlignment(align)
            item.setSizeHint(GRID_CARD)
            self.grid.addItem(item)

    def _populate_tree(self, folders, files) -> None:
        self.tree.clear()
        for f in folders:
            item = QTreeWidgetItem([f.name, "—", "", ""])
            item.setIcon(0, folder_icon(22))
            item.setData(0, KIND_ROLE, ("folder", f))
            self.tree.addTopLevelItem(item)
        for r in files:
            item = QTreeWidgetItem([
                r.original_name,
                human_size(r.size_bytes),
                (r.uploaded_at or "")[:16],
                STATUS_LABEL.get(r.status, r.status),
            ])
            item.setIcon(0, _file_icon(r, 22))
            item.setData(0, KIND_ROLE, ("file", r))
            item.setToolTip(0, _tooltip(r))
            self.tree.addTopLevelItem(item)

    # ================= event handler =================

    def _emit_activate(self, entry) -> None:
        kind, rec = entry
        if kind == "folder":
            self.folder_opened.emit(rec)
        else:
            self.file_activated.emit(rec)

    def _on_grid_double(self, item: QListWidgetItem) -> None:
        self._emit_activate(item.data(KIND_ROLE))

    def _on_tree_double(self, item: QTreeWidgetItem, _col: int) -> None:
        self._emit_activate(item.data(0, KIND_ROLE))

    def _on_grid_context(self, pos) -> None:
        item = self.grid.itemAt(pos)
        entry = item.data(KIND_ROLE) if item else None
        self.context_requested.emit(
            entry, self.grid.viewport().mapToGlobal(pos)
        )

    def _on_tree_context(self, pos) -> None:
        item = self.tree.itemAt(pos)
        entry = item.data(0, KIND_ROLE) if item else None
        self.context_requested.emit(
            entry, self.tree.viewport().mapToGlobal(pos)
        )
