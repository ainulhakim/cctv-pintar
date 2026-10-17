# CCTV Portal — Implementation Plan

> **Untuk Ali (Hermes):** kerjakan bertahap, commit tiap task, verifikasi tiap langkah.

**Goal:** Aplikasi web pemantauan CCTV dengan autentikasi sendiri (bukan kredensial kamera), kontrol akses berbasis jadwal per kamera, dapat diakses publik via `cctv.ainulhakim.com`.

**Architecture:**
- **SEMUA di server `rumah`** (<IP-TAILNET>) — keputusan Master: konsep ini prototype, jadi cukup 1 server. Server rumah juga yang satu-satunya bisa menjangkau kamera di LAN (<LAN-RUMAH>).
- **MediaMTX** (single binary, tanpa transcoding) menarik RTSP dari kamera → menyajikan **HLS** ke app.
- **Aplikasi FastAPI** (auth, jadwal, proxy HLS) listen di `127.0.0.1:8090`.
- **cloudflared** tunnel **baru** khusus (`cctv-pintar`) di server rumah → `cctv.ainulhakim.com`.
- Browser **tidak pernah** menerima kredensial kamera. Semua RTSP ditangani server-side; HLS hanya keluar lewat endpoint ber-autentikasi.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy 2.0 / SQLite / Jinja2 + Tailwind (CDN) + hls.js / uvicorn / bcrypt / MediaMTX / systemd / Cloudflare Tunnel

**Topologi:**
```
Kamera Tiandy (<IP-KAMERA-1> / .223)  [LAN rumah]
      │ RTSP
      ▼
MediaMTX @rumah 127.0.0.1:8554 → HLS 127.0.0.1:8888
      │
      ▼
FastAPI cctv-pintar @rumah 127.0.0.1:8090  ← auth + cek jadwal + proxy HLS
      │
      ▼
cloudflared tunnel cctv-pintar → cctv.ainulhakim.com
```

**Repo & backup:** kode dikembangkan di `/home/ubuntu/cctv-pintar` (workspace Hermes) + di-deploy ke rumah via rsync. Setiap selesai deploy → **push ke GitHub** (`cctv-pintar`), autentikasi SSH (akun `ainulhakim`).

---

## Fase 0 — Persiapan & verifikasi lingkungan

### Task 0.1: Cek prasyarat media
- **Files:** —
- Jalankan: `ffmpeg -version`, `python3 --version` di rumah; cek sub-stream kamera.
- Verifikasi: dapat 2 stream **sub-stream** (resolusi rendah) untuk live view, main-stream untuk rekaman.
- Perintah uji sub-stream:
  ```bash
  ffprobe -v error -rtsp_transport tcp -select_streams v:0 \
    -show_entries stream=codec_name,width,height -of csv=p=0 \
    "rtsp://cam:<PASSWORD-KAMERA>@<IP-KAMERA-1>:554/Streaming/Channels/102"
  ```
- Expected: `hevc,704,576` (atau resolusi sub yang lebih kecil)

### Task 0.2: Buat struktur proyek
- **Create:** `/home/ubuntu/cctv-portal/` dengan `app/`, `app/routers/`, `app/templates/`, `app/static/`, `tests/`, `docs/plans/`
- **Create:** `/home/ubuntu/cctv-portal/README.md` (arsitektur + cara deploy)

---

## Fase 1 — Blokir sleep di server rumah (WAJIB sebelum apa pun)

> Server rumah adalah laptop. Kalau sleep, CCTV mati. Ini prasyarat "akses 24 jam".

### Task 1.1: Matikan suspend/hibernate
- **Modify (rumah):** `/etc/systemd/logind.conf` → `HandleLidSwitch=ignore`, `HandleSuspendKey=ignore`
- **Modify (rumah):** `/etc/systemd/sleep.conf` → `AllowSuspend=no`, `AllowHibernation=no`
- Verifikasi: `systemctl restart systemd-logind`, lalu `systemd-inhibit --list`
- **Test:** tutup lid (minta Master) → `uptime` tetap jalan

### Task 1.2: Pastikan Wi-Fi tidak dimatikan saat idle
- **Modify (rumah):** NetworkManager → `wifi.powersave = 2` (off) via `/etc/NetworkManager/conf.d/wifi-powersave-off.conf`
- Verifikasi: `iw dev wlp3s0 get power_save` → `Power save: off`

