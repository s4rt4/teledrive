"""Dialog Pengaturan: akun (logout), tema, auto-backup folder.

Frameless + rounded seperti dialog lain. Dialog hanya mengumpulkan
pilihan — MainWindow yang menerapkan (ganti tema, pasang watcher,
logout) setelah exec() sukses.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class SettingsDialog(QDialog):
    def __init__(
        self,
        parent,
        account_label: str,
        theme: str,
        backup_enabled: bool,
        backup_path: str,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

        self.logout = False
        self.result_theme = theme
        self.result_backup_path = backup_path

        card = QFrame()
        card.setObjectName("DialogCard")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 70))
        card.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addWidget(card)

        v = QVBoxLayout(card)
        v.setContentsMargins(24, 20, 24, 16)
        v.setSpacing(14)

        title = QLabel("Pengaturan")
        title.setObjectName("DialogTitle")
        v.addWidget(title)

        # ---- akun ----
        v.addWidget(self._section("AKUN"))
        acc_row = QHBoxLayout()
        acc = QLabel(account_label)
        acc_row.addWidget(acc)
        acc_row.addStretch()
        btn_logout = QPushButton("Logout")
        btn_logout.setObjectName("DangerButton")
        btn_logout.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_logout.clicked.connect(self._on_logout)
        acc_row.addWidget(btn_logout)
        v.addLayout(acc_row)

        # ---- tema ----
        v.addWidget(self._section("TEMA"))
        theme_toggle = QFrame()
        theme_toggle.setObjectName("ViewToggle")
        theme_toggle.setFixedHeight(34)
        tt = QHBoxLayout(theme_toggle)
        tt.setContentsMargins(3, 3, 3, 3)
        tt.setSpacing(0)
        self.btn_light = QPushButton("Terang")
        self.btn_dark = QPushButton("Gelap")
        for btn, val in ((self.btn_light, "light"), (self.btn_dark, "dark")):
            btn.setCheckable(True)
            btn.setFixedHeight(28)
            btn.setMinimumWidth(90)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, t=val: self._set_theme(t))
            tt.addWidget(btn)
        (self.btn_dark if theme == "dark" else self.btn_light).setChecked(True)
        row = QHBoxLayout()
        row.addWidget(theme_toggle)
        row.addStretch()
        v.addLayout(row)

        # ---- auto-backup ----
        v.addWidget(self._section("AUTO-BACKUP"))
        self.chk_backup = QCheckBox("Upload otomatis file baru dari folder:")
        self.chk_backup.setChecked(backup_enabled)
        v.addWidget(self.chk_backup)
        path_row = QHBoxLayout()
        self.path_label = QLabel(backup_path or "(belum dipilih)")
        self.path_label.setObjectName("SectionLabel")
        path_row.addWidget(self.path_label, stretch=1)
        btn_pick = QPushButton("Pilih folder...")
        btn_pick.setObjectName("GhostButton")
        btn_pick.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_pick.clicked.connect(self._pick_folder)
        path_row.addWidget(btn_pick)
        v.addLayout(path_row)

        # ---- tombol ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Batal")
        btn_cancel.setObjectName("GhostButton")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("Simpan")
        btn_ok.setObjectName("PrimaryButton")
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        v.addLayout(btn_row)

        self.setMinimumWidth(430)

    @staticmethod
    def _section(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("SectionLabel")
        return lbl

    def _set_theme(self, theme: str) -> None:
        self.result_theme = theme
        self.btn_light.setChecked(theme == "light")
        self.btn_dark.setChecked(theme == "dark")

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Pilih folder auto-backup"
        )
        if path:
            self.result_backup_path = path
            self.path_label.setText(path)
            self.chk_backup.setChecked(True)

    def _on_logout(self) -> None:
        self.logout = True
        self.accept()

    @property
    def result_backup_enabled(self) -> bool:
        return self.chk_backup.isChecked() and bool(self.result_backup_path)
