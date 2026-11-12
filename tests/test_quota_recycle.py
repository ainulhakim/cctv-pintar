"""Test logika recycle rekaman (kuota + retensi)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

GB = 1024 ** 3
SKRIP = Path(__file__).resolve().parent.parent / "scripts" / "quota_recycle.py"


def buat_berkas(root: Path, nama: str, ukuran: int, umur_detik: float) -> Path:
    path = root / nama
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * ukuran)
    waktu = time.time() - umur_detik
    os.utime(path, (waktu, waktu))
    return path


def jalankan(*args: str) -> str:
    hasil = subprocess.run(
        [sys.executable, str(SKRIP), *args], capture_output=True, text=True, check=True
    )
    return hasil.stdout


def test_kuota_menghapus_terlama_dulu(tmp_path):
    # kuota 10 MB, high-watermark 50% -> harus menyisakan <= 5 MB
    for i in range(5):
        buat_berkas(tmp_path, f"utara/seg{i}.mp4", 2 * 1024 * 1024, umur_detik=3600 * (5 - i))
    total_awal = sum(p.stat().st_size for p in tmp_path.rglob("*.mp4"))
    assert total_awal == 10 * 1024 * 1024

    out = jalankan("--root", str(tmp_path), "--quota-gb", str(10 / 1024),
                   "--high-watermark", "0.5", "--json")
    assert '"files_deleted"' in out
    sisa = sum(p.stat().st_size for p in tmp_path.rglob("*.mp4"))
    assert sisa <= 5 * 1024 * 1024

    # yang tersisa harus berkas terbaru
    tersisa = sorted(p.name for p in tmp_path.rglob("*.mp4"))
    assert tersisa == ["seg3.mp4", "seg4.mp4"]


def test_tidak_menyentuh_berkas_baru(tmp_path):
    buat_berkas(tmp_path, "utara/lama.mp4", 2 * 1024 * 1024, umur_detik=7200)
    buat_berkas(tmp_path, "utara/baru.mp4", 2 * 1024 * 1024, umur_detik=5)
    jalankan("--root", str(tmp_path), "--quota-gb", str(1 / 1024),
             "--high-watermark", "1.0", "--min-keep-seconds", "120", "--json")
    assert (tmp_path / "utara" / "baru.mp4").exists()
    assert not (tmp_path / "utara" / "lama.mp4").exists()


def test_retensi_umur(tmp_path):
    buat_berkas(tmp_path, "a/lama.mp4", 1024, umur_detik=10 * 86400)
    buat_berkas(tmp_path, "a/baru.mp4", 1024, umur_detik=3600)
    jalankan("--root", str(tmp_path), "--quota-gb", "1", "--retention-days", "3", "--json")
    assert not (tmp_path / "a" / "lama.mp4").exists()
    assert (tmp_path / "a" / "baru.mp4").exists()


def test_dry_run_tidak_menghapus(tmp_path):
    buat_berkas(tmp_path, "b/seg.mp4", 2 * 1024 * 1024, umur_detik=7200)
    out = jalankan("--root", str(tmp_path), "--quota-gb", str(1 / 1024),
                   "--high-watermark", "1.0", "--dry-run", "--json")
    assert (tmp_path / "b" / "seg.mp4").exists()
    assert '"dry_run": true' in out


def test_berkas_selain_rekaman_diabaikan(tmp_path):
    buat_berkas(tmp_path, "catatan.txt", 1024, umur_detik=7200)
    buat_berkas(tmp_path, "b/seg.mp4", 2 * 1024 * 1024, umur_detik=7200)
    jalankan("--root", str(tmp_path), "--quota-gb", str(1 / 1024),
             "--high-watermark", "1.0", "--json")
    assert (tmp_path / "catatan.txt").exists()