### Task 1.3: Watchdog kamera
- **Create (rumah):** `/usr/local/bin/cctv-check.sh` — ping <IP-KAMERA-1> & .223, catat ke log
- **Create (rumah):** cron `*/5 * * * *` menjalankan script
- Verifikasi: log bertambah; kalau kamera offline tercatat timestamp-nya

---

## Fase 2 — MediaMTX sebagai relay RTSP/HLS di rumah

### Task 2.1: Install MediaMTX
- **Create (rumah):** `/opt/mediamtx/mediamtx` (binary dari GitHub release, `linux_amd64`)
- **Create (rumah):** `/opt/mediamtx/mediamtx.yml`
- Konfigurasi kunci:
  ```yaml
  logLevel: info
  rtspAddress: 127.0.0.1:8554        # hanya lokal, tidak diekspos
  hlsAddress: <IP-TAILNET>:8888    # HANYA Tailscale → app di Hermes
  hlsVariant: lowLatency
  hlsSegmentCount: 7
  hlsSegmentDuration: 1s
  api: yes
  apiAddress: 127.0.0.1:9997
  paths:
    utara:
      source: rtsp://cam:<PASSWORD-KAMERA>@<IP-KAMERA-1>:554/Streaming/Channels/102
      sourceOnDemand: yes
    selatan:
      source: rtsp://cam:<PASSWORD-KAMERA>@<IP-KAMERA-2>:554/Streaming/Channels/102
      sourceOnDemand: yes
  ```
- Verifikasi: `./mediamtx` jalan tanpa error, `curl http://<IP-TAILNET>:8888/utara/index.m3u8` dari Hermes mengembalikan playlist

### Task 2.2: systemd service MediaMTX
- **Create (rumah):** `/etc/systemd/system/mediamtx.service` (User=ainul, Restart=always, After=network-online.target)
- Verifikasi: `systemctl enable --now mediamtx` → `systemctl is-active mediamtx` = `active`

### Task 2.3: Snapshot on-demand
- **Create (rumah):** `/usr/local/bin/cctv-snapshot.sh <slug>` → `ffmpeg -frames:v 1` dari RTSP → `/tmp/cctv/<slug>.jpg`
- Alternatif: pakai `api` MediaMTX `/v3/paths/get/<slug>` untuk status online.
- Verifikasi: file JPEG terupdate tiap dipanggil

---

## Fase 3 — Aplikasi FastAPI (inti)

### Task 3.1: Skeleton + config
- **Create:** `app/main.py` (FastAPI, mount static, include routers)
- **Create:** `app/config.py` (env: `DATABASE_URL`, `SECRET_KEY`, `MEDIAMTX_HLS_BASE=http://<IP-TAILNET>:8888`, `TZ=Asia/Jakarta`)
- **Create:** `requirements.txt` (fastapi, uvicorn[standard], sqlalchemy, passlib[bcrypt], itsdangerous, jinja2, httpx, python-multipart, pytest)
- Verifikasi: `uvicorn app.main:app` jalan, `curl localhost:8090/healthz` → `{"ok":true}`

### Task 3.2: Model & migrasi
- **Create:** `app/models.py`
  ```python
  class User(Base):        # id, username(uniq), password_hash, role(admin|viewer), active, created_at
  class Camera(Base):      # id, slug(uniq), name, location, stream_key, enabled, sort, created_at
  class AccessPolicy(Base):# id, camera_id(FK), mode(public|scheduled), days(JSON "0-6"),
                           #   start_time(Time), end_time(Time), timezone, active
  class AccessLog(Base):   # id, user_id, camera_id, action, ip, at
  ```
- **Catatan:** kredensial kamera **TIDAK** disimpan di app — sudah ada di MediaMTX (rumah). App hanya menyimpan `slug`/`stream_key`.
- Verifikasi: `Base.metadata.create_all()` membuat 4 tabel di SQLite

### Task 3.3: Util auth (bcrypt + session)
- **Create:** `app/security.py`
  - `hash_password(pw)` / `verify_password(pw, hash)` (bcrypt 4.2.1 pin untuk kompatibilitas passlib)
  - `sign_session(user_id)` / `read_session(token)` via `itsdangerous.URLSafeTimedSerializer`, max_age 12 jam
