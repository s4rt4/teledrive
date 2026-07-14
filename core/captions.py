"""Format caption message di channel storage — kontrak lintas perangkat.

Caption adalah satu-satunya metadata yang ikut tersimpan di Telegram,
jadi dipakai untuk recovery DB (core.sync) dan propagasi antar
perangkat (desktop <-> Android):

    <nama file>
    dir: <path/folder>          <- opsional

- Baris pertama = nama file (kontrak rename yang sudah ada sejak awal).
- Baris "dir: " = folder virtual, separator "/". "dir: /" = eksplisit
  root (dipakai saat file dipindah KE root, supaya perangkat lain ikut
  memindahkan). Tanpa baris dir = tidak ada info folder (file lama /
  belum pernah dipindah) — sync TIDAK menyentuh folder lokal.

Keterbatasan: nama folder yang mengandung "/" akan terpecah jadi
sub-folder saat di-recover di perangkat lain.
"""

DIR_PREFIX = "dir: "
ROOT = "/"


def build(name: str, folder_path: str | None = None) -> str:
    """Susun caption. folder_path None = tanpa baris dir;
    ROOT ("/") = penanda eksplisit root."""
    if not folder_path:
        return name
    return f"{name}\n{DIR_PREFIX}{folder_path}"


def parse(text: str) -> tuple[str | None, str | None]:
    """Return (nama, dir_path). Keduanya None kalau tidak ada di caption.
    dir_path ROOT berarti eksplisit root."""
    lines = (text or "").strip().splitlines()
    if not lines or not lines[0].strip():
        return None, None
    name = lines[0].strip()[:255]
    dir_path = None
    for line in lines[1:]:
        line = line.strip()
        if line.startswith(DIR_PREFIX):
            dir_path = line[len(DIR_PREFIX):].strip() or None
            break
    return name, dir_path
