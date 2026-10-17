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
- [ ] **Fase 3** — Aplikasi FastAPI: skeleton, model, auth, login
- [ ] **Fase 4** — Logika jadwal + unit test
- [ ] **Fase 5** — Halaman pantauan viewer + proxy HLS ber-guard
- [ ] **Fase 6** — Panel admin (kamera, jadwal, user, log)
- [ ] **Fase 7** — Deploy cloudflared + hardening + uji end-to-end

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
systemctl status mediamtx      # relay RTSP -> HLS
systemctl status cctv-pintar   # aplikasi web (belum dibuat)
systemctl status cloudflared-cctv # konektor tunnel (belum dibuat)
```

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python scripts/seed.py          # buat admin pertama
uvicorn app.main:app --reload --port 8090
pytest -v
```

## Deploy

```bash
./scripts/deploy.sh             # rsync ke server rumah (lihat scripts/deploy.sh)
```