- **Test:** `tests/test_security.py` — hash != plaintext, verify benar/salah, token expired ditolak

### Task 3.4: Dependency "current_user" + guard role
- **Create:** `app/deps.py` — `get_current_user(request)` (baca cookie `session`, load user, tolak kalau tidak aktif), `require_admin(user)`
- **Test:** tanpa cookie → 401/redirect; cookie viewer mengakses admin route → 403

### Task 3.5: Halaman login/logout
- **Create:** `app/routers/auth_router.py` — `GET /login`, `POST /login`, `POST /logout`
- **Create:** `app/templates/login.html`
- Verifikasi: login dengan user seed → cookie ter-set → redirect ke `/`; password salah → pesan error

### Task 3.6: Seed admin pertama
- **Create:** `scripts/seed.py` — buat admin dari env `ADMIN_USER` / `ADMIN_PASSWORD` (hanya kalau belum ada user)
- Verifikasi: `python scripts/seed.py` → user admin muncul; jalankan kedua kali tidak menduplikasi

---

## Fase 4 — Logika jadwal (inti requirement #2)

### Task 4.1: Fungsi "apakah kamera terbuka sekarang"
- **Create:** `app/schedule.py`
  ```python
  def is_open(policy, now=None) -> bool:
      """mode=public → selalu True.
         mode=scheduled → cek hari (days) dan window start_time..end_time.
         Mendukung window melewati tengah malam (22:00–05:00)."""
  def next_open(policy, now=None) -> datetime | None
  ```
- **Test:** `tests/test_schedule.py` (WAJIB, ini logic paling rawan)
  - public → selalu True
  - di dalam window → True; di luar → False
  - window lewat tengah malam (22:00–05:00): jam 23:00 True, 02:00 True, 12:00 False
  - hari tidak termasuk → False
  - `next_open` mengembalikan waktu buka berikutnya yang benar
- Run: `pytest tests/test_schedule.py -v` → semua PASS

### Task 4.2: Penyimpanan hari + timezone
- **Create:** util `parse_days("1,2,3")` → set, dan konversi waktu ke `Asia/Jakarta` pakai `zoneinfo`
- **Test:** hari "0" = Minggu? → **tetapkan Senin=0 … Minggu=6** dan dokumentasikan di kode + UI

---

## Fase 5 — Halaman pantauan (viewer)

### Task 5.1: Grid kamera + gating
- **Create:** `app/routers/view.py` — `GET /` → daftar kamera yang `enabled` + status `is_open`
- **Create:** `app/templates/dashboard.html` — kartu per kamera:
  - kalau terbuka → `<video>` dengan hls.js memuat `/stream/{slug}/index.m3u8`
  - kalau tertutup → overlay "Tertutup — dibuka kembali pukul HH:MM (hari X)"
  - auto-refresh status tiap 30 detik (endpoint `/api/cameras/status`)
- Verifikasi: kamera mode public selalu main; kamera scheduled di luar window menampilkan overlay

### Task 5.2: Proxy HLS ber-autentikasi (PENTING untuk requirement #1)
- **Create:** `app/routers/stream.py`
  - `GET /stream/{slug}/{path:path}` → validasi: (a) sesi valid, (b) kamera enabled, (c) `is_open(policy)` — kalau tertutup → **403**
  - lalu proxy ke `MEDIAMTX_HLS_BASE/{stream_key}/{path}` via httpx, teruskan `Content-Type` + body
  - manifest `.m3u8` di-rewrite agar segmen tetap lewat app (bukan langsung ke MediaMTX)
- **Test:** `tests/test_stream_guard.py` — tanpa sesi → 401; di luar jadwal → 403; di dalam jadwal → 200 (mock httpx)
- Verifikasi: **curl langsung ke MediaMTX dari internet tidak mungkin** (hanya Tailscale); buka `cctv.ainulhakim.com/stream/...` tanpa login → tertolak

### Task 5.3: Snapshot / thumbnail
- **Create:** `GET /api/snapshot/{slug}` → proxy ke snapshot MediaMTX/ffmpeg, cache 5 detik, tetap lewat guard jadwal

---

## Fase 6 — Panel admin

### Task 6.1: CRUD kamera
- **Create:** `app/routers/admin_cameras.py` + `app/templates/admin/cameras.html`
- Field: slug, nama, lokasi, stream_key, enabled, urutan
- Verifikasi: tambah/ubah/nonaktifkan kamera dari UI tercermin di dashboard

