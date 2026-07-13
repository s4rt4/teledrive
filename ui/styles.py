"""Stylesheet global — palet ala Google Drive, tema light & dark.

QSS di-render dari template dengan token @nama@ (bukan str.format —
QSS penuh kurung kurawal). Tema aktif disimpan di tabel meta ('theme'),
MainWindow menerapkan ulang lewat build_qss() + re-icon.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMenu

PALETTES = {
    "light": {
        "root_bg": "#f8fafd",
        "content_bg": "#ffffff",
        "text": "#1f1f1f",
        "muted": "#5f6368",
        "muted2": "#444746",
        "item_bg": "#f0f4f9",
        "item_hover": "#e2e9f1",
        "sel_bg": "#c2e7ff",
        "sel_text": "#001d35",
        "border": "#dfe3e8",
        "chip_border": "#c4c7c5",
        "search_bg": "#e9eef6",
        "hover_bg": "#eef2f8",
        "accent": "#0b57d0",
        "accent_text": "#ffffff",
        "accent_hover": "#0a4cb8",
        "menu_bg": "#ffffff",
        "nav_bg": "#c2e7ff",
        "nav_text": "#001d35",
        "divider": "#eef1f4",
        "danger": "#b3261e",
        "danger_hover": "#fceeee",
        "input_border": "#747775",
        "progress_bg": "#e9eef6",
        "disabled": "#9aa0a6",
        "icon_ink": "#444746",
    },
    "dark": {
        "root_bg": "#131314",
        "content_bg": "#1e1f20",
        "text": "#e3e3e3",
        "muted": "#9aa0a6",
        "muted2": "#c4c7c5",
        "item_bg": "#2d2e30",
        "item_hover": "#37393b",
        "sel_bg": "#004a77",
        "sel_text": "#c2e7ff",
        "border": "#3c4043",
        "chip_border": "#5f6368",
        "search_bg": "#282a2c",
        "hover_bg": "#2d2e30",
        "accent": "#a8c7fa",
        "accent_text": "#062e6f",
        "accent_hover": "#bdd5fc",
        "menu_bg": "#2d2e30",
        "nav_bg": "#004a77",
        "nav_text": "#c2e7ff",
        "divider": "#2d2e30",
        "danger": "#f2b8b5",
        "danger_hover": "#3c2a29",
        "input_border": "#8e918f",
        "progress_bg": "#333537",
        "disabled": "#757775",
        "icon_ink": "#c4c7c5",
    },
}


def icon_ink(theme: str) -> str:
    return PALETTES.get(theme, PALETTES["light"])["icon_ink"]


def polish_menu(menu: QMenu) -> QMenu:
    """Bikin QMenu benar-benar rounded di Windows.

    Border-radius di QSS saja tidak cukup — window popup-nya tetap kotak,
    jadi sudutnya perlu frameless + translucent. NoDropShadowWindowHint
    mencegah bayangan kotak default muncul di belakang sudut bulat.
    """
    menu.setWindowFlags(
        menu.windowFlags()
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.NoDropShadowWindowHint
    )
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    return menu


_TEMPLATE = """
* {
    font-family: 'Segoe UI';
    font-size: 10pt;
    color: @text@;
}
QMainWindow, #Root {
    background: @root_bg@;
}

/* ---- sidebar ---- */
#Sidebar {
    background: @root_bg@;
    border: none;
}
#AppTitle {
    font-size: 15pt;
    font-weight: 600;
}
#NewButton {
    background: @content_bg@;
    border: 1px solid @border@;
    border-radius: 23px;   /* pill penuh: setengah tinggi fixed 46px */
    padding-left: 20px;
    font-size: 10.5pt;
    font-weight: 600;
    text-align: left;
}
#NewButton:hover { background: @hover_bg@; }
#NewButton:disabled { color: @disabled@; }
#NewButton::menu-indicator { image: none; width: 0; }

/* ---- dropdown / context menu ---- */
QMenu {
    background: @menu_bg@;
    border: 1px solid @border@;
    border-radius: 12px;
    padding: 6px 5px;
}
QMenu::item {
    background: transparent;
    border-radius: 8px;
    padding: 9px 36px 9px 14px;
    margin: 1px 3px;
}
QMenu::item:selected { background: @hover_bg@; }
QMenu::item:disabled { color: @disabled@; }
QMenu::separator { height: 1px; background: @border@; margin: 5px 10px; }

#NavItem {
    background: @nav_bg@;
    border-radius: 16px;
}
#NavItem QLabel {
    background: transparent;
    font-weight: 600;
    color: @nav_text@;
}
#StorageLabel {
    color: @muted@;
    font-size: 9pt;
    padding: 4px;
}

/* ---- tombol aksi sidebar ---- */
#SideAction {
    background: transparent;
    border: none;
    border-radius: 16px;
    padding: 9px 16px;
    text-align: left;
    color: @muted2@;
    font-weight: 600;
}
#SideAction:hover { background: @hover_bg@; }
#SideAction:disabled { color: @disabled@; }

/* ---- topbar ---- */
#SearchBar {
    background: @search_bg@;
    border: 1px solid transparent;
    border-radius: 23px;   /* pill: setengah dari tinggi fixed 46px */
    padding: 0 20px;
    font-size: 10.5pt;
}
#SearchBar:focus { background: @content_bg@; border: 1px solid @sel_bg@; }

/* ---- toggle list/grid ----
   Ukuran tombol di-fix dari kode (48x28) — radius harus <= setengah
   tinggi, kalau lebih Qt menggambar sudut kotak. */
