# CCTV Pintar

Aplikasi web pemantauan CCTV (prototype) dengan **autentikasi sendiri** dan **kontrol akses berbasis jadwal** per kamera.

## Arsitektur (1 server)

Semua berjalan di server **`rumah`** (`<IP-TAILNET>`) karena hanya mesin ini yang bisa menjangkau kamera di LAN `<LAN-RUMAH>`.

```
Kamera Tiandy (<IP-KAMERA-1> / .223)
      │ RTSP sub-stream 704x576 HEVC
      ▼
MediaMTX (127.0.0.1:8554 RTSP, 127.0.0.1:8888 HLS, 127.0.0.1:9997 API)
      │  transcode on-demand H.265 -> H.264 (ffmpeg runOnDemand)
      ▼
Aplikasi FastAPI cctv-pintar (127.0.0.1:8090)   ← auth + cek jadwal + proxy HLS
      ▼
cloudflared tunnel cctv-pintar → https://cctv.ainulhakim.com
```

## Prinsip keamanan

- Kredensial kamera **hanya** ada di konfigurasi MediaMTX di server. Aplikasi & browser **tidak pernah** menerimanya.
- MediaMTX (RTSP/HLS/API) hanya listen di `127.0.0.1` → tidak bisa diakses dari internet.
- HLS hanya keluar lewat endpoint aplikasi ber-autentikasi yang memvalidasi sesi **dan** jadwal akses.
- Aplikasi punya tabel `users` sendiri (bcrypt) + session cookie.

## Status pekerjaan

- [x] **Fase 0** — Recon kamera, identifikasi kredensial, cek sub-stream
- [x] **Fase 1** — Blokir sleep/suspend di server rumah, WiFi powersave off, linger
- [x] **Fase 2** — MediaMTX + transcode on-demand + systemd service
- [x] **Fase 3** — Aplikasi FastAPI: skeleton, model, auth, login (bcrypt langsung tanpa passlib)
- [x] **Fase 4** — Logika jadwal (`app/schedule.py`) + unit test, termasuk window lintas tengah malam
- [ ] **Fase 5** — Halaman pantauan viewer + proxy HLS ber-guard
- [ ] **Fase 6** — Panel admin (kamera, jadwal, user, log)
- [~] **Fase 7** — Deploy jalan (systemd + tunnel Cloudflare + rate limit login); sisa: uji dari HP & `docs/OPERASIONAL.md`

## Akses aplikasi (sudah jalan)

- Tailnet: `http://<IP-TAILNET>:8090` (kini **200 OK**)
- Publik: `https://cctv.ainulhakim.com` (tunnel `cctv-pintar`, **200 OK**)
- Login awal: user `admin`, password ada di `/home/ainul/cctv-pintar/.env`
- `/api/docs` **mati** saat `APP_ENV=production`
- Belum: halaman pantauan (fase 5) — `/` masih placeholder statistik

Detail rencana: [`docs/plans/2026-10-17-cctv-portal.md`](docs/plans/2026-10-17-cctv-portal.md)

## Infrastruktur

| Item | Nilai |
|---|---|
| Server | `ainul@<IP-TAILNET>` · Debian 11 · x86_64 · LAN `<IP-SERVER-LAN>` |
| Cloudflare tunnel | `cctv-pintar` · `<TUNNEL-ID>` |
| Domain | `cctv.ainulhakim.com` |
| Kamera 1 | `<IP-KAMERA-1>` — Area Utara — Tiandy TC-C34QN |
| Kamera 2 | `<IP-KAMERA-2>` — Area Selatan — Tiandy TC-C34QN |
| Path RTSP | main `/1/1` · sub `/1/2` (keduanya perlu kredensial) |

Kredensial kamera **tidak** disimpan di repo ini — ada di `deploy/mediamtx.yml` di server (lihat `deploy/mediamtx.yml.example` untuk template) dan catatan di server development.

## Service di server

```bash
systemctl status mediamtx          # relay RTSP -> HLS (aktif)
systemctl status cctv-pintar       # aplikasi web, bind <IP-TAILNET>:8090 (aktif)
systemctl status cloudflared-cctv  # konektor tunnel cctv.ainulhakim.com (aktif)
```

Pemasangan/repasang unit di server rumah:

```bash
ssh ainul@<IP-TAILNET>
cd ~/cctv-pintar && SUDO_PASS=xxxxx bash scripts/remote_setup_rumah.sh
```

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python scripts/seed.py --with-cameras   # buat admin + 2 kamera contoh
uvicorn app.main:app --reload --port 8090
pytest -q
```

Catatan: bcrypt dipakai **langsung** (tanpa passlib) agar tidak ada warning
"trapped error reading bcrypt version" dari passlib vs bcrypt 4.x.
Password lebih dari 72 byte di-pre-hash (SHA-256+base64) sehingga tidak dipotong.

## Konvensi jadwal

- Hari: **Senin=0 … Minggu=6** (sama dengan `datetime.weekday()`), disimpan sebagai string `"0,1,2"`.
- Jam (`start_time`/`end_time`) adalah waktu lokal sesuai `policy.timezone` (default `Asia/Jakarta`).
- Window mendukung lintas tengah malam: `22:00–05:00` berarti dini hari ikut hari **sebelumnya**.
- `start_time == end_time` = terbuka 24 jam pada hari terpilih.
- `is_open()` / `next_open()` ada di `app/schedule.py` (murni, tanpa I/O) — lihat `tests/test_schedule.py`.

## Verifikasi setelah deploy

```bash
# di server rumah
cd /home/ainul/cctv-pintar
.venv/bin/python -m pytest -q         # 75 test
bash scripts/provision_rumah.sh       # sekali saja: buat .env (perm 600)
.venv/bin/python scripts/seed.py --with-cameras
.venv/bin/python scripts/smoke.py     # uji HTTP end-to-end (12 pemeriksaan)
```

Status verifikasi terakhir: **75 test hijau** + **smoke 12/12 lolos** di server rumah (Python 3.9.2).

## Deploy

```bash
./scripts/deploy.sh                    # rsync ke server rumah (ssh interaktif)
RSSH_PASS=xxxxx ./scripts/deploy.sh    # versi non-interaktif (sshpass)
```

Catatan server rumah: `rsync` dan `python3.9-venv` sudah dipasang, `.venv` proyek sudah terisi dependensi.
