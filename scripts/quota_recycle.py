#!/usr/bin/env python3
"""quota_recycle.py — penjaga kapasitas rekaman CCTV.

Prinsip: rekaman punya KUOTA yang dideklarasikan (mis. 300 GB) yang selalu lebih
kecil dari kapasitas disk. Kalau kuota tercapai, rekaman TERLAMA dihapus lebih
dulu, jadi rekaman baru selalu punya tempat (recycle / ring buffer).

Dua tahap pembersihan:
  1. Retensi  — hapus berkas lebih tua dari --retention-days (kalau diset).
  2. Kuota    — selama total masih di atas high-watermark (mis. 90% kuota),
                hapus berkas tertua sampai di bawah ambang.

Berkas yang masih mungkin sedang ditulis (umurnya < --min-keep-seconds) tidak
pernah dihapus, supaya ffmpeg yang sedang merekam tidak kehilangan segmen aktif.

Kompatibel Python 3.9+ (host rumah: Debian 11).

Pemakaian:
    python3 quota_recycle.py --root /srv/cctv-rec --quota-gb 300
    python3 quota_recycle.py --root /srv/cctv-rec --quota-gb 300 --dry-run --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

GB = 1024 ** 3
EKSTENSI = {".mp4", ".mkv", ".ts", ".mov"}


def kumpulkan(root: Path) -> List[Tuple[Path, int, float]]:
    """Daftar (path, ukuran, mtime) untuk semua berkas rekaman."""
    hasil = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for nama in filenames:
            if Path(nama).suffix.lower() not in EKSTENSI:
                continue
            path = Path(dirpath) / nama
            try:
                st = path.stat()
            except OSError:
                continue
            hasil.append((path, st.st_size, st.st_mtime))
    return hasil


def bersihkan(
    root: Path,
    kuota_bytes: int,
    high_watermark: float = 0.90,
    retention_days: float = 0.0,
    min_keep_seconds: float = 120.0,
    dry_run: bool = False,
) -> Dict[str, object]:
    sekarang = time.time()
    berkas = kumpulkan(root)
    total_awal = sum(b[1] for b in berkas)
    batas = int(kuota_bytes * max(0.05, min(high_watermark, 1.0)))

    dihapus: List[str] = []
    bytes_dihapus = 0

    def buang(item: Tuple[Path, int, float]) -> None:
        nonlocal bytes_dihapus
        path, ukuran, _mtime = item
        if not dry_run:
            try:
                path.unlink()
            except OSError as exc:  # noqa: BLE001 - laporkan, jangan berhenti
                print("!! gagal hapus {}: {}".format(path, exc), file=sys.stderr)
                return
        dihapus.append(str(path))
        bytes_dihapus += ukuran

    # Tahap 1: retensi umur
    if retention_days > 0:
        batas_umur = sekarang - retention_days * 86400
        for item in sorted(berkas, key=lambda b: b[2]):
            if item[2] < batas_umur and (sekarang - item[2]) > min_keep_seconds:
                buang(item)

    # Tahap 2: kuota (buang terlama lebih dulu)
    sisa = total_awal - bytes_dihapus
    if sisa > batas:
        kandidat = [b for b in berkas if str(b[0]) not in set(dihapus)]
        for item in sorted(kandidat, key=lambda b: b[2]):
            if sisa <= batas:
                break
            umur = sekarang - item[2]
            if umur <= min_keep_seconds:
                continue  # mungkin sedang ditulis recorder
            buang(item)
            sisa -= item[1]

    return {
        "root": str(root),
        "dry_run": dry_run,
        "quota_bytes": kuota_bytes,
        "quota_gb": round(kuota_bytes / GB, 2),
        "threshold_bytes": batas,
        "total_before_bytes": total_awal,
        "total_after_bytes": total_awal - bytes_dihapus,
        "files_total": len(berkas),
        "files_deleted": len(dihapus),
        "bytes_deleted": bytes_dihapus,
        "usage_pct": round((total_awal - bytes_dihapus) / kuota_bytes * 100, 2) if kuota_bytes else 0.0,
        "deleted": dihapus[:50],
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Recycle rekaman CCTV berbasis kuota")
    p.add_argument("--root", required=True, help="direktori rekaman (volume khusus)")
    p.add_argument("--quota-gb", type=float, required=True, help="kuota maksimal (GB)")
    p.add_argument("--high-watermark", type=float, default=0.90,
                   help="ambang pembersihan terhadap kuota (default 0.90)")
    p.add_argument("--retention-days", type=float, default=0.0,
                   help="hapus rekaman lebih tua dari N hari (0 = nonaktif)")
    p.add_argument("--min-keep-seconds", type=float, default=120.0,
                   help="jangan hapus berkas lebih muda dari N detik (default 120)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print("!! direktori tidak ada: {}".format(root), file=sys.stderr)
        return 2
    if args.quota_gb <= 0:
        print("!! --quota-gb harus > 0", file=sys.stderr)
        return 2

    ringkas = bersihkan(
        root=root,
        kuota_bytes=int(args.quota_gb * GB),
        high_watermark=args.high_watermark,
        retention_days=args.retention_days,
        min_keep_seconds=args.min_keep_seconds,
        dry_run=args.dry_run,
    )

    if args.json:
        print(json.dumps(ringkas))
    else:
        print("root        : {}".format(ringkas["root"]))
        print("kuota       : {} GB".format(ringkas["quota_gb"]))
        print("terpakai    : {} GB -> {} GB ({}%)".format(
            round(int(ringkas["total_before_bytes"]) / GB, 2),
            round(int(ringkas["total_after_bytes"]) / GB, 2),
            ringkas["usage_pct"]))
        print("berkas      : {} (dihapus {})".format(
            ringkas["files_total"], ringkas["files_deleted"]))
        print("dibebaskan  : {} GB".format(round(int(ringkas["bytes_deleted"]) / GB, 2)))
        if ringkas["dry_run"]:
            print("(dry-run: tidak ada yang benar-benar dihapus)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
