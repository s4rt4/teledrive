<p align="center">
  <img src="teledrive.svg" width="96" alt="TeleDrive">
</p>

<h1 align="center">TeleDrive</h1>

<p align="center">Personal cloud drive di atas Telegram — UI ala Google Drive, penyimpanan tanpa batas di channel privat milikmu sendiri.</p>

---

## Fitur

- Upload / download dengan progress per file, antrian persist, dedup sha256, dan verifikasi integritas
- Grid thumbnail & list berkolom, folder virtual, search, filter (jenis/tanggal/ukuran), sort
- Pratinjau in-app: gambar, video, audio, PDF, teks, markdown, docx
- Drag & drop file maupun folder (struktur ikut terbawa)
- Auto-backup folder lokal, sinkronisasi/recovery dari channel, kirim file ke chat Telegram
- Dark mode, system tray, deteksi Telegram Premium (limit upload naik ke 3,5 GB)

## Menjalankan

```bash
pip install -r requirements.txt
copy .env.example .env   # isi TELEGRAM_API_ID & TELEGRAM_API_HASH dari https://my.telegram.org/apps
python main.py
```

Login pertama memakai OTP Telegram; sesi berikutnya masuk otomatis. Semua file disimpan di channel privat `TeleDrive_Storage` yang dibuat otomatis di akunmu.

> File `.session` dan database lokal disimpan di luar folder project (`%LOCALAPPDATA%\TeleDrive`) dan tidak pernah masuk repo.