### Task 6.2: CRUD jadwal akses (requirement #2)
- **Create:** `app/routers/admin_policies.py` + `app/templates/admin/policies.html`
- UI per kamera: pilih **mode**:
  - `public` → "Akses publik 24 jam" (tanpa batas waktu)
  - `scheduled` → centang hari + input `mulai`–`selesai` (time picker)
- Verifikasi: set Utara = public 24 jam, Selatan = scheduled 08:00–17:00 → dashboard berubah perilaku sesuai jam saat diuji

### Task 6.3: CRUD user
- **Create:** `app/routers/admin_users.py` + `app/templates/admin/users.html`
- Aksi: tambah user (role admin/viewer), reset password, aktif/nonaktifkan
- Verifikasi: user baru bisa login, viewer tidak bisa buka `/admin/*`

### Task 6.4: Log akses + status sistem
- **Create:** `app/routers/admin_logs.py` + template
- Tampilkan: percobaan akses ditolak (di luar jadwal), login gagal, status kamera (dari MediaMTX API), sisa disk rumah
- Verifikasi: membuka kamera tertutup menghasilkan baris log "denied"

---

## Fase 7 — Deployment & publikasi

### Task 7.1: systemd app di Hermes
- **Create:** `/home/ubuntu/.config/systemd/user/cctv-portal.service` (uvicorn, `127.0.0.1:8090`, Restart=always, EnvironmentFile)
- Verifikasi: `systemctl --user enable --now cctv-portal` → `curl 127.0.0.1:8090/healthz` OK

### Task 7.2: Cloudflare ingress
- **Modify:** `/home/ubuntu/.cloudflared/config.yml` → tambah sebelum catch-all:
  ```yaml
  - hostname: cctv.ainulhakim.com
    service: http://localhost:8090
  ```
- Restart service cloudflared yang aktif.
- Verifikasi: `curl -I https://cctv.ainulhakim.com/healthz` → 200 (DNS CNAME sudah ada untuk tunnel ini)

### Task 7.3: Hardening
- `Cookie`: `HttpOnly`, `Secure`, `SameSite=Lax`
- Rate-limit login (5 percobaan / 5 menit per IP)
- Header keamanan: `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`
- `SECRET_KEY` dari file env, permission 600
- Verifikasi: `curl -I` menunjukkan header; login gagal 6x → diblokir sementara

### Task 7.4: Uji end-to-end dari luar
- Verifikasi manual (dari HP Master, bukan Wi-Fi rumah):
  1. buka `https://cctv.ainulhakim.com` → halaman login
  2. login viewer → lihat kamera public
  3. kamera scheduled di luar window → overlay tertutup, tidak ada stream
  4. coba akses langsung URL segmen HLS tanpa login → 401

### Task 7.5: Dokumen operasional
- **Create:** `docs/OPERASIONAL.md` — cara tambah kamera, atur jadwal, tambah user, lihat log, restart service, troubleshoot kamera offline

---

## Risiko & mitigasi

| Risiko | Mitigasi |
|---|---|
| Laptop rumah sleep / Wi-Fi drop | Fase 1 (blokir sleep, powersave off) + MediaMTX `sourceOnDemand` + watchdog |
| Disk rumah 81% (sisa 21 GB) | Fase ini **tidak** menyimpan rekaman di rumah; HLS hanya buffer di memori. Rekaman ditunda / pakai disk eksternal |
| Tailscale tambah latensi (~30 ms) | HLS LL, 1 detik segmen; jika kurang nyaman → pindah MediaMTX ke Hermes + Tailscale subnet router |
| Kamera `.222`/`.106` belum bisa | Tidak diblokir — arsitektur hanya butuh `slug` + `stream_key`, kamera bisa ditambah kapan saja setelah RTSP-nya aktif |
| Cloudflare ingress bentrok | Tambahkan rule sebelum catch-all `http_status:404`, restart, cek tunnel log |

## Yang ditunda (YAGNI)
- Rekaman berbasis jadwal (butuh disk eksternal)
- Deteksi gerakan berbasis AI (Frigate) — bisa jadi fase lanjutan
- Multi-tenant / multi-organisasi
- Notifikasi push/Telegram otomatis (setelah portal stabil)
