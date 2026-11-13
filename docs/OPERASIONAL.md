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
- Semua endpoint pantauan & stream wajib sesi login — **kecuali** bila `PUBLIC_VIEW=1`
  (mode viewer publik, lihat bagian di bawah); `/api/docs` mati di mode produksi.
- Panel admin (`/admin*`) **selalu** wajib login, apa pun nilai `PUBLIC_VIEW`.
- Cookie sesi `HttpOnly` + `SameSite=Lax` (CSRF antar-situs tertahan).
- Rate limit login 5/5 menit per IP; seluruh aksi admin tercatat di `access_logs`.
- `SECRET_KEY` disimpan di `.env` (perm 600), bukan di repo.

### 8.1 Viewer publik (tanpa password)

Master bisa membuka halaman pantauan untuk umum tanpa login:

```bash
cd ~/cctv-pintar && python3 scripts/set_env.py PUBLIC_VIEW=1 && sudo systemctl restart cctv-pintar
```

Yang terjadi: `/`, `/api/cameras/status`, `/stream/...`, dan `/api/snapshot/...` bisa diakses
tanpa sesi. **Jadwal kamera tetap dipaksa** — kamera `scheduled` yang sedang tertutup tetap
`403` (dan `stream_denied` tercatat di log), jadi viewer publik tidak bisa menembus jadwal.
Override admin dan seluruh panel admin tetap butuh login admin.

Risiko: siapa pun yang tahu URL `cctv.ainulhakim.com` bisa menonton kamera ber-mode `public`
(24 jam). Kalau ingin menutup lagi: `PUBLIC_VIEW=0` + restart, atau ubah mode kamera ke
`scheduled` lewat panel admin.

`COOKIE_SECURE=0` sengaja dipakai supaya sesi tetap jalan lewat `http://` tailnet. Kalau akses
hanya lewat HTTPS Cloudflare, set `COOKIE_SECURE=1` lalu restart aplikasi.

## 9. Rekaman CCTV (aktif sejak 13 Nov 2026)

Rekaman 24 jam **tanpa transcode** (`-c copy` HEVC sub-stream), jadi CPU hampir nol.
Dua lapis pengaman kuota:

- **Hard limit filesystem**: volume ext4 on loopback `/srv/cctv-rec/rec.img` = **30 GB**
  (terdaftar di `/etc/fstab`, opsi `loop,noatime,nofail`). Recorder secara fisik tidak bisa
  menulis melebihi 30 GB, apa pun bug-nya.
- **Recycler aplikasi**: `cctv-recycle.timer` tiap 5 menit menghapus segmen **terlama** saat
  pemakaian > 90% kuota (`RECORD_HIGH_WATERMARK=0.9` → 27 GB). Berkas < 120 detik tidak
  pernah dihapus.

Konfigurasi:

```
/etc/cctv-record/quota.env     RECORD_QUOTA_GB=30 RECORD_HIGH_WATERMARK=0.9 RECORD_RETENTION_DAYS=0
/etc/cctv-record/utara.env     CAM_URL=rtsp://...192.168.1.2:554/1/2
/etc/cctv-record/selatan.env   CAM_URL=rtsp://...192.168.1.223:554/1/2
/etc/cctv-record/balai.env     CAM_URL=rtsp://...192.168.1.222:554/...stream=1
```

Segmen: **MPEG-TS** (`SEGMENT_FORMAT=ts`, default) **5 menit/berkas**, nama
`/srv/cctv-rec/<kamera>/YYYYmmdd-HHMMSS_sub.ts`. TS dipilih karena tidak butuh *moov atom*:
potongan yang terpotong reboot/kamera-putus tetap bisa diputar. (Mode `mp4` masih tersedia via
`SEGMENT_FORMAT=mp4`, tapi segmen terakhir yang belum ditutup akan korup.)

Segmen 5 menit dipilih supaya: (a) tinjauan cepat — tidak perlu menunggu konversi 1 jam,
(b) konversi H.264 selesai dalam ±10 detik, (c) kehilangan data saat crash maksimal 5 menit.

### 9.1 Menonton rekaman (menu **Rekaman**)

`/admin/recordings` (wajib login admin): filter kamera + tanggal, lalu **Putar** atau
**Unduh asli**. Rekaman kamera berformat **HEVC (H.265)** — browser tidak bisa memutarnya,
jadi aplikasi mengonversi segmen ke **H.264** sekali saat pertama dibuka (asinkron, satu
antrean, ±10 detik per segmen 5 menit), lalu menyimpannya di `/srv/cctv-rec/.cache-h264/`
(batas 4 GB, dibersihkan otomatis oleh recycler). Buka ulang = instan. Tombol
**Unduh asli** memberi berkas `.ts` HEVC untuk diputar di VLC.

Operasi harian:

```bash
systemctl list-units 'cctv-record@*' --no-pager        # status per kamera
systemctl restart cctv-record@utara                     # restart 1 kamera
journalctl -u cctv-record@utara -n 50 --no-pager        # log (perlu sudo)
du -sh /srv/cctv-rec/*/ ; df -h /srv/cctv-rec            # pemakaian nyata
python3 ~/cctv-pintar/scripts/quota_recycle.py --root /srv/cctv-rec --quota-gb 30 --dry-run
sudo bash ~/cctv-pintar/scripts/record_setup_volume.sh --size-gb 60 --grow   # perbesar kuota
```

Tambah kamera ke rekaman: buat `/etc/cctv-record/<nama>.env` berisi `CAM_URL=...`, lalu
`sudo systemctl enable --now cctv-record@<nama>`.

Rekaman kamera kantor (`camkantor`) **tidak** diaktifkan karena bergantung pada relay MacBook
(`rtsp://127.0.0.1:8554/camkantor`); aktifkan dengan perintah di atas bila relay selalu hidup.

Catatan: kuota 30 GB hanya menampung sekitar **2 hari** rekaman 3 kamera (laju terukur
±14 GB/hari, didominasi kamera selatan ±10 GB/hari). Untuk arsip lebih panjang: perkecil
bitrate sub-stream kamera selatan, kurangi jumlah kamera, atau tambah disk eksternal.

