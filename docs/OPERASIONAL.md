# CCTV Pintar — Panduan Operasional

Semua perintah di dokumen ini dijalankan **di server rumah** (`ainul@<IP-TAILNET>`, password <PASSWORD-SSH-DIROTASI>) kecuali disebut lain.

## 1. Ringkasan layanan

| Layanan | Perintah | Keterangan |
|---|---|---|
| MediaMTX | `systemctl status mediamtx` | RTSP → HLS, transcode on-demand |
| Aplikasi | `systemctl status cctv-pintar` | uvicorn di `<IP-TAILNET>:8090` |
| Tunnel | `systemctl status cloudflared-cctv` | `cctv.ainulhakim.com` |

Akses:

- Publik: `https://cctv.ainulhakim.com`
- Tailnet: `http://<IP-TAILNET>:8090`
- Kesehatan: `GET /healthz` → `{"ok": true}`

Direktori proyek: `/home/ainul/cctv-pintar` · database: `data/cctv.db` · konfigurasi: `.env` (perm 600).

## 2. Tambah kamera baru

Prasyarat: kamera sudah bisa diakses server rumah (RTSP) dan sudah ditambahkan sebagai path di
`/opt/mediamtx/mediamtx.yml` (kredensial kamera **hanya** ada di file itu).

1. Buka `https://cctv.ainulhakim.com/admin/cameras`.
2. Isi **slug** (huruf kecil, mis. `garasi`), **nama**, **lokasi**, **stream key**
   (= nama path di MediaMTX, mis. `garasi`), urutan, centang Aktif → *Tambahkan*.
3. Kamera baru otomatis punya policy **publik 24 jam**. Atur di **Jadwal Akses** kalau perlu dibatasi.
4. Uji: buka halaman pantauan, kartu kamera harus muncul dan berbunyi `LIVE`.

Kalau kamera di MediaMTX belum hidup, kartu tetap muncul tapi video kosong. Cek `Status MediaMTX`
di menu **Log & Status** (harus `siap`).

## 3. Atur jadwal akses

Menu **Jadwal Akses** → pilih kamera:

- **Publik 24 jam** — siapa pun yang sudah login bisa menonton kapan saja.
- **Terjadwal** — centang hari (Senin–Minggu) dan isi jam mulai–selesai.
  - Window boleh melewati tengah malam: `22:00–05:00` (dini hari ikut hari **sebelumnya**).
  - Jam mulai = jam selesai berarti **24 jam** pada hari terpilih.
  - Hari mengikuti zona waktu policy (default `Asia/Jakarta`).
- **Policy aktif** tidak dicentang = kamera tertutup total (walau mode publik).

Di luar jadwal, penonton melihat overlay **"Tertutup"** + waktu buka berikutnya, dan endpoint
stream/snapshot membalas **403** (tercatat di log).

### Override admin (buka kamera tertutup sementara)

Di halaman pantauan, admin melihat tombol **"Buka"** pada kartu yang berstatus TERTUTUP:

1. Masukkan **password akun admin yang sedang login** (bukan password admin lain).
2. Kalau benar, kamera itu terbuka untuk **30 menit** (ubah lewat `OVERRIDE_TTL` di `.env`),
   kartu menampilkan badge **OVERRIDE ADMIN** + jam berakhirnya.
3. Override berlaku **per kamera** dan hanya untuk akun tersebut — kamera lain tetap tertutup,
   dan user lain tetap ditolak.
4. Semua percobaan dicatat: `override_granted`, `override_failed`, `override_blocked`
   (maksimal **5 percobaan salah / 5 menit** per user+IP → balasan `429`).
5. Logout otomatis mencabut override.

Catatan: setelah password admin diganti lewat menu **Pengguna → Reset password**, nilai
`ADMIN_PASSWORD` di `.env` menjadi **basi** — itu normal, karena `.env` hanya dipakai sekali
saat seeding (`scripts/seed.py`) dan oleh `scripts/smoke.py`. Untuk memulihkan akses pakai
`scripts/set_password.py` (lihat bagian Troubleshooting).

## 4. Kelola pengguna

Menu **Pengguna**:

- **Tambah**: username, nama, role (`admin` = bisa kelola semua, `viewer` = hanya menonton),
  password minimal 8 karakter.
- **Reset password**: buka *Reset password* pada baris user.
- **Aktif/Nonaktif**: menonaktifkan langsung memutus akses login user tersebut.
- **Hapus**: tidak bisa menghapus akun sendiri atau admin aktif terakhir.

Login dibatasi **5 percobaan gagal per 5 menit per IP** (balasan `429`).

## 5. Lihat log & status

Menu **Log & Status** menampilkan:

- log akses: `login_ok`, `login_failed`, `login_blocked`, `stream_denied`, `snapshot_denied`,
  serta aksi admin (`camera_*`, `policy_update`, `user_*`) — lengkap dengan IP klien asli;
- filter per aksi / kamera / jumlah baris;
- status path MediaMTX (siap/belum, codec, jumlah penonton);
- pemakaian disk server rumah.

