"""Dialog custom ala Google Drive — frameless + rounded, tanpa chrome Windows."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class TextInputDialog(QDialog):
    """Satu input teks dengan tombol Batal + aksi utama."""

    def __init__(
        self,
        title: str,
        ok_label: str = "OK",
        text: str = "",
        placeholder: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

        card = QFrame()
        card.setObjectName("DialogCard")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 70))
        card.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)  # ruang untuk bayangan
        outer.addWidget(card)

        v = QVBoxLayout(card)
        v.setContentsMargins(24, 20, 24, 16)
        v.setSpacing(18)

        lbl = QLabel(title)
        lbl.setObjectName("DialogTitle")
        v.addWidget(lbl)

        self.edit = QLineEdit(text)
        self.edit.setObjectName("DialogInput")
        self.edit.setPlaceholderText(placeholder)
        self.edit.setMinimumWidth(300)
        self.edit.returnPressed.connect(self.accept)
        self.edit.textChanged.connect(
            lambda t: self.btn_ok.setEnabled(bool(t.strip()))
        )
        self.edit.selectAll()
        v.addWidget(self.edit)

        row = QHBoxLayout()
        row.addStretch()
        btn_cancel = QPushButton("Batal")
        btn_cancel.setObjectName("GhostButton")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton(ok_label)
        self.btn_ok.setObjectName("PrimaryButton")
        self.btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ok.setEnabled(bool(text.strip()))
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        row.addWidget(btn_cancel)
        row.addWidget(self.btn_ok)
        v.addLayout(row)

    def accept(self) -> None:
        if self.edit.text().strip():
            super().accept()

    @staticmethod
    def get_text(
        parent,
        title: str,
        ok_label: str = "OK",
        text: str = "",
        placeholder: str = "",
    ) -> str | None:
        dlg = TextInputDialog(title, ok_label, text, placeholder, parent)
        dlg.edit.setFocus()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.edit.text().strip() or None
        return None


class NewFolderDialog:
    @staticmethod
    def get_name(parent) -> str | None:
        return TextInputDialog.get_text(
            parent, "Folder baru", "Buat", placeholder="Folder tanpa nama"
        )
