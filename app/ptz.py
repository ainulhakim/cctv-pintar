"""Kontrol PTZ kamera Tapo lewat API lokal (port 443).

Kenapa modul terpisah dari model/repo:

- Kredensial akun TP-Link **tidak** disimpan di database aplikasi maupun repo.
  Semuanya dibaca dari file env terpisah (`PTZ_ENV`, default
  `/etc/cctv-pintar/ptz.env`, mode 600 root):

      TAPO_USER=akun@email
      TAPO_PASS=password-akun-tplink
      PTZ_HOSTS=cam140=192.168.18.140,cam142=192.168.18.142

  `PTZ_HOSTS` memetakan `stream_key` (yang dikenal aplikasi) ke IP kamera.
  Aplikasi tetap tidak tahu kredensial RTSP.

- Kamera Tapo tidak memakai ONVIF, jadi kontrol memakai protokol lokalnya
  sendiri (library `pytapo`). Gerakan bersifat **diskret per langkah**
  (`moveMotorStep`), bukan continuous — jadi tidak ada risiko kamera
  berputar terus kalau tombol tertahan, dan tidak perlu tombol Stop.

Bila `pytapo` belum terpasang atau konfigurasi kosong, semua fungsi
mengembalikan "tidak didukung" — aplikasi tetap jalan normal.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from typing import Dict, Optional, Tuple

PTZ_ENV = os.environ.get("PTZ_ENV", "/etc/cctv-pintar/ptz.env")

# Sudut untuk `moveMotorStep` (derajat, 0 <= a < 360).
# 0 = searah jarum jam, 90 = vertikal, 180 = berlawanan jarum jam, 270 = horizontal.
# Arah ini bisa berbeda antar model; kalau tombol terbalik, cukup ubah di sini.
ARAH_SUDUT = {"kanan": 0, "atas": 90, "kiri": 180, "bawah": 270}

TTL_KEMAMPUAN = 600.0  # detik
BATAS_GERAK = 30       # maksimum aksi PTZ per menit per pengguna
JENDELA_GERAK = 60.0

_lock = threading.Lock()
_konfig_cache: Tuple[float, Optional[dict]] = (0.0, None)
_klien: Dict[str, object] = {}
_kemampuan: Dict[str, Tuple[float, dict]] = {}
_riwayat: Dict[str, deque] = {}


def _baca_env(path: str) -> dict:
    hasil = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for baris in fh:
                baris = baris.strip()
                if not baris or baris.startswith("#") or "=" not in baris:
                    continue
                kunci, nilai = baris.split("=", 1)
                hasil[kunci.strip()] = nilai.strip().strip('"').strip("'")
    except OSError:
        return {}
    return hasil


def konfigurasi() -> dict:
    """Kredensial + peta stream_key -> IP kamera (di-cache per perubahan file)."""
    global _konfig_cache
    try:
        mtime = os.path.getmtime(PTZ_ENV)
    except OSError:
        mtime = 0.0
    with _lock:
        waktu, data = _konfig_cache
        if data is not None and waktu == mtime:
            return data

    env = _baca_env(PTZ_ENV) if mtime else {}
    user = env.get("TAPO_USER") or os.environ.get("TAPO_USER", "")
    pwd = env.get("TAPO_PASS") or os.environ.get("TAPO_PASS", "")
    cloud = env.get("TAPO_CLOUD_PASS") or os.environ.get("TAPO_CLOUD_PASS", "")
    mentah = env.get("PTZ_HOSTS") or os.environ.get("PTZ_HOSTS", "")
    host_map: Dict[str, str] = {}
    for potong in mentah.split(","):
        potong = potong.strip()
        if not potong or "=" not in potong:
            continue
        slug, host = potong.split("=", 1)
        host_map[slug.strip()] = host.strip()

    data = {"user": user, "password": pwd, "cloud": cloud, "hosts": host_map,
            "aktif": bool(user and pwd and host_map)}
    with _lock:
        _konfig_cache = (mtime, data)
    return data


def _host(stream_key: str) -> Optional[str]:
    return konfigurasi()["hosts"].get(stream_key)


def _klien_untuk(host: str):
    """Instance Tapo per IP (reuse sesi login; login Tapo relatif mahal)."""
    with _lock:
        ada = _klien.get(host)
    if ada is not None:
        return ada

    from pytapo import Tapo  # import lokal: aplikasi tetap jalan tanpa paket ini

    konf = konfigurasi()
    if not konf["aktif"]:
        raise RuntimeError("PTZ belum dikonfigurasi (TAPO_USER/TAPO_PASS/PTZ_HOSTS kosong)")
    klien = Tapo(
        host,
        konf["user"],
        konf["password"],
        cloudPassword=konf.get("cloud") or "",
        printDebugInformation=False,
        printWarnInformation=False,
    )
    with _lock:
        _klien[host] = klien
    return klien


def _lupakan(host: str) -> None:
    with _lock:
        _klien.pop(host, None)


def _parse_kemampuan(mentah) -> dict:
    """Terjemahkan respons `getMotorCapability` jadi penanda sederhana.

    Bentuk respons berbeda antar firmware, jadi dipakai pencocokan longgar
    pada JSON-nya, bukan struktur yang diandaikan.
    """
    teks = json.dumps(mentah).lower() if not isinstance(mentah, str) else mentah.lower()
    pan = "horizontal" in teks or "pan" in teks
    tilt = "vertical" in teks or "tilt" in teks
    zoom = "zoom" in teks
    return {"pan": pan, "tilt": tilt, "zoom": zoom}


def kemampuan(stream_key: str, segarkan: bool = False) -> dict:
    """Apakah kamera ini punya motor PTZ. Hasil di-cache 10 menit."""
    host = _host(stream_key)
    if not host:
        return {"didukung": False, "alasan": "Kamera ini tidak terdaftar untuk PTZ.", "host": None,
                "pan": False, "tilt": False, "zoom": False}
    if not konfigurasi()["aktif"]:
        return {"didukung": False, "alasan": "Panel PTZ belum dikonfigurasi di server.",
                "host": host, "pan": False, "tilt": False, "zoom": False}

    sekarang = time.time()
    if not segarkan:
        with _lock:
            tersimpan = _kemampuan.get(host)
        if tersimpan and tersimpan[0] > sekarang:
            return tersimpan[1]

    try:
        klien = _klien_untuk(host)
        mentah = klien.getMotorCapability()
        try:
            info = klien.getDeviceInfo()
        except Exception:  # noqa: BLE001 - info model hanya pelengkap
            info = {}
        ciri = _parse_kemampuan(mentah)
        hasil = {
            "didukung": bool(ciri["pan"] or ciri["tilt"]),
            "alasan": "",
            "host": host,
            "model": str(info.get("device_model") or info.get("model") or ""),
            "mentah": mentah,
            **ciri,
        }
        if not hasil["didukung"]:
            hasil["alasan"] = "Kamera menjawab, tetapi tidak punya motor pan/tilt."
    except Exception as exc:  # noqa: BLE001 - kamera mati / login gagal
        _lupakan(host)
        hasil = {
            "didukung": False,
            "alasan": f"Gagal menghubungi kamera ({type(exc).__name__}: {str(exc)[:120]})",
            "host": host,
            "pan": False,
            "tilt": False,
            "zoom": False,
        }

    with _lock:
        _kemampuan[host] = (sekarang + TTL_KEMAMPUAN, hasil)
    return hasil


def batas_gerak_terlampaui(kunci: str) -> bool:
    """Rate limit sederhana: maksimum `BATAS_GERAK` aksi per menit per pengguna."""
    sekarang = time.time()
    with _lock:
        riwayat = _riwayat.setdefault(kunci, deque())
        while riwayat and sekarang - riwayat[0] > JENDELA_GERAK:
            riwayat.popleft()
        if len(riwayat) >= BATAS_GERAK:
            return True
        riwayat.append(sekarang)
        return False


def gerak(stream_key: str, arah: str) -> dict:
    """Geser kamera satu langkah ke `arah` (kanan/kiri/atas/bawah)."""
    arah = (arah or "").strip().lower()
    if arah not in ARAH_SUDUT:
        raise ValueError(f"Arah tidak dikenal: {arah}")
    host = _host(stream_key)
    if not host:
        raise RuntimeError("Kamera ini tidak terdaftar untuk PTZ.")

    klien = _klien_untuk(host)
    klien.moveMotorStep(ARAH_SUDUT[arah])
    return {"ok": True, "arah": arah, "sudut": ARAH_SUDUT[arah], "host": host}


def daftar_preset(stream_key: str) -> list:
    host = _host(stream_key)
    if not host:
        return []
    klien = _klien_untuk(host)
    presets = klien.getPresets() or {}
    hasil = []
    for kunci, nilai in presets.items():
        if isinstance(nilai, dict):
            nama = nilai.get("name") or nilai.get("custom_name") or str(kunci)
        else:
            nama = str(nilai)
        hasil.append({"id": str(kunci), "nama": str(nama)})
    return hasil


def simpan_preset(stream_key: str, nama: str) -> dict:
    host = _host(stream_key)
    if not host:
        raise RuntimeError("Kamera ini tidak terdaftar untuk PTZ.")
    nama = (nama or "").strip()[:32]
    if not nama:
        raise ValueError("Nama preset wajib diisi.")
    klien = _klien_untuk(host)
    klien.savePreset(nama)
    return {"ok": True, "nama": nama}


def ke_preset(stream_key: str, preset_id: str) -> dict:
    host = _host(stream_key)
    if not host:
        raise RuntimeError("Kamera ini tidak terdaftar untuk PTZ.")
    klien = _klien_untuk(host)
    klien.setPreset(str(preset_id))
    return {"ok": True, "preset": str(preset_id)}


def lupakan_semua() -> None:
    """Dipakai test / setelah kredensial berubah."""
    global _konfig_cache
    with _lock:
        _klien.clear()
        _kemampuan.clear()
        _riwayat.clear()
        _konfig_cache = (0.0, None)