Waktu log disimpan **UTC**.

## 6. Operasi rutin

```bash
# restart aplikasi (setelah ubah .env)
sudo systemctl restart cctv-pintar && systemctl is-active cctv-pintar

# lihat log aplikasi / tunnel
journalctl -u cctv-pintar -n 100 --no-pager
journalctl -u cloudflared-cctv -n 50 --no-pager

# ubah nilai konfigurasi tanpa editor
cd ~/cctv-pintar && .venv/bin/python scripts/set_env.py KEY=VALUE

# jalankan test di server (harus hijau sebelum/sesudah perubahan)
cd ~/cctv-pintar && .venv/bin/python -m pytest -q
```

**Deploy dari workspace (Hermes) — alur git (sejak 19 Okt 2026)**:

Folder `/home/ainul/cctv-pintar` di rumah sudah bukan lagi copy rsync, melainkan **clone git**
(read-only lewat HTTPS publik `https://github.com/ainulhakim/cctv-pintar.git`). Jadi sumber
kebenaran tunggal = repo GitHub, dan `git pull` bisa dipakai kapan saja.

```bash
cd /home/ubuntu/cctv-pintar
RSSH_PASS=<PASSWORD-SSH> ./scripts/deploy_git.sh              # push ke GitHub -> rumah pull + restart
RSSH_PASS=<PASSWORD-SSH> RUN_TESTS=1 ./scripts/deploy_git.sh  # sekalian pytest + smoke di rumah
```

Dari sisi rumah (manual / inspeksi):

```bash
cd ~/cctv-pintar
SUDO_PASS=<PASSWORD-SSH> bash scripts/pull_deploy.sh          # git pull + restart + cek /healthz
git log --oneline -1 && git status --short              # pastikan sama dengan GitHub
```

`scripts/pull_deploy.sh` idempotent: kalau `.git` belum ada, folder otomatis dijadikan clone
(`.env`, `.venv`, `data/`, `deploy/mediamtx.yml` **tidak** tersentuh karena di-gitignore).
`scripts/deploy.sh` (rsync) dipertahankan hanya sebagai cadangan/bootstrap.

## 7. Troubleshooting

| Gejala | Cek / tindakan |
|---|---|
| Video tidak muncul, kartu `LIVE` | Cek `Status MediaMTX`; pastikan path `ready: true` |
| Kartu menampilkan "Tertutup" | Memang di luar jadwal — cek menu Jadwal Akses |
| `502 MediaMTX tidak dapat dihubungi` | `systemctl status mediamtx`, lalu restart |
| Snapshot gagal (`503`) | Kamera mungkin offline; uji `ffmpeg -rtsp_transport tcp -i rtsp://127.0.0.1:8554/<key> -frames:v 1 /tmp/a.jpg` |
| Halaman tidak terbuka dari internet | `systemctl status cloudflared-cctv`, `journalctl -u cloudflared-cctv` |
| Lupa password admin | `cd ~/cctv-pintar && NEW_PASSWORD='rahasia-baru' .venv/bin/python scripts/set_password.py admin` (di server rumah). `scripts/seed.py` **tidak** me-reset user yang sudah ada |
| Perlu admin baru darurat | `cd ~/cctv-pintar && NEW_PASSWORD='rahasia-baru' .venv/bin/python scripts/set_password.py admin2 --create-admin` |
| Kamera offline | Cek Wi-Fi rumah & daya kamera; `ping <IP-KAMERA-1>` dari server rumah |
| Laptop mendadak mati / stream hilang | Cek daya: `upower -i /org/freedesktop/UPower/devices/battery_BAT0` → `state` harus *charging*, `cat /sys/class/power_supply/AC/online` harus `1` |

Catatan: laptop server rumah wajib tetap menyala dan **tidak boleh sleep** (sudah dimatikan
suspend/hibernate-nya di Fase 1). **Wajib selalu tersambung charger** — baterai ThinkPad ini sudah
tua (kapasitas penuh hanya ~15,5 Wh dari desain 47,5 Wh ≈ **33% kesehatan**), jadi tanpa adaptor
server hanya bertahan sekitar **1–3 jam**.

## 8. Keamanan (yang sudah berlaku)

- Kredensial kamera **hanya** di `/opt/mediamtx/mediamtx.yml`; aplikasi & browser tidak pernah menerimanya.
- MediaMTX (RTSP/HLS/API) hanya listen di `127.0.0.1`.
- Semua endpoint pantauan & stream wajib sesi login; `/api/docs` mati di mode produksi.
- Cookie sesi `HttpOnly` + `SameSite=Lax` (CSRF antar-situs tertahan).
- Rate limit login 5/5 menit per IP; seluruh aksi admin tercatat di `access_logs`.
- `SECRET_KEY` disimpan di `.env` (perm 600), bukan di repo.

`COOKIE_SECURE=0` sengaja dipakai supaya sesi tetap jalan lewat `http://` tailnet. Kalau akses
hanya lewat HTTPS Cloudflare, set `COOKIE_SECURE=1` lalu restart aplikasi.
