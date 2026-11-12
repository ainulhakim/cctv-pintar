"""Deteksi kesehatan kamera di balik MediaMTX.

Latar belakang (bug 2026-11-12): MediaMTX dikonfigurasi `runOnDemand`, artinya
path hanya menjadi "ready" saat ada penonton. Konsekuensinya `ready` + `tracks`
BUKAN bukti kamera mati — saat viewer sepi, semua kamera terlihat "offline".

Aturan yang dipakai modul ini:

* `live`    : MediaMTX punya publisher dengan video (bukti positif hidup).
* `offline` : probe aktif (ffprobe ke RTSP MediaMTX, memicu runOnDemand) GAGAL,
              jadi ada bukti positif kamera/relay tidak mengirim gambar.
* `siap`    : sisanya — kamera terjangkau tapi sedang siaga, atau belum
              diprobe. Ketidaktahuan tidak boleh dilaporkan sebagai offline.

Probe berjalan di thread latar dengan cache TTL, supaya endpoint status tidak
pernah menunggu 10-25 detik (runOnDemandStartTimeout) per kamera.
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Dict, Optional, Tuple

from .config import settings

LIVE = "live"
SIAP = "siap"
OFFLINE = "offline"

# stream_key -> (timestamp_probe, state)
_hasil: Dict[str, Tuple[float, str]] = {}
_berjalan: set[str] = set()
_guard = threading.Lock()


def _ffprobe(stream_key: str, timeout: float) -> bool:
    """True kalau MediaMTX bisa mengeluarkan video untuk path ini."""
    url = "{}/{}".format(settings.mediamtx_rtsp_base, stream_key)
    cmd = [
        "ffprobe",
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-rw_timeout",
        str(int(timeout * 900000)),  # mikrodetik, sedikit di bawah timeout proses
        "-analyzeduration",
        "3000000",
        "-probesize",
        "1000000",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name",
        "-of",
        "csv=p=0",
        url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    keluaran = proc.stdout.decode("utf-8", "replace").strip()
    return proc.returncode == 0 and bool(keluaran)


def _kerja(stream_key: str, timeout: float) -> None:
    try:
        ok = _ffprobe(stream_key, timeout)
    except Exception:  # noqa: BLE001 - probe tidak boleh mematikan worker
        ok = False
    with _guard:
        # Probe sukses hanya membuktikan kamera terjangkau (siaga), bukan bahwa
        # ada yang sedang menonton — runOnDemand akan menutup publisher lagi.
        _hasil[stream_key] = (time.time(), SIAP if ok else OFFLINE)
        _berjalan.discard(stream_key)


def _mulai_probe(stream_key: str, timeout: float) -> None:
    with _guard:
        if stream_key in _berjalan:
            return
        _berjalan.add(stream_key)
    threading.Thread(
        target=_kerja, args=(stream_key, timeout), name=f"probe-{stream_key}", daemon=True
    ).start()


def state(stream_key: str, publisher_aktif: bool) -> str:
    """Status satu kamera, tanpa pernah memblokir pemanggil."""
    if publisher_aktif:
        with _guard:
            _hasil[stream_key] = (time.time(), LIVE)
        return LIVE

    if not settings.live_probe:
        return SIAP

    sekarang = time.time()
    with _guard:
        catatan = _hasil.get(stream_key)
    if catatan is not None:
        waktu, nilai = catatan
        if sekarang - waktu < settings.live_probe_ttl:
            return nilai

    _mulai_probe(stream_key, settings.live_probe_timeout)
    # Belum ada bukti baru: jangan mengklaim offline.
    return catatan[1] if catatan is not None else SIAP


def reset(stream_key: Optional[str] = None) -> None:
    """Kosongkan cache (dipakai test)."""
    with _guard:
        if stream_key is None:
            _hasil.clear()
            _berjalan.clear()
        else:
            _hasil.pop(stream_key, None)
            _berjalan.discard(stream_key)
