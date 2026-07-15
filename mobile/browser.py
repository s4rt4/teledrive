"""Layar utama TeleDrive Android — browser file (paritas desktop).

Fitur: folder virtual, search, sort, thumbnail Telegram, upload via SAF
picker (queue persist di DB), download ke Download/TeleDrive publik,
pratinjau in-app (gambar/teks — tipe lain via app eksternal), rename
(caption = kontrak resync), pindah folder, hapus, panel transfer.

Semua operasi jaringan lewat asyncio task di loop bersama Kivy —
JANGAN pernah blokir callback UI.
"""
import asyncio
from pathlib import Path

from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView
from kivymd.toast import toast
from kivymd.uix.button import (
    MDFlatButton,
    MDFloatingActionButton,
    MDIconButton,
    MDRaisedButton,
)
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDIcon, MDLabel
from kivymd.uix.list import (
    IconLeftWidget,
    IconRightWidget,
    ImageLeftWidget,
    MDList,
    OneLineAvatarIconListItem,
    OneLineIconListItem,
    TwoLineAvatarIconListItem,
)
from kivymd.uix.progressbar import MDProgressBar
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField
from kivymd.uix.toolbar import MDTopAppBar

import androidio
from appmeta import __version__
from config import settings
from core import captions, previewer
from core.db import FileRecord
from core.deleter import delete_file
from core.downloader import IntegrityError
from core.renamer import move_file, rename_file
from core.sync import sync_channel
from core.thumbs import fetch_thumbs, thumb_path
from core.uploader import FileTooLargeError, upload_file

SORT_OPTIONS = [
    ("name_asc", "sort-alphabetical-ascending", "Nama A ke Z"),
    ("name_desc", "sort-alphabetical-descending", "Nama Z ke A"),
    ("date_desc", "sort-calendar-descending", "Terbaru dulu"),
    ("date_asc", "sort-calendar-ascending", "Terlama dulu"),
    ("size_desc", "sort-numeric-descending", "Terbesar dulu"),
    ("size_asc", "sort-numeric-ascending", "Terkecil dulu"),
]

ICON_BY_KIND = [
    ("image/", "file-image"),
    ("video/", "file-video"),
    ("audio/", "file-music"),
    ("application/pdf", "file-pdf-box"),
    ("application/zip", "zip-box"),
    ("text/", "file-document"),
]


def _icon_for(rec: FileRecord) -> str:
    mime = (rec.mime_type or "").lower()
    for prefix, icon in ICON_BY_KIND:
        if mime.startswith(prefix):
            return icon
    return "file"


class TapCard(ButtonBehavior, MDCard):
    """MDCard yang bisa ditekan (on_release) — sel grid. MDCard biasa
    tidak punya perilaku tombol; MDIconButton di dalamnya tetap memakan
    sentuhannya sendiri, jadi tombol menu tidak ikut membuka kartu."""


