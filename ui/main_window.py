"""Jendela utama ala Google Drive.

Layout: sidebar kiri (Baru, nav, Sinkronkan, pemakaian storage) |
kanan: search bar pill + konten putih rounded berisi breadcrumb, chip
filter/sort, toggle grid-list, dan browser file. Kartu progress
transfer melayang di pojok kanan bawah dengan tombol Batal.

Folder bersifat virtual (hanya di DB) — channel Telegram tetap flat.
Semua operasi Telethon via asyncio.create_task di loop qasync, tanpa
QThread. Transfer sekuensial: satu file pada satu waktu.

Queue upload persist di DB (tabel upload_queue) — antrian yang belum
selesai ditawarkan untuk dilanjutkan saat aplikasi dibuka lagi.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

from PyQt6.QtCore import QFileSystemWatcher, QPoint, QSize, Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from config import settings
from core import (
    captions,
    downloader,
    previewer,
    renamer,
    sharer,
    sync,
    thumbs,
    uploader,
)
from core.db import Database, FileRecord, FolderRecord
from core.thumbs import thumb_path
from ui.dialogs import NewFolderDialog, TextInputDialog
from ui.file_list_widget import FileBrowser, human_size
from ui.icons import (
    caret_icon,
    drive_icon,
    file_kind,
    gear_icon,
    grid_icon,
    list_icon,
    plus_icon,
    search_icon,
    sync_icon,
)
from ui.preview_dialog import PreviewWindow
from ui.settings_dialog import SettingsDialog
from ui.styles import build_qss, icon_ink, polish_menu
from ui.upload_progress import TransferCard

LOGO_PATH = str(settings.PROJECT_ROOT / "teledrive.svg")

META_THEME = "theme"
META_BACKUP_PATH = "autobackup_path"
META_BACKUP_ON = "autobackup_enabled"

# (label, nilai) untuk chip filter
JENIS_OPTIONS = [
    ("Gambar", "image"), ("Video", "video"), ("Audio", "audio"),
    ("PDF", "pdf"), ("Arsip", "archive"), ("Dokumen", "doc"),
]
TANGGAL_OPTIONS = [
    ("Hari ini", 1), ("7 hari terakhir", 7),
    ("30 hari terakhir", 30), ("Tahun ini", "year"),
]
UKURAN_OPTIONS = [
    ("< 1 MB", (0, 1024**2)),
    ("1 - 100 MB", (1024**2, 100 * 1024**2)),
    ("100 MB - 1 GB", (100 * 1024**2, 1024**3)),
    ("> 1 GB", (1024**3, None)),
]
SORT_OPTIONS = [
    ("Nama (A-Z)", ("name", False)),
    ("Nama (Z-A)", ("name", True)),
    ("Terbaru", ("date", True)),
    ("Terlama", ("date", False)),
    ("Terbesar", ("size", True)),
    ("Terkecil", ("size", False)),
]


class MainWindow(QMainWindow):
    def __init__(self, client, db: Database, channel_entity,
                 me=None) -> None:
        super().__init__()
        self.client = client
        self.db = db
        self.channel = channel_entity
        self.me = me

        self._path: list[FolderRecord] = []  # breadcrumb; [] = root
        self._transfer_task: asyncio.Task | None = None
        self._busy = False
        self._filters: dict[str, object] = {
            "jenis": None, "tanggal": None, "ukuran": None,
        }
        self._sort: tuple[str, bool] = ("name", False)
        self._thumb_inflight: set[int] = set()
        self._previews: list[PreviewWindow] = []
        previewer.prune_cache()

        self.setWindowTitle("TeleDrive")
        self.setWindowIcon(QIcon(LOGO_PATH))
        self.resize(1000, 620)
        self._theme = self.db.get_meta(META_THEME) or "light"
        self.setStyleSheet(build_qss(self._theme))
        self.setAcceptDrops(True)

        root = QWidget()
        root.setObjectName("Root")
        outer = QHBoxLayout(root)
        outer.setContentsMargins(12, 8, 16, 12)
        outer.setSpacing(12)
        outer.addWidget(self._build_sidebar())
        outer.addLayout(self._build_main_area(), stretch=1)
        self.setCentralWidget(root)

        self.transfer = TransferCard()
        self.transfer.setParent(root)
        self.transfer.cancel_clicked.connect(self.on_cancel_transfer)

        self._apply_theme(self._theme, save=False)
        self._build_tray()
        self._setup_autobackup()
        self.refresh()
        QTimer.singleShot(0, self._offer_resume_queue)

    # ================= layout =================

    def _build_sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(210)
        v = QVBoxLayout(side)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(10)

        head = QWidget()
        hh = QHBoxLayout(head)
        hh.setContentsMargins(8, 6, 4, 6)
        hh.setSpacing(9)
        logo = QLabel()
        logo.setPixmap(QIcon(LOGO_PATH).pixmap(28, 28))
        title = QLabel("TeleDrive")
        title.setObjectName("AppTitle")
        hh.addWidget(logo)
        hh.addWidget(title)
        hh.addStretch()
        v.addWidget(head)

        self.btn_new = QPushButton("Baru")
        self.btn_new.setObjectName("NewButton")
        self.btn_new.setIcon(plus_icon(40))
        self.btn_new.setIconSize(QSize(20, 20))
        self.btn_new.setFixedSize(146, 46)  # selebar dropdown-nya
        self.btn_new.setCursor(Qt.CursorShape.PointingHandCursor)
        menu = polish_menu(QMenu(self))
        menu.addAction("Upload file", self.on_upload)
        menu.addAction("Upload folder", self.on_upload_folder)
        menu.addAction("Folder baru", self.on_new_folder)
        self.btn_new.setMenu(menu)
        v.addWidget(self.btn_new, alignment=Qt.AlignmentFlag.AlignLeft)

        nav = QFrame()
        nav.setObjectName("NavItem")
        nh = QHBoxLayout(nav)
        nh.setContentsMargins(16, 9, 16, 9)
        nh.setSpacing(11)
        self._nav_ic = QLabel()
        self._nav_ic.setPixmap(drive_icon(36).pixmap(18, 18))
        nh.addWidget(self._nav_ic)
        nh.addWidget(QLabel("Drive Saya"))
        nh.addStretch()
        v.addWidget(nav)

        self.btn_sync = QPushButton("Sinkronkan")
        self.btn_sync.setObjectName("SideAction")
        self.btn_sync.setIcon(sync_icon(32))
        self.btn_sync.setIconSize(QSize(16, 16))
        self.btn_sync.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sync.setToolTip(
            "Pindai channel Telegram: pulihkan file yang belum tercatat "
            "dan tandai yang hilang"
        )
        self.btn_sync.clicked.connect(self.on_sync)
        v.addWidget(self.btn_sync)

        self.btn_settings = QPushButton("Pengaturan")
        self.btn_settings.setObjectName("SideAction")
        self.btn_settings.setIcon(gear_icon(32))
        self.btn_settings.setIconSize(QSize(16, 16))
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.clicked.connect(self.on_settings)
        v.addWidget(self.btn_settings)

        v.addStretch()
        self.storage_label = QLabel()
        self.storage_label.setObjectName("StorageLabel")
        self.storage_label.setWordWrap(True)
        v.addWidget(self.storage_label)
        return side

    def _build_main_area(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(10)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("SearchBar")
        self.search_edit.setPlaceholderText("Telusuri di TeleDrive")
        self.search_edit.setFixedHeight(46)  # radius QSS 23px = pill penuh
        self._search_action = self.search_edit.addAction(
            search_icon(36), QLineEdit.ActionPosition.LeadingPosition
        )
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.refresh)
        col.addWidget(self.search_edit)

        content = QFrame()
        content.setObjectName("Content")
        cv = QVBoxLayout(content)
        cv.setContentsMargins(16, 10, 16, 12)
        cv.setSpacing(6)

        self.breadcrumb = QWidget()
        self.breadcrumb.setObjectName("Breadcrumb")
        self._crumb_layout = QHBoxLayout(self.breadcrumb)
        self._crumb_layout.setContentsMargins(0, 0, 0, 0)
        self._crumb_layout.setSpacing(2)

        hdr = QHBoxLayout()
        hdr.addWidget(self.breadcrumb, stretch=1)
        hdr.addWidget(self._build_sort_chip())
        hdr.addWidget(self._build_view_toggle())
        cv.addLayout(hdr)
        cv.addLayout(self._build_filter_bar())

        self.browser = FileBrowser()
        self.browser.folder_opened.connect(self.open_folder)
        self.browser.file_activated.connect(self.on_activate)
        self.browser.context_requested.connect(self._context_menu)
        cv.addWidget(self.browser, stretch=1)

        col.addWidget(content, stretch=1)
        return col

    def _build_view_toggle(self) -> QFrame:
        toggle = QFrame()
        toggle.setObjectName("ViewToggle")
        toggle.setFixedHeight(34)
        th = QHBoxLayout(toggle)
        th.setContentsMargins(3, 3, 3, 3)
        th.setSpacing(0)

        self.btn_list = QPushButton()
        self.btn_list.setIcon(list_icon(32))
        self.btn_grid = QPushButton()
        self.btn_grid.setIcon(grid_icon(32))
        group = QButtonGroup(self)
        for btn, mode in ((self.btn_list, "list"), (self.btn_grid, "grid")):
            btn.setCheckable(True)
            btn.setFixedSize(48, 28)  # radius QSS 14px = pill penuh
            btn.setIconSize(QSize(16, 16))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, m=mode: self._set_view_mode(m))
            group.addButton(btn)
            th.addWidget(btn)
        self.btn_grid.setChecked(True)
        return toggle

    def _set_view_mode(self, mode: str) -> None:
        self.browser.set_display_mode(mode)
        self.refresh()

    # ================= tema =================

    def _apply_theme(self, theme: str, save: bool = True) -> None:
        self._theme = theme
        self.setStyleSheet(build_qss(theme))
        ink = icon_ink(theme)
        self.btn_new.setIcon(plus_icon(40, ink))
        self._search_action.setIcon(search_icon(36, ink))
        self.btn_list.setIcon(list_icon(32, ink))
        self.btn_grid.setIcon(grid_icon(32, ink))
        self.btn_sync.setIcon(sync_icon(32, ink))
        self.btn_settings.setIcon(gear_icon(32, ink))
        self.sort_chip.setIcon(caret_icon(32, ink))
        for chip in self._chips.values():
            chip.setIcon(caret_icon(32, ink))
        # icon nav kontras dengan pill biru nav
        nav_color = "#c2e7ff" if theme == "dark" else "#001d35"
        self._nav_ic.setPixmap(drive_icon(36, nav_color).pixmap(18, 18))
        if save:
            self.db.set_meta(META_THEME, theme)

    # ================= system tray =================

    def _build_tray(self) -> None:
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(QIcon(LOGO_PATH), self)
        self.tray.setToolTip("TeleDrive")
        # simpan ref — QMenu tanpa parent bisa kena GC dan menu tray kosong
        self._tray_menu = QMenu()
        self._tray_menu.addAction("Buka TeleDrive", self._show_from_tray)
        self._tray_menu.addAction("Sinkronkan", self.on_sync)
        self._tray_menu.addSeparator()
        self._tray_menu.addAction("Keluar", QApplication.quit)
        self.tray.setContextMenu(self._tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        self._tray_notice_shown = False

    def _show_from_tray(self) -> None:
        self.show()
        self.setWindowState(
            self.windowState() & ~Qt.WindowState.WindowMinimized
        )
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_from_tray()

    def closeEvent(self, event) -> None:
        if self.tray is not None:
            event.ignore()
            self.hide()
            if not self._tray_notice_shown:
                self._tray_notice_shown = True
                self.tray.showMessage(
                    "TeleDrive tetap berjalan",
                    "Transfer dan auto-backup jalan terus di background. "
                    "Klik kanan icon tray > Keluar untuk menutup.",
                    QSystemTrayIcon.MessageIcon.Information, 4000,
                )
        else:
            super().closeEvent(event)

    # ================= pengaturan =================

    def on_settings(self) -> None:
        if self.me is not None:
            name = " ".join(
                p for p in (self.me.first_name, self.me.last_name) if p
            )
            phone = f" (+{self.me.phone})" if self.me.phone else ""
            account = f"{name}{phone}"
            if getattr(self.me, "premium", False):
                account += " · Premium"
        else:
            account = "Akun Telegram"

        dlg = SettingsDialog(
            self,
            account_label=account,
            theme=self._theme,
            backup_enabled=self.db.get_meta(META_BACKUP_ON) == "1",
            backup_path=self.db.get_meta(META_BACKUP_PATH) or "",
        )
        if not dlg.exec():
            return
        if dlg.logout:
            answer = QMessageBox.question(
                self, "Logout",
                "Logout menghapus session di PC ini — kamu perlu login "
                "ulang dengan OTP. File di Telegram tidak terhapus. Lanjut?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                asyncio.create_task(self._logout())
            return

        if dlg.result_theme != self._theme:
            self._apply_theme(dlg.result_theme)
        self.db.set_meta(META_BACKUP_ON,
                         "1" if dlg.result_backup_enabled else "0")
        self.db.set_meta(META_BACKUP_PATH, dlg.result_backup_path)
        self._setup_autobackup()

    async def _logout(self) -> None:
        try:
            await self.client.log_out()
        except Exception as e:
            QMessageBox.critical(self, "Logout gagal", str(e))
            return
        QApplication.quit()

    # ================= auto-backup =================

    def _setup_autobackup(self) -> None:
        if not hasattr(self, "_backup_watcher"):
            self._backup_watcher = QFileSystemWatcher(self)
            self._backup_watcher.directoryChanged.connect(
                self._on_backup_dir_changed
            )
            self._backup_debounce = QTimer(self)
            self._backup_debounce.setSingleShot(True)
            self._backup_debounce.setInterval(2000)  # tunggu file selesai ditulis
            self._backup_debounce.timeout.connect(self._scan_backup_folder)

        if self._backup_watcher.directories():
            self._backup_watcher.removePaths(
                self._backup_watcher.directories()
            )
        enabled = self.db.get_meta(META_BACKUP_ON) == "1"
        path = self.db.get_meta(META_BACKUP_PATH) or ""
        if enabled and os.path.isdir(path):
            self._backup_watcher.addPath(path)
            QTimer.singleShot(1500, self._scan_backup_folder)

    def _on_backup_dir_changed(self, _path: str) -> None:
        self._backup_debounce.start()

    def _scan_backup_folder(self) -> None:
        if self.db.get_meta(META_BACKUP_ON) != "1":
            return
        path = self.db.get_meta(META_BACKUP_PATH) or ""
        if not os.path.isdir(path):
            return
        new_files = []
        for fn in sorted(os.listdir(path)):
            full = os.path.join(path, fn)
            if not os.path.isfile(full):
                continue
            if os.path.getsize(full) > settings.MAX_UPLOAD_SIZE:
                continue
            if self.db.has_local_path(full) or self.db.queue_has_path(full):
                continue
            new_files.append(full)
        if not new_files:
            return
        folder_id = self.db.get_or_create_folder("Auto-backup", None)
        for p in new_files:
            self.db.queue_add(p, folder_id)
        self._info(f"Auto-backup: {len(new_files)} file baru diantrikan")
        if not self._busy:
            self._transfer_task = asyncio.create_task(
                self._process_upload_queue()
            )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_transfer_card()

    def _place_transfer_card(self) -> None:
        if self.centralWidget():
            self.transfer.relayout()
            x = self.centralWidget().width() - self.transfer.width() - 28
            y = self.centralWidget().height() - self.transfer.height() - 22
            self.transfer.move(QPoint(max(0, x), max(0, y)))

    # ================= filter & sort =================

    def _build_filter_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self._chips: dict[str, QPushButton] = {}
        self._base_labels: dict[str, str] = {}
        for key, label, options in (
            ("jenis", "Jenis", JENIS_OPTIONS),
            ("tanggal", "Diupload", TANGGAL_OPTIONS),
            ("ukuran", "Ukuran", UKURAN_OPTIONS),
        ):
            chip = self._make_chip(label)
            menu = polish_menu(QMenu(self))
            for opt_label, value in options:
                menu.addAction(
                    opt_label,
                    lambda k=key, v=value, t=opt_label: self._set_filter(k, v, t),
                )
            menu.addSeparator()
            menu.addAction(
                "Hapus filter", lambda k=key: self._set_filter(k, None, None)
            )
            chip.setMenu(menu)
            self._chips[key] = chip
            self._base_labels[key] = label
            bar.addWidget(chip)
        bar.addStretch()
        return bar

    def _build_sort_chip(self) -> QPushButton:
        self.sort_chip = self._make_chip("Urutkan")
        menu = polish_menu(QMenu(self))
        for label, value in SORT_OPTIONS:
            menu.addAction(
                label, lambda v=value, t=label: self._set_sort(v, t)
            )
        self.sort_chip.setMenu(menu)
        return self.sort_chip

    def _make_chip(self, label: str) -> QPushButton:
        chip = QPushButton(label)
        chip.setObjectName("FilterChip")
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        chip.setIcon(caret_icon(32))
        chip.setIconSize(QSize(14, 14))
        chip.setLayoutDirection(Qt.LayoutDirection.RightToLeft)  # caret kanan
        return chip

    def _set_filter(self, key: str, value, label: str | None) -> None:
        self._filters[key] = value
        chip = self._chips[key]
        chip.setText(label or self._base_labels[key])
        chip.setProperty("active", "true" if value is not None else "false")
        chip.style().unpolish(chip)
        chip.style().polish(chip)
        self.refresh()

    def _set_sort(self, value: tuple[str, bool], label: str) -> None:
        self._sort = value
        default = value == ("name", False)
        self.sort_chip.setText("Urutkan" if default else label)
        self.sort_chip.setProperty("active", "false" if default else "true")
        self.sort_chip.style().unpolish(self.sort_chip)
        self.sort_chip.style().polish(self.sort_chip)
        self.refresh()

    def _filters_active(self) -> bool:
        return any(v is not None for v in self._filters.values())

    def _match_filters(self, r: FileRecord) -> bool:
        jenis = self._filters["jenis"]
        if jenis is not None and file_kind(r.mime_type) != jenis:
            return False

        tanggal = self._filters["tanggal"]
        if tanggal is not None:
            try:  # uploaded_at = CURRENT_TIMESTAMP SQLite (UTC)
                up = datetime.strptime(
                    r.uploaded_at, "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                return False
            now = datetime.now(timezone.utc)
            if tanggal == "year":
                cutoff = datetime(now.year, 1, 1, tzinfo=timezone.utc)
            else:
                cutoff = now - timedelta(days=tanggal)
            if up < cutoff:
                return False

        ukuran = self._filters["ukuran"]
        if ukuran is not None:
            lo, hi = ukuran
            size = r.size_bytes
            if size is None or size < lo or (hi is not None and size >= hi):
                return False
        return True

    def _sorted(self, folders: list[FolderRecord],
                files: list[FileRecord]) -> tuple[list, list]:
        key, reverse = self._sort
        if key == "name":
            files.sort(key=lambda r: r.original_name.casefold(),
                       reverse=reverse)
            folders.sort(key=lambda f: f.name.casefold(), reverse=reverse)
        elif key == "date":
            files.sort(key=lambda r: r.uploaded_at or "", reverse=reverse)
        elif key == "size":
            files.sort(key=lambda r: r.size_bytes or 0, reverse=reverse)
        return folders, files

    # ================= navigasi & refresh =================

    def current_folder_id(self) -> int | None:
        return self._path[-1].id if self._path else None

    def open_folder(self, folder: FolderRecord) -> None:
        self.search_edit.clear()
        self._path.append(folder)
        self.refresh()

    def _goto_depth(self, depth: int) -> None:
        self._path = self._path[:depth]
        self.refresh()

    def refresh(self) -> None:
        term = self.search_edit.text().strip()
        filtering = self._filters_active()
        if term or filtering:
            # Filter aktif = cari global (seluruh Drive), seperti GDrive
            files = [f for f in self.db.search(term) if self._match_filters(f)]
            folders = [f for f in self.db.list_all_folders()
                       if term and term.lower() in f.name.lower()]
        else:
            fid = self.current_folder_id()
            folders = self.db.list_folders(fid)
            files = self.db.list_in_folder(fid)
        folders, files = self._sorted(folders, files)
        self.browser.populate(folders, files)
        self._rebuild_breadcrumb(searching=bool(term) or filtering)
        used = human_size(self.db.total_synced_bytes())
        self.storage_label.setText(f"{used} tersimpan di Telegram")
        self._schedule_thumbs(files)

    def _schedule_thumbs(self, files: list[FileRecord]) -> None:
        targets = [
            r for r in files
            if r.status == "synced"
            and file_kind(r.mime_type) in ("image", "video")
            and r.id not in self._thumb_inflight
            and not thumb_path(r.id).exists()
        ]
        if targets:
            asyncio.create_task(self._fetch_thumbs(targets))

    async def _fetch_thumbs(self, targets: list[FileRecord]) -> None:
        self._thumb_inflight.update(r.id for r in targets)
        try:
            await thumbs.fetch_thumbs(
                self.client, self.channel, targets,
                on_ready=self.browser.update_thumb,
            )
        except Exception:
            pass  # thumb gagal tidak boleh mengganggu UI
        finally:
            self._thumb_inflight.difference_update(r.id for r in targets)

    def _rebuild_breadcrumb(self, searching: bool) -> None:
        while self._crumb_layout.count():
            w = self._crumb_layout.takeAt(0).widget()
            if w:
                w.deleteLater()

        if searching:
            lbl = QLabel("Hasil pencarian"
                         if self.search_edit.text().strip() else "Hasil filter")
            lbl.setObjectName("Crumb")
            self._crumb_layout.addWidget(lbl)
            self._crumb_layout.addStretch()
            return

        crumbs = [("Drive Saya", 0)] + [
            (f.name, i + 1) for i, f in enumerate(self._path)
        ]
        for name, depth in crumbs:
            btn = QPushButton(name)
            is_last = depth == len(crumbs) - 1
            btn.setProperty("last", "true" if is_last else "false")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, d=depth: self._goto_depth(d))
            self._crumb_layout.addWidget(btn)
            if not is_last:
                sep = QLabel("›")
                sep.setObjectName("Crumb")
                self._crumb_layout.addWidget(sep)
        self._crumb_layout.addStretch()

    def _info(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 8000)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy

    # ================= context menu =================

    def _context_menu(self, entry, global_pos) -> None:
        selected = self.browser.selected_entries()
        sel_files = [rec for kind, rec in selected if kind == "file"]

        menu = polish_menu(QMenu(self))
        if entry is None:
            menu.addAction("Upload file ke sini", self.on_upload)
            menu.addAction("Folder baru", self.on_new_folder)
        elif len(sel_files) > 1:
            n = len(sel_files)
            menu.addAction(f"Download {n} file",
                           lambda: self._start_downloads(sel_files))
            menu.addAction(f"Pindahkan {n} file ke...",
                           lambda: self.on_move(sel_files))
            menu.addAction(f"Hapus {n} file",
                           lambda: self.on_delete_records(sel_files))
        else:
            kind, rec = entry
            if kind == "folder":
                menu.addAction("Buka", lambda: self.open_folder(rec))
                menu.addAction("Ganti nama",
                               lambda: self.on_rename(("folder", rec)))
                menu.addAction("Hapus folder",
                               lambda: self.on_delete_folder(rec))
            else:
                if previewer.kind_for(rec):
                    menu.addAction("Pratinjau", lambda: self.on_preview(rec))
                menu.addAction("Download",
                               lambda: self.on_download_record(rec))
                menu.addAction("Kirim ke chat Telegram...",
                               lambda: self.on_share(rec))
                menu.addAction("Ganti nama",
                               lambda: self.on_rename(("file", rec)))
                menu.addAction("Pindahkan ke...",
                               lambda: self.on_move([rec]))
                menu.addAction("Hapus",
                               lambda: self.on_delete_records([rec]))
        menu.exec(global_pos)

    # ================= bagikan =================

    def on_share(self, record: FileRecord) -> None:
        asyncio.create_task(self._share(record))

    async def _share(self, record: FileRecord) -> None:
        try:
            dialogs = await self.client.get_dialogs(limit=50)
        except Exception as e:
            QMessageBox.critical(self, "Bagikan gagal", str(e))
            return
        options, entities = [], []
        for d in dialogs:
            if d.entity.id == self.channel.id:
                continue  # jangan tawarkan channel storage sendiri
            options.append(d.name or "(tanpa nama)")
            entities.append(d.entity)
        if not options:
            QMessageBox.information(
                self, "Bagikan", "Tidak ada chat yang bisa dituju."
            )
            return
        choice, ok = QInputDialog.getItem(
            self, "Kirim ke chat Telegram",
            f"Kirim '{record.original_name}' ke:", options, 0, False,
        )
        if not ok:
            return
        target = entities[options.index(choice)]
        try:
            await sharer.send_copy(self.client, self.channel, target, record)
            self._info(f"{record.original_name}: terkirim ke {choice}")
        except Exception as e:
            QMessageBox.critical(self, "Bagikan gagal", str(e))

    # ================= folder =================

    def on_new_folder(self) -> None:
        name = NewFolderDialog.get_name(self)
        if not name:
            return
        try:
            self.db.create_folder(name, self.current_folder_id())
            self.refresh()
        except ValueError as e:
            QMessageBox.warning(self, "Folder baru", str(e))

    def on_delete_folder(self, folder: FolderRecord) -> None:
        if not self.db.folder_is_empty(folder.id):
            QMessageBox.warning(
                self, "Hapus folder",
                f"'{folder.name}' tidak kosong. Kosongkan dulu isinya.",
            )
            return
        self.db.delete_folder(folder.id)
        self.refresh()

    def on_move(self, records: list[FileRecord]) -> None:
        options = ["Drive Saya (root)"]
        folders = self.db.list_all_folders()
        paths = {f.id: self._folder_path(f, folders) for f in folders}
        options += [paths[f.id] for f in folders]
        choice, ok = QInputDialog.getItem(
            self, "Pindahkan ke...", "Folder tujuan:", options, 0, False
        )
        if not ok:
            return
        if choice == options[0]:
            target = None
        else:
            target = next(f.id for f in folders if paths[f.id] == choice)
        asyncio.create_task(self._move_records(records, target))

    async def _move_records(
        self, records: list[FileRecord], target: int | None
    ) -> None:
        """Pindah + publikasikan folder ke caption (sinkron antar
        perangkat) — butuh jaringan, makanya async."""
        try:
            for rec in records:
                await renamer.move_file(
                    self.client, self.channel, self.db, rec, target
                )
        except Exception as e:
            QMessageBox.critical(self, "Pindahkan gagal", str(e))
        self.refresh()

    @staticmethod
    def _folder_path(folder: FolderRecord, all_folders: list[FolderRecord]) -> str:
        by_id = {f.id: f for f in all_folders}
        parts, cur = [folder.name], folder
        while cur.parent_id is not None and cur.parent_id in by_id:
            cur = by_id[cur.parent_id]
            parts.append(cur.name)
        return " / ".join(reversed(parts))

    # ================= rename =================

    def on_rename(self, entry: tuple[str, object]) -> None:
        kind, rec = entry
        current = rec.name if kind == "folder" else rec.original_name
        name = TextInputDialog.get_text(
            self, "Ganti nama", "Simpan", text=current
        )
        if not name or name == current:
            return
        if kind == "folder":
            try:
                self.db.rename_folder(rec.id, name)
                self.refresh()
            except ValueError as e:
                QMessageBox.warning(self, "Ganti nama", str(e))
        else:
            asyncio.create_task(self._rename_file(rec, name))

    async def _rename_file(self, record: FileRecord, new_name: str) -> None:
        try:
            await renamer.rename_file(
                self.client, self.channel, self.db, record, new_name
            )
            self._info(f"Nama diganti: {new_name}")
        except Exception as e:
            QMessageBox.critical(self, "Ganti nama gagal", str(e))
        self.refresh()

    # ================= sinkronisasi =================

    def on_sync(self) -> None:
        if self._busy:
            self._info("Tunggu transfer yang sedang jalan (atau batalkan dulu)")
            return
        self._transfer_task = asyncio.create_task(self._sync())

    async def _sync(self) -> None:
        self._set_busy(True)
        self.btn_sync.setEnabled(False)
        self.transfer.begin_batch("Sinkronisasi")
        row = self.transfer.add_item("Memindai channel...")
        row.set_indeterminate()
        self._place_transfer_card()
        try:
            report = await sync.sync_channel(
                self.client, self.channel, self.db,
                progress=lambda n: row.set_status(f"{n} message"),
            )
            # migrasi satu kali: folder desktop lama diterbitkan ke caption
            # supaya perangkat lain (Android) bisa merekonstruksinya
            row.set_status("Publikasi folder…")
            published = await sync.publish_folders(
                self.client, self.channel, self.db,
                progress=lambda n: row.set_status(f"Publikasi folder… {n}"),
            )
            text = report.summary()
            if published:
                text += f". {published} caption folder dipublikasikan"
            QMessageBox.information(self, "Sinkronisasi", text)
        except asyncio.CancelledError:
            self._info("Sinkronisasi dibatalkan")
        except Exception as e:
            QMessageBox.critical(self, "Sinkronisasi gagal", str(e))
        finally:
            self.transfer.end()
            self.btn_sync.setEnabled(True)
            self._set_busy(False)
            self._transfer_task = None
            self.refresh()

    # ================= upload =================

    def on_upload(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Pilih file untuk diupload")
        if paths:
            self._enqueue_paths(paths)

    def on_upload_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Pilih folder untuk diupload"
        )
        if path:
            self._enqueue_folder(path)

    def _enqueue_folder(self, root: str) -> None:
        """Antrikan seluruh isi folder; strukturnya jadi folder virtual."""
        root = os.path.abspath(root)
        base_name = os.path.basename(root.rstrip("\\/")) or root
        base_id = self.db.get_or_create_folder(
            base_name, self.current_folder_id()
        )
        dir_ids = {root: base_id}
        accepted: list[tuple[str, int]] = []
        rejected: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            parent = dir_ids[dirpath]
            for d in sorted(dirnames):
                dir_ids[os.path.join(dirpath, d)] = \
                    self.db.get_or_create_folder(d, parent)
            for fn in sorted(filenames):
                full = os.path.join(dirpath, fn)
                if os.path.getsize(full) > settings.MAX_UPLOAD_SIZE:
                    rejected.append(full)
                else:
                    accepted.append((full, parent))
        if rejected:
            names = "\n".join(
                f"- {os.path.basename(p)} ({human_size(os.path.getsize(p))})"
                for p in rejected
            )
            QMessageBox.warning(
                self, "File terlalu besar",
                f"Melebihi limit {settings.MAX_UPLOAD_SIZE / 1024**3:.1f} GB, "
                f"dilewati:\n\n{names}",
            )
        for p, fid in accepted:
            self.db.queue_add(p, fid)
        self.refresh()  # struktur folder baru langsung terlihat
        if accepted and not self._busy:
            self._transfer_task = asyncio.create_task(
                self._process_upload_queue()
            )

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [
            u.toLocalFile() for u in event.mimeData().urls()
            if u.isLocalFile()
        ]
        dirs = [p for p in paths if os.path.isdir(p)]
        files = [p for p in paths if os.path.isfile(p)]
        for d in dirs:
            self._enqueue_folder(d)
        if files:
            self._enqueue_paths(files)
        event.acceptProposedAction()

    def _enqueue_paths(self, paths: list[str]) -> None:
        rejected = [p for p in paths
                    if os.path.getsize(p) > settings.MAX_UPLOAD_SIZE]
        accepted = [p for p in paths if p not in rejected]
        if rejected:
            names = "\n".join(
                f"- {os.path.basename(p)} ({human_size(os.path.getsize(p))})"
                for p in rejected
            )
            QMessageBox.warning(
                self, "File terlalu besar",
                f"Melebihi limit {settings.MAX_UPLOAD_SIZE / 1024**3:.1f} GB, "
                f"dilewati:\n\n{names}",
            )

        fid = self.current_folder_id()
        for p in accepted:
            self.db.queue_add(p, fid)
        if accepted and not self._busy:
            self._transfer_task = asyncio.create_task(
                self._process_upload_queue()
            )

    def _offer_resume_queue(self) -> None:
        n = self.db.queue_count()
        if not n:
            return
        answer = QMessageBox.question(
            self, "Lanjutkan upload",
            f"Ada {n} file di antrian upload yang belum selesai dari sesi "
            "sebelumnya. Lanjutkan sekarang?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._transfer_task = asyncio.create_task(
                self._process_upload_queue()
            )
        else:
            self.db.queue_clear()

    async def _process_upload_queue(self) -> None:
        self._set_busy(True)
        done = 0
        failed = 0
        self.transfer.begin_batch("Upload")
        self._place_transfer_card()
        try:
            while True:
                item = self.db.queue_next()
                if item is None:
                    break
                name = os.path.basename(item.local_path)
                if not os.path.exists(item.local_path):
                    self._info(f"{name}: file tidak ditemukan, dilewati")
                    self.db.queue_remove(item.id)
                    continue
                total = done + self.db.queue_count()
                self.transfer.set_title(f"Upload {done + 1}/{total}")
                row = self.transfer.add_item(name)
                row.start()
                self._place_transfer_card()
                try:
                    result = await uploader.upload_file(
                        self.client, self.channel, item.local_path,
                        progress_callback=row.set_progress,
                        find_by_sha256=self.db.find_by_sha256,
                        # nama+folder ke caption — kontrak resync antar device
                        caption=captions.build(
                            name, self.db.folder_path(item.folder_id)
                        ),
                    )
                    if result.deduped:
                        row.finish("Sudah ada (dedup)")
                    else:
                        self.db.save_upload(result, folder_id=item.folder_id)
                        row.finish("Selesai")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    failed += 1
                    row.finish("Gagal", ok=False)
                    self._info(f"Upload gagal - {name}: {e}")
                self.db.queue_remove(item.id)
                done += 1
                self.refresh()
            if failed:
                self._info(f"Upload selesai: {done - failed} sukses, "
                           f"{failed} gagal")
            else:
                self._info(f"Upload selesai ({done} file)")
        except asyncio.CancelledError:
            self.db.queue_clear()
            self._info("Upload dibatalkan")
        finally:
            self.transfer.end()
            self._set_busy(False)
            self._transfer_task = None
            self.refresh()

    # ================= pratinjau =================

    def on_activate(self, record: FileRecord) -> None:
        """Double-click: pratinjau kalau didukung, selain itu download."""
        if previewer.kind_for(record):
            self.on_preview(record)
        else:
            self.on_download_record(record)

    def on_preview(self, record: FileRecord) -> None:
        if not previewer.is_cached(record) and self._busy:
            self._info("Tunggu transfer yang sedang jalan (atau batalkan dulu)")
            return
        self._transfer_task = asyncio.create_task(self._preview(record))

    async def _preview(self, record: FileRecord) -> None:
        kind = previewer.kind_for(record)
        cached = previewer.is_cached(record)
        row = None
        if not cached:
            self._set_busy(True)
            self.transfer.begin_batch("Menyiapkan pratinjau")
            row = self.transfer.add_item(record.original_name)
            row.start()
            self._place_transfer_card()
        try:
            path = await previewer.fetch(
                self.client, self.channel, record,
                progress_callback=row.set_progress if row else None,
            )
        except asyncio.CancelledError:
            self._info("Pratinjau dibatalkan")
            return
        except downloader.IntegrityError:
            self.db.set_status(record.id, "corrupt")
            self.refresh()
            QMessageBox.critical(
                self, "File corrupt",
                f"{record.original_name}: sha256 tidak cocok dengan record.",
            )
            return
        except FileNotFoundError:
            self.db.set_status(record.id, "missing")
            self.refresh()
            QMessageBox.warning(
                self, "File hilang",
                f"{record.original_name}: message-nya sudah tidak ada "
                "di Telegram.",
            )
            return
        except Exception as e:
            QMessageBox.critical(self, "Pratinjau gagal", str(e))
            return
        finally:
            if not cached:
                self.transfer.end()
                self._set_busy(False)
                self._transfer_task = None

        win = PreviewWindow(
            self, record, path, kind, theme=self._theme,
            on_download=lambda: self._start_downloads([record]),
        )
        self._previews = [w for w in self._previews if w.isVisible()]
        self._previews.append(win)  # jaga ref — non-modal
        win.show()

    # ================= download =================

    def on_download_record(self, record: FileRecord) -> None:
        self._start_downloads([record])

    def _start_downloads(self, records: list[FileRecord]) -> None:
        if self._busy:
            self._info("Tunggu transfer yang sedang jalan (atau batalkan dulu)")
            return
        dest_dir = QFileDialog.getExistingDirectory(self, "Simpan ke folder")
        if not dest_dir:
            return
        self._transfer_task = asyncio.create_task(
            self._download_many(records, dest_dir)
        )

    @staticmethod
    def _unique_dest(dest_dir: str, name: str) -> str:
        dest = os.path.join(dest_dir, name)
        base, ext = os.path.splitext(name)
        counter = 1
        while os.path.exists(dest):
            dest = os.path.join(dest_dir, f"{base} ({counter}){ext}")
            counter += 1
        return dest

    async def _download_many(self, records: list[FileRecord],
                             dest_dir: str) -> None:
        self._set_busy(True)
        ok = 0
        current_dest = None
        self.transfer.begin_batch("Download")
        self._place_transfer_card()
        try:
            for i, rec in enumerate(records, 1):
                current_dest = self._unique_dest(dest_dir, rec.original_name)
                self.transfer.set_title(f"Download {i}/{len(records)}")
                row = self.transfer.add_item(rec.original_name)
                row.start()
                self._place_transfer_card()
                try:
                    await downloader.download_file(
                        self.client, self.channel, rec.message_id,
                        current_dest,
                        progress_callback=row.set_progress,
                        expected_sha256=rec.sha256,
                    )
                    ok += 1
                    row.finish("Selesai")
                except asyncio.CancelledError:
                    raise
                except downloader.IntegrityError:
                    self.db.set_status(rec.id, "corrupt")
                    row.finish("Corrupt", ok=False)
                    self._info(f"{rec.original_name}: sha256 tidak cocok, "
                               "status ditandai 'corrupt'")
                except FileNotFoundError:
                    self.db.set_status(rec.id, "missing")
                    row.finish("Hilang di Telegram", ok=False)
                except Exception as e:
                    row.finish("Gagal", ok=False)
                    self._info(f"Download gagal - {rec.original_name}: {e}")
            self._info(
                f"Download selesai ({ok}/{len(records)} file) di {dest_dir}"
            )
        except asyncio.CancelledError:
            if current_dest and os.path.exists(current_dest):
                os.remove(current_dest)  # buang hasil parsial
            self._info("Download dibatalkan")
        finally:
            self.transfer.end()
            self._set_busy(False)
            self._transfer_task = None
            self.refresh()

    # ================= delete & cancel =================

    def on_delete_records(self, records: list[FileRecord]) -> None:
        if len(records) == 1:
            text = (f"Hapus '{records[0].original_name}' dari Telegram?\n"
                    "Message di channel ikut terhapus permanen.")
        else:
            text = (f"Hapus {len(records)} file dari Telegram?\n"
                    "Message di channel ikut terhapus permanen.")
        answer = QMessageBox.question(self, "Hapus file", text)
        if answer == QMessageBox.StandardButton.Yes:
            asyncio.create_task(self._delete_many(records))

    async def _delete_many(self, records: list[FileRecord]) -> None:
        try:
            await self.client.delete_messages(
                self.channel, [r.message_id for r in records]
            )
            for rec in records:
                self.db.set_status(rec.id, "deleted")
            if len(records) == 1:
                self._info(f"{records[0].original_name}: terhapus")
            else:
                self._info(f"{len(records)} file terhapus")
        except Exception as e:
            QMessageBox.critical(self, "Delete gagal", str(e))
        self.refresh()

    def on_cancel_transfer(self) -> None:
        if self._transfer_task and not self._transfer_task.done():
            self._transfer_task.cancel()
