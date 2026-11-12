# Konsep Rekaman CCTV dengan Kuota & Recycle

Tanggal: 2026-11-12 · Status: konsep + kerangka siap dipasang

## 1. Prinsip

Rekaman **tidak** boleh memakai seluruh disk. Ada tiga angka yang dipisahkan:

| Angka | Arti | Contoh |
|---|---|---|
| Kapasitas fisik | ukuran disk/volume | HDD 1 TB |
| **Kuota rekaman (dideklarasikan)** | batas maksimal yang boleh dipakai rekaman | 300 GB |
| High-watermark | ambang mulai menghapus (persen kuota) | 90% = 270 GB |

Saat pemakaian menembus high-watermark, rekaman **terlama** dihapus lebih dulu
(recycle / ring buffer). Hasilnya rekaman terbaru selalu ada, tanpa operator
harus menghapus manual, dan disk sistem tidak pernah terancam penuh.

## 2. Dua lapis pengamanan

**Lapis 1 — hard limit filesystem (volume khusus).**
Volume rekaman dibuat sebagai ext4 on loopback image berukuran *deklarasi*
(`/srv/cctv-rec/rec.img`, mis. 300 GB). Filesystem di dalamnya benar-benar hanya
300 GB: apa pun bug di recorder, ia tidak bisa menulis lebih dari itu. Disk
sistem tetap aman. Ukuran diubah kapan saja: `truncate -s <baru>G` +
`resize2fs` (lihat `scripts/record_setup_volume.sh --grow`).

Alternatif tanpa loop (lebih cepat, tanpa overhead ~5%): partisi terpisah atau
ext4 *project quota* (`prjquota` di mount option). Kelemahannya butuh
repartition/remount saat mengubah ukuran, jadi loop lebih praktis untuk
pemakaian rumahan.

**Lapis 2 — recycler aplikasi.**
`scripts/quota_recycle.py` dijalankan systemd timer tiap 5 menit:
1. hapus berkas lebih tua dari `RECORD_RETENTION_DAYS` (opsional),
2. selama total > `kuota × high-watermark`, hapus berkas tertua,
3. berkas yang lebih muda dari 120 detik tidak pernah dihapus (mungkin sedang
   ditulis recorder).

Dry-run tersedia: `--dry-run --json` untuk melihat apa yang *akan* dihapus.

## 3. Alur data

```
kamera LAN ──RTSP sub-stream──► recorder ffmpeg (-c copy, segmen 1 jam)
                                     │
                                     ▼
                        /srv/cctv-rec/<kamera>/YYYYmmdd-HHMMSS_sub.mp4
                                     │
                        quota_recycle.py (tiap 5 menit)
                                     │
                        hapus terlama saat > 90% kuota
```

Kenapa `-c copy` (bukan transcode): CPU hampir nol dan kualitas asli terjaga.
Kamera Tiandy sudah H.264, jadi tidak perlu diubah.

Kenapa recorder terpisah dari MediaMTX: MediaMTX di rumah memakai
`runOnDemand` — publisher hanya hidup saat ada penonton. Rekaman 24 jam butuh
penarikan terus-menerus, jadi recorder punya koneksi RTSP sendiri ke kamera
(sub-stream), tidak bergantung pada ada/tidaknya penonton.

Kamera lintas jaringan (Tapo kantor via relay MacBook): rekam dari
`rtsp://127.0.0.1:8554/camkantor`, dan otomatis ikut mati saat relay mati
(supervisor recorder akan retry).

## 4. Hitungan kapasitas (angka nyata)

Sub-stream 704×576 @ ~600 kbps (konfigurasi saat ini):

| Item | Nilai |
|---|---|
| Per kamera per jam | ~270 MB |
| Per kamera per hari | ~6,5 GB |
| 4 kamera per hari | ~26 GB |
| Kuota 300 GB (sub-stream) | **≈ 11 hari** |
| Kuota 500 GB | ≈ 19 hari |
| Kuota 1 TB | ≈ 38 hari |