class BrowserScreen(MDScreen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.folder_id = None
        self.folder_stack = []  # [(id, nama)] — breadcrumb
        self.sort_mode = "name_asc"
        self.view_mode = "list"  # "list" | "grid"
        self._dialog = None
        self._uploading = False
        # Satu transfer pada satu waktu — paralel ke channel yang sama
        # adalah jalan tercepat ke FloodWait
        self._transfer_lock = asyncio.Lock()

        col = BoxLayout(orientation="vertical")

        self.toolbar = MDTopAppBar(title="TeleDrive", elevation=0)
        self.toolbar.right_action_items = self._toolbar_actions()
        col.add_widget(self.toolbar)

        # Search bar permanen tepat di bawah toolbar — SELALU terlihat.
        # Berada di luar ScrollView, jadi tidak ikut tergulung saat scroll.
        self.search_box = BoxLayout(
            size_hint_y=None, height=dp(60),
            padding=[dp(16), 0, dp(16), dp(4)],
        )
        self.search = MDTextField(hint_text="Cari file di semua folder…")
        self.search.bind(text=lambda *_: self.refresh())
        self.search_box.add_widget(self.search)
        col.add_widget(self.search_box)

        self.info = MDLabel(
            text="", theme_text_color="Secondary", font_style="Caption",
            halign="center", size_hint_y=None, height=dp(24),
        )
        col.add_widget(self.info)

        # List & grid berbagi satu ScrollView; kontennya ditukar saat
        # ganti mode (MDList vs GridLayout kartu thumbnail).
        self.mdlist = MDList()
        self.grid = GridLayout(
            cols=2, spacing=dp(10), padding=dp(10), size_hint_y=None,
        )
        self.grid.bind(minimum_height=self.grid.setter("height"))
        self.scroll = ScrollView()
        self.scroll.add_widget(self.mdlist)
        col.add_widget(self.scroll)

        self.panel = MDCard(
            orientation="vertical", size_hint_y=None, height=0, opacity=0,
            padding=[dp(16), dp(10), dp(16), dp(10)], spacing=dp(6),
            radius=[dp(12), dp(12), 0, 0],
        )
        self.panel_title = MDLabel(
            shorten=True, shorten_from="right",
            size_hint_y=None, height=dp(24),
        )
        self.panel_bar = MDProgressBar(
            max=100, value=0, size_hint_y=None, height=dp(6)
        )
        self.panel_status = MDLabel(
            theme_text_color="Secondary", font_style="Caption",
            size_hint_y=None, height=dp(20),
        )
        for w in (self.panel_title, self.panel_bar, self.panel_status):
            self.panel.add_widget(w)
        col.add_widget(self.panel)

        self.add_widget(col)

        self.fab = MDFloatingActionButton(
            icon="plus", pos_hint={"right": 0.95, "y": 0.03},
            on_release=lambda *_: self.fab_menu(),
        )
        self.add_widget(self.fab)

    # ---- lifecycle ----

    def start(self):
        """Dipanggil setelah login — sync awal + lanjutkan queue upload
        yang tersisa dari sesi sebelumnya (persist di DB)."""
        self.refresh()
        self.update_info()
        if self.app.client is not None:
            self.app.run_task(self.sync())
            self.app.run_task(self.process_queue())

    def handle_back(self) -> bool:
        """Tombol back Android: bersihkan pencarian / naik folder."""
        if self.search.text:
            self.search.text = ""  # bind text → refresh() otomatis
            return True
        if self.folder_stack:
            self.go_up()
            return True
        return False

    # ---- data & list ----

    def refresh(self):
        db = self.app.db
        if db is None:
            return

        term = self.search.text.strip()
        if term:
            folders, files = [], db.search(term)
        else:
            folders = db.list_folders(self.folder_id)
            files = db.list_in_folder(self.folder_id)
        files = self._sorted([f for f in files if f.status != "deleted"])

        if self.view_mode == "grid":
            self._show_grid(folders, files)
        else:
            self._show_list(folders, files)

        if self.folder_stack:
            self.toolbar.left_action_items = [
                ["arrow-left", lambda *_: self.go_up()]
            ]
            self.toolbar.title = self.folder_stack[-1][1]
        else:
            self.toolbar.left_action_items = []
            self.toolbar.title = "TeleDrive"

    def _show_list(self, folders, files):
        if self.mdlist.parent is None:
            self.scroll.clear_widgets()
            self.scroll.add_widget(self.mdlist)
        self.mdlist.clear_widgets()

        for f in folders:
            item = OneLineAvatarIconListItem(
                text=f.name,
                on_release=lambda w, fo=f: self.enter_folder(fo),
            )
            item.add_widget(IconLeftWidget(icon="folder"))
            item.add_widget(IconRightWidget(
                icon="dots-vertical",
                on_release=lambda w, fo=f: self.folder_menu(fo),
            ))
            self.mdlist.add_widget(item)

        for r in files:
            mb = (r.size_bytes or 0) / 1024**2
            sub = f"{mb:.1f} MB  •  {(r.uploaded_at or '')[:16]}"
            if r.status != "synced":
                sub += f"  •  {r.status}"
            item = TwoLineAvatarIconListItem(
                text=r.original_name, secondary_text=sub,
                on_release=lambda w, rec=r: self.app.run_task(
                    self.preview(rec)
                ),
            )
            tp = thumb_path(r.id)
            if r.status == "synced" and tp.exists():
                item.add_widget(ImageLeftWidget(source=str(tp)))
            elif r.status != "synced":
                item.add_widget(IconLeftWidget(icon="alert-circle-outline"))
            else:
                item.add_widget(IconLeftWidget(icon=_icon_for(r)))
            item.add_widget(IconRightWidget(
                icon="dots-vertical",
                on_release=lambda w, rec=r: self.file_menu(rec),
            ))
            self.mdlist.add_widget(item)

    def _show_grid(self, folders, files):
        if self.grid.parent is None:
            self.scroll.clear_widgets()
            self.scroll.add_widget(self.grid)
        self.grid.clear_widgets()
        for f in folders:
            self.grid.add_widget(self._grid_folder(f))
        for r in files:
            self.grid.add_widget(self._grid_file(r))

    def _grid_cell(self):
        return TapCard(
            orientation="vertical", size_hint_y=None, height=dp(168),
            padding=dp(6), spacing=dp(2), radius=[dp(12)],
            ripple_behavior=True,
        )

    def _grid_folder(self, folder):
        card = self._grid_cell()
        card.bind(on_release=lambda *_: self.enter_folder(folder))
        card.add_widget(MDIcon(
            icon="folder", halign="center", valign="center",
            font_size="64sp", theme_text_color="Custom",
            text_color=self.app.theme_cls.primary_color,
        ))
        card.add_widget(MDLabel(
            text=folder.name, halign="center", shorten=True,
            shorten_from="right", font_style="Caption",
            size_hint_y=None, height=dp(20),
        ))
        row = BoxLayout(size_hint_y=None, height=dp(28))
        row.add_widget(MDLabel(
            text="Folder", font_style="Caption",
            theme_text_color="Secondary",
        ))
        row.add_widget(MDIconButton(
            icon="dots-vertical",
            on_release=lambda *_: self.folder_menu(folder),
        ))
        card.add_widget(row)
        return card

    def _grid_file(self, r):
        card = self._grid_cell()
        card.bind(on_release=lambda *_: self.app.run_task(self.preview(r)))
        tp = thumb_path(r.id)
        if r.status == "synced" and tp.exists():
            card.add_widget(Image(source=str(tp), fit_mode="cover"))
        elif r.status != "synced":
            card.add_widget(MDIcon(
                icon="alert-circle-outline", halign="center",
                valign="center", font_size="48sp",
            ))
        else:
            card.add_widget(MDIcon(
                icon=_icon_for(r), halign="center", valign="center",
                font_size="48sp",
            ))
        card.add_widget(MDLabel(
            text=r.original_name, halign="center", shorten=True,
            shorten_from="right", font_style="Caption",
            size_hint_y=None, height=dp(20),
        ))
        row = BoxLayout(size_hint_y=None, height=dp(28))
        mb = (r.size_bytes or 0) / 1024**2
        row.add_widget(MDLabel(
            text=f"{mb:.1f} MB", font_style="Caption",
            theme_text_color="Secondary",
        ))
        row.add_widget(MDIconButton(
            icon="dots-vertical",
            on_release=lambda *_: self.file_menu(r),
        ))
        card.add_widget(row)
        return card

    def update_info(self):
        db = self.app.db
        if db is None:
            return
        n = sum(1 for r in db.list_files() if r.status == "synced")
        total_mb = db.total_synced_bytes() / 1024**2
        limit_gb = settings.MAX_UPLOAD_SIZE / 1024**3
        plan = (
            "Premium" if getattr(self.app.me, "premium", False) else "Standar"
        )
        self.info.text = (
            f"{n} file  •  {total_mb:.1f} MB  •  "
            f"{plan} (maks {limit_gb:.1f} GB/file)"
        )

    def _sorted(self, files):
        key, _, direction = self.sort_mode.partition("_")
        reverse = direction == "desc"
        if key == "name":
            files.sort(key=lambda r: r.original_name.lower(), reverse=reverse)
        elif key == "size":
            files.sort(key=lambda r: r.size_bytes or 0, reverse=reverse)
        else:
            files.sort(key=lambda r: r.uploaded_at or "", reverse=reverse)
        return files

    # ---- navigasi & toolbar ----

    def enter_folder(self, folder):
        self.folder_stack.append((folder.id, folder.name))
        self.folder_id = folder.id
        self.refresh()

    def go_up(self):
        if self.folder_stack:
            self.folder_stack.pop()
        self.folder_id = (
            self.folder_stack[-1][0] if self.folder_stack else None
        )
        self.refresh()

    def _toolbar_actions(self):
        view_icon = (
            "view-grid-outline" if self.view_mode == "list"
            else "format-list-bulleted"
        )
        return [
            [view_icon, lambda *_: self.toggle_view()],
            ["sort", lambda *_: self.sort_dialog()],
            ["refresh", lambda *_: self.app.run_task(self.sync())],
            ["dots-vertical", lambda *_: self.overflow_menu()],
        ]

    def toggle_view(self):
        self.view_mode = "grid" if self.view_mode == "list" else "list"
        self.toolbar.right_action_items = self._toolbar_actions()
        self.refresh()

    def overflow_menu(self):
        self._menu("TeleDrive", [
            ("information-outline", "Tentang", self.about_dialog),
        ])

    def about_dialog(self):
        version = androidio.app_version() or __version__
        self._dialog = MDDialog(
            title="TeleDrive",
            text=(
                f"Versi terpasang: {version}\n"
                "Paket: com.s4rt4.teledrive\n\n"
                "Penyimpanan pribadi Anda di Telegram."
            ),
            buttons=[MDFlatButton(
                text="TUTUP",
                on_release=lambda *_: self._dialog.dismiss(),
            )],
        )
        self._dialog.open()

    def sort_dialog(self):
        self._menu("Urutkan", [
            (icon, label, lambda m=mode: self._set_sort(m))
            for mode, icon, label in SORT_OPTIONS
        ])

    def _set_sort(self, mode):
        self.sort_mode = mode
        self.refresh()

    def fab_menu(self):
        self._menu("TeleDrive", [
            ("upload", "Unggah file", self.pick_upload),
            ("folder-plus", "Folder baru", self.new_folder_dialog),
        ])

    # ---- sync & thumbnail ----

    async def sync(self):
        if self.app.client is None:
            return
        self.info.text = "Sinkronisasi…"

        def prog(n):
            if n % 25 == 0:
                self.info.text = f"Sinkronisasi… {n} message dipindai"

        try:
            report = await sync_channel(
                self.app.client, self.app.channel, self.app.db, progress=prog
            )
        except Exception as e:
            self.info.text = ""
            toast(f"Sync gagal: {type(e).__name__}: {e}")
            return
        self.refresh()
        self.update_info()
        if report.added or report.restored or report.missing:
            toast(report.summary())
        await self.load_thumbs()

    async def load_thumbs(self):
        recs = [
            r for r in self.app.db.list_files()
            if r.status == "synced"
            and (r.mime_type or "").lower().startswith(("image/", "video/"))
        ]
        try:
            if await fetch_thumbs(self.app.client, self.app.channel, recs):
                self.refresh()
        except Exception:
            pass  # thumbnail gagal bukan alasan mengganggu UI

    # ---- panel transfer ----

    def _panel_show(self, title):
        self.panel_title.text = title
        self.panel_bar.max = 100
        self.panel_bar.value = 0
        self.panel_status.text = ""
        self.panel.height = dp(96)
        self.panel.opacity = 1

    def _panel_hide(self):
        self.panel.height = 0
        self.panel.opacity = 0

    def _progress(self, cur, total):
        self.panel_bar.max = total or 1
        self.panel_bar.value = cur
        self.panel_status.text = (
            f"{cur / 1024**2:.1f} / {(total or 0) / 1024**2:.1f} MB"
        )

    # ---- pratinjau & download ----

    async def _fetch_cached(self, rec) -> Path:
        """Tarik file penuh ke preview cache (sekali — verifikasi sha)."""
        async with self._transfer_lock:
            self._panel_show(f"Mengunduh {rec.original_name}…")
            try:
                return await previewer.fetch(
                    self.app.client, self.app.channel, rec, self._progress
                )
            except IntegrityError:
                self.app.db.set_status(rec.id, "corrupt")
                self.refresh()
                raise
            finally:
                self._panel_hide()

    async def preview(self, rec: FileRecord):
        if self.app.client is None:
            return
        if rec.status != "synced":
            toast(f"File berstatus '{rec.status}' — tidak bisa dibuka")
            return
        kind = previewer.kind_for(rec)
        if kind in ("image", "text", "markdown"):
            path = await self._fetch_cached(rec)
            previewer.prune_cache()
            self.app.preview.show(
                rec, "image" if kind == "image" else "text", path
            )
            self.app.sm.current = "preview"
        else:
            # video/audio/pdf/docx: serahkan ke app eksternal (6.3 plan)
            self._menu(rec.original_name, [
                ("download", "Unduh ke Download",
                 lambda: self.app.run_task(self.download_public(rec))),
                ("open-in-new", "Unduh & buka dengan app lain",
                 lambda: self.app.run_task(
                     self.download_public(rec, open_after=True)
                 )),
            ])

    async def download_public(self, rec: FileRecord, open_after=False):
        src = await self._fetch_cached(rec)
        label, uri = androidio.save_to_downloads(
            src, rec.original_name, rec.mime_type
        )
        previewer.prune_cache()
        if label is None:  # dev desktop
            toast(f"Tersimpan di {src}")
            return
        if open_after and not androidio.view_uri(uri, rec.mime_type):
            toast(f"Tidak ada app yang bisa membuka — tersimpan di {label}")
        else:
            toast(f"Tersimpan di {label}")

    # ---- upload ----

    def pick_upload(self):
        if not androidio.ANDROID:
            toast("Upload hanya tersedia di Android")
            return
        cache = settings.DATA_DIR / "upload_cache"
        androidio.pick_files(cache, self._queue_picked)

    def _queue_picked(self, paths):
        if not paths:
            return
        for p in paths:
            self.app.db.queue_add(str(p), self.folder_id)
        toast(f"{len(paths)} file masuk antrean upload")
        self.app.run_task(self.process_queue())

    async def process_queue(self):
        """Proses upload_queue sekuensial; queue persist antar sesi."""
        if self._uploading or self.app.client is None:
            return
        self._uploading = True
        db = self.app.db
        try:
            while (item := db.queue_next()) is not None:
                p = Path(item.local_path)
                if not p.exists():
                    db.queue_remove(item.id)
                    continue
                async with self._transfer_lock:
                    self._panel_show(f"Mengunggah {p.name}…")
                    try:
                        res = await upload_file(
                            self.app.client, self.app.channel, p,
                            self._progress, db.find_by_sha256,
                            caption=captions.build(
                                p.name, db.folder_path(item.folder_id)
                            ),
                        )
                    except FileTooLargeError as e:
                        toast(str(e))
                        db.queue_remove(item.id)
                        continue
                    except Exception as e:
                        # biarkan di queue — dicoba lagi saat app dibuka
                        toast(f"Upload gagal: {type(e).__name__}: {e}")
                        break
                    finally:
                        self._panel_hide()
                db.save_upload(res, folder_id=item.folder_id)
                db.queue_remove(item.id)
                if res.deduped:
                    toast(f"{p.name}: file identik sudah ada (dedup)")
                if p.parent.name == "upload_cache":
                    p.unlink(missing_ok=True)  # salinan SAF, sudah tak perlu
                self.refresh()
                self.update_info()
        finally:
            self._uploading = False
            self.app.run_task(self.load_thumbs())

    # ---- aksi file & folder ----

    def file_menu(self, rec: FileRecord):
        if rec.status != "synced":
            self._menu(rec.original_name, [
                ("delete", "Hapus dari daftar",
                 lambda: self.confirm_delete(rec)),
            ])
            return
        self._menu(rec.original_name, [
            ("eye", "Pratinjau",
             lambda: self.app.run_task(self.preview(rec))),
            ("download", "Unduh ke Download",
             lambda: self.app.run_task(self.download_public(rec))),
            ("open-in-new", "Unduh & buka dengan app lain",
             lambda: self.app.run_task(
                 self.download_public(rec, open_after=True)
             )),
            ("pencil", "Ganti nama", lambda: self.rename_dialog(rec)),
            ("folder-move", "Pindahkan", lambda: self.move_dialog(rec)),
            ("delete", "Hapus", lambda: self.confirm_delete(rec)),
        ])

    def rename_dialog(self, rec):
        self._text_dialog(
            "Ganti nama", rec.original_name, "Nama baru",
            lambda v: self.app.run_task(self._rename(rec, v)),
        )

    async def _rename(self, rec, new_name):
        await rename_file(
            self.app.client, self.app.channel, self.app.db, rec, new_name
        )
        self.refresh()
        toast("Nama diperbarui")

    def move_dialog(self, rec):
        options = [("home", "(Root)",
                    lambda: self.app.run_task(self._move(rec, None)))]
        for f in self.app.db.list_all_folders():
            options.append((
                "folder", f.name,
                lambda fid=f.id: self.app.run_task(self._move(rec, fid)),
            ))
        self._menu("Pindahkan ke…", options)

    async def _move(self, rec, folder_id):
        # tulis juga ke caption — perangkat lain ikut memindahkan saat sync
        await move_file(
            self.app.client, self.app.channel, self.app.db, rec, folder_id
        )
        self.refresh()
        toast("Dipindahkan")

    def confirm_delete(self, rec):
        self._confirm(
            f"Hapus {rec.original_name}?",
            "File dihapus dari channel Telegram. Tidak bisa dibatalkan.",
            lambda: self.app.run_task(self._delete(rec)),
        )

    async def _delete(self, rec):
        await delete_file(self.app.client, self.app.channel, self.app.db, rec)
        self.refresh()
        self.update_info()
        toast("Dihapus")

    def new_folder_dialog(self):
        self._text_dialog(
            "Folder baru", "", "Nama folder", self._create_folder
        )

    def _create_folder(self, name):
        try:
            self.app.db.create_folder(name, self.folder_id)
        except ValueError as e:
            toast(str(e))
            return
        self.refresh()

    def folder_menu(self, folder):
        self._menu(folder.name, [
            ("pencil", "Ganti nama",
             lambda: self._text_dialog(
                 "Ganti nama folder", folder.name, "Nama baru",
                 lambda v: self._rename_folder(folder, v),
             )),
            ("delete", "Hapus folder", lambda: self._delete_folder(folder)),
        ])

    def _rename_folder(self, folder, new_name):
        try:
            self.app.db.rename_folder(folder.id, new_name)
        except ValueError as e:
            toast(str(e))
            return
        self.refresh()

    def _delete_folder(self, folder):
        if not self.app.db.folder_is_empty(folder.id):
            toast("Folder tidak kosong — kosongkan dulu")
            return
        self.app.db.delete_folder(folder.id)
        self.refresh()

    # ---- dialog util ----

    def _menu(self, title, options):
        """Dialog daftar aksi: options = [(icon, label, callback)]."""
        items = []
        for icon, label, cb in options:
            it = OneLineIconListItem(
                text=label,
                on_release=lambda w, c=cb: (self._dialog.dismiss(), c()),
            )
            it.add_widget(IconLeftWidget(icon=icon))
            items.append(it)
        self._dialog = MDDialog(title=title, type="simple", items=items)
        self._dialog.open()

    def _text_dialog(self, title, initial, hint, on_ok):
        field = MDTextField(text=initial, hint_text=hint)
        box = BoxLayout(
            size_hint_y=None, height=dp(80), padding=[0, dp(12), 0, 0]
        )
        box.add_widget(field)

        def ok(*_):
            value = field.text.strip()
            self._dialog.dismiss()
            if value:
                on_ok(value)

        self._dialog = MDDialog(
            title=title, type="custom", content_cls=box,
            buttons=[
                MDFlatButton(
                    text="BATAL",
                    on_release=lambda *_: self._dialog.dismiss(),
                ),
                MDRaisedButton(text="OK", on_release=ok),
            ],
        )
        self._dialog.open()

    def _confirm(self, title, text, on_yes):
        def yes(*_):
            self._dialog.dismiss()
            on_yes()

        self._dialog = MDDialog(
            title=title, text=text,
            buttons=[
                MDFlatButton(
                    text="BATAL",
                    on_release=lambda *_: self._dialog.dismiss(),
                ),
                MDRaisedButton(text="HAPUS", on_release=yes),
            ],
        )
        self._dialog.open()


class PreviewScreen(MDScreen):
    """Pratinjau in-app: gambar (Image) atau teks (label scrollable)."""

    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        col = BoxLayout(orientation="vertical")
        self.toolbar = MDTopAppBar(
            title="", elevation=0,
            left_action_items=[
                ["arrow-left",
                 lambda *_: setattr(app.sm, "current", "browser")]
            ],
        )
        col.add_widget(self.toolbar)
        self.holder = BoxLayout()
        col.add_widget(self.holder)
        self.add_widget(col)

    def show(self, rec: FileRecord, kind: str, path):
        self.toolbar.title = rec.original_name
        self.holder.clear_widgets()
        if kind == "image":
            self.holder.add_widget(
                Image(source=str(path), fit_mode="contain")
            )
            return
        label = MDLabel(
            text=previewer.read_text(Path(path)),
            size_hint_y=None, padding=[dp(16), dp(16)],
        )
        label.bind(
            texture_size=lambda w, s: setattr(w, "height", s[1] + dp(32))
        )
        label.bind(
            width=lambda w, v: setattr(w, "text_size", (v - dp(32), None))
        )
        sc = ScrollView()
        sc.add_widget(label)
        self.holder.add_widget(sc)