#ViewToggle {
    background: @content_bg@;
    border: 1px solid @input_border@;
    border-radius: 17px;
}
#ViewToggle QPushButton {
    background: transparent;
    border: none;
    border-radius: 14px;
    padding: 0;
}
#ViewToggle QPushButton:checked { background: @sel_bg@; }
#ViewToggle QPushButton:hover:!checked { background: @hover_bg@; }

/* ---- chip filter ---- */
#FilterChip {
    background: @content_bg@;
    border: 1px solid @chip_border@;
    border-radius: 9px;
    padding: 6px 12px;
    color: @muted2@;
}
#FilterChip:hover { background: @hover_bg@; }
#FilterChip[active="true"] {
    background: @sel_bg@;
    border-color: @sel_bg@;
    color: @sel_text@;
    font-weight: 600;
}
#FilterChip::menu-indicator { image: none; width: 0; }

/* ---- dialog custom ---- */
#DialogCard {
    background: @content_bg@;
    border: 1px solid @border@;
    border-radius: 16px;
}
#DialogTitle { font-size: 13pt; font-weight: 600; background: transparent; }
#SectionLabel {
    color: @muted@;
    font-weight: 600;
    font-size: 9pt;
    background: transparent;
}
#DialogInput {
    background: @content_bg@;
    border: 1px solid @input_border@;
    border-radius: 8px;
    padding: 9px 12px;
}
#DialogInput:focus { border: 2px solid @accent@; padding: 8px 11px; }
#PrimaryButton {
    background: @accent@;
    color: @accent_text@;
    border: none;
    border-radius: 16px;
    padding: 8px 22px;
    font-weight: 600;
}
#PrimaryButton:hover { background: @accent_hover@; }
#PrimaryButton:disabled { background: @border@; color: @disabled@; }
#GhostButton {
    background: transparent;
    color: @accent@;
    border: none;
    border-radius: 16px;
    padding: 8px 16px;
    font-weight: 600;
}
#GhostButton:hover { background: @hover_bg@; }
#DangerButton {
    background: transparent;
    color: @danger@;
    border: 1px solid @border@;
    border-radius: 16px;
    padding: 8px 16px;
    font-weight: 600;
}
#DangerButton:hover { background: @danger_hover@; }
QCheckBox { background: transparent; spacing: 8px; }

/* ---- halaman login ---- */
#LoginSubtitle { color: @muted@; font-size: 10.5pt; background: transparent; }
#InfoLabel { color: @muted@; font-size: 9pt; background: transparent; }
#ErrorLabel {
    color: @danger@;
    font-size: 9pt;
    font-weight: 600;
    background: transparent;
}

/* ---- content ---- */
#Content {
    background: @content_bg@;
    border-radius: 16px;
}
#Breadcrumb QPushButton {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 4px 8px;
    font-size: 12pt;
    color: @muted2@;
}
#Breadcrumb QPushButton:hover { background: @hover_bg@; }
#Breadcrumb QPushButton[last="true"] {
    font-weight: 600;
    color: @text@;
}
#Crumb { color: @muted@; font-size: 12pt; }

QListWidget {
    background: transparent;
    border: none;
}
QListWidget::item {
    background: @item_bg@;
    border-radius: 12px;
    margin: 4px;
    padding: 4px;
}
QListWidget::item:hover { background: @item_hover@; }
QListWidget::item:selected { background: @sel_bg@; color: @sel_text@; }

/* ---- mode list berkolom ---- */
QTreeWidget {
    background: transparent;
    border: none;
}
QTreeWidget::item {
    padding: 9px 6px;
    border-bottom: 1px solid @divider@;
}
QTreeWidget::item:hover { background: @item_bg@; }
QTreeWidget::item:selected { background: @sel_bg@; color: @sel_text@; }
QHeaderView { background: transparent; border: none; }
QHeaderView::section {
    background: transparent;
    border: none;
    border-bottom: 1px solid @border@;
    padding: 6px;
    color: @muted@;
    font-weight: 600;
}
QTreeWidget QTableCornerButton::section { background: transparent; }

/* ---- scrollbar ---- */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: @chip_border@;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: @chip_border@;
    border-radius: 5px;
    min-width: 30px;
}
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ---- transfer card ---- */
#TransferCard {
    background: @content_bg@;
    border: 1px solid @border@;
    border-radius: 12px;
}
#TransferTitle { font-weight: 600; }
#TransferRowName { font-size: 9pt; }
#TransferRowStatus { color: @muted@; font-size: 8.5pt; }
#TransferRowStatus[error="true"] { color: @danger@; font-weight: 600; }
#CancelButton {
    background: transparent;
    border: 1px solid @border@;
    border-radius: 14px;
    padding: 4px 14px;
    color: @danger@;
    font-weight: 600;
}
#CancelButton:hover { background: @danger_hover@; }
QProgressBar {
    background: @progress_bg@;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    font-size: 1px;
    color: transparent;
}
QProgressBar::chunk { background: @accent@; border-radius: 4px; }

/* ---- pratinjau ---- */
#PreviewWindow { background: @root_bg@; }
#PreviewText {
    background: @content_bg@;
    border: none;
    border-radius: 10px;
    padding: 10px;
    font-size: 10.5pt;
}
QSlider::groove:horizontal {
    height: 4px;
    background: @progress_bg@;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: @accent@;
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}
QSlider::sub-page:horizontal { background: @accent@; border-radius: 2px; }

QStatusBar { background: @root_bg@; color: @muted@; }
QToolTip {
    background: @content_bg@;
    color: @text@;
    border: 1px solid @border@;
    padding: 4px;
}
"""


def build_qss(theme: str = "light") -> str:
    palette = PALETTES.get(theme, PALETTES["light"])
    qss = _TEMPLATE
    for token, value in palette.items():
        qss = qss.replace(f"@{token}@", value)
    return qss


QSS = build_qss("light")  # kompat: dipakai saat theme belum dibaca