Main stream (4 MP @ ~4 Mbps) untuk perbandingan: ~43 GB/hari/kamera →
kuota 300 GB hanya ≈ 1,7 hari. Jadi **rekaman 24 jam pakai sub-stream**;
main stream hanya untuk klip kejadian (on-demand recording).

## 5. Kondisi host saat ini (penting)

Server rumah: ThinkPad Debian 11, disk **SSD 128 GB** (root 110 GB, **sisa 19 GB**),
RAM 15 GB, tanpa disk kedua.

Artinya: **kuota 300 GB belum mungkin** dengan hardware sekarang. Pilihan:

1. **Disk eksternal USB 3.0 (disarankan)** — HDD 1 TB/2 TB. Cukup untuk kuota
   300–800 GB, tidak perlu bongkar laptop. Mount ke `/mnt/cctv-disk`, lalu
   volume rekaman dibuat di atasnya.
2. Ganti SSD internal dengan yang lebih besar (butuh buka baut + reinstall).
3. Mulai kecil: kuota 8–10 GB di SSD sekarang → hanya ~8–10 jam rekaman sub-stream
   untuk 4 kamera. Layak untuk uji coba, tidak untuk arsip.

Rekomendasi: pasang HDD eksternal 1 TB, kuota 300 GB (sisakan ruang untuk
pertumbuhan harian + retensi 11 hari).

## 6. Komponen yang sudah disiapkan

- `scripts/record_setup_volume.sh` — buat/perbesar volume rekaman berkuota.
- `scripts/recorder.sh` — perekam per kamera, supervisor auto-restart.
- `deploy/cctv-record@.service` — unit systemd per kamera (`cctv-record@utara`).
- `scripts/quota_recycle.py` — recycler kuota + retensi (ada test-nya).
- `deploy/cctv-recycle.service` + `.timer` — jalankan recycler tiap 5 menit.

Konfigurasi ditaruh di `/etc/cctv-record/`:

```
/etc/cctv-record/quota.env      RECORD_QUOTA_GB=300  RECORD_HIGH_WATERMARK=0.9  RECORD_RETENTION_DAYS=0
/etc/cctv-record/utara.env      CAM_URL=rtsp://...sub-stream...
/etc/cctv-record/selatan.env    CAM_URL=rtsp://...
```

## 7. Langkah pemasangan (setelah disk tersedia)

```bash
# 1) volume berkuota
sudo scripts/record_setup_volume.sh --size-gb 300 --mount /srv/cctv-rec

# 2) env per kamera + kuota
sudo mkdir -p /etc/cctv-record
sudo tee /etc/cctv-record/quota.env <<'EOF'
RECORD_QUOTA_GB=300
RECORD_HIGH_WATERMARK=0.9
RECORD_RETENTION_DAYS=0
EOF

# 3) recorder + recycler
sudo cp deploy/cctv-record@.service deploy/cctv-recycle.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cctv-record@utara cctv-record@selatan cctv-record@balai
sudo systemctl enable --now cctv-recycle.timer

# 4) verifikasi
systemctl list-units 'cctv-record@*' --no-pager
find /srv/cctv-rec -name '*.mp4' -mmin -10 | head
python3 scripts/quota_recycle.py --root /srv/cctv-rec --quota-gb 300 --dry-run
df -h /srv/cctv-rec
```

## 8. Fase lanjutan (belum dikerjakan)

- Halaman **Rekaman** di viewer: daftar segmen per kamera + tombol putar
  (HTTP range ke berkas mp4), dibatasi login admin.
- Penanda "rekaman aktif" dan sisa hari retensi di dashboard
  (`pemakaian / kuota`, estimasi hari tersisa).
- Rekaman berbasis kejadian (motion detect) supaya kuota jauh lebih efisien.
- Ekspor klip (potong rentang waktu → unduh mp4).
