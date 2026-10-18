"""Snapshot JPEG on-demand dari MediaMTX (tanpa menyentuh kredensial kamera).

Sumbernya RTSP lokal MediaMTX (`rtsp://127.0.0.1:8554/<stream_key>`) — jadi
aplikasi tetap tidak perlu tahu kredensial kamera.
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Dict, Optional, Tuple

from .config import settings


class SnapshotError(RuntimeError):
    """Gagal mengambil snapshot dari MediaMTX."""


_cache: Dict[str, Tuple[float, bytes]] = {}
_locks: Dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def capture(stream_key: str, timeout: Optional[float] = None) -> bytes:
    """Ambil 1 frame JPEG dari stream MediaMTX. Blocking (jalankan di threadpool)."""
    url = f"{settings.mediamtx_rtsp_base}/{stream_key}"
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-i",
        url,
        "-frames:v",
        "1",
        "-q:v",
        "4",
        "-f",
        "image2",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout or settings.snapshot_timeout)
    except subprocess.TimeoutExpired as exc:
        raise SnapshotError("ffmpeg timeout") from exc
    except FileNotFoundError as exc:  # pragma: no cover - ffmpeg tidak ada
        raise SnapshotError("ffmpeg tidak ditemukan di server") from exc

    if proc.returncode != 0 or not proc.stdout:
        pesan = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise SnapshotError(pesan[-1] if pesan else "ffmpeg gagal mengambil frame")
    return proc.stdout


def get_snapshot(stream_key: str, now: Optional[float] = None, ttl: Optional[float] = None) -> bytes:
    """Snapshot dengan cache pendek supaya ffmpeg tidak dijalankan tiap request."""
    ttl = settings.snapshot_cache_seconds if ttl is None else ttl
    saat = time.time() if now is None else now

    entri = _cache.get(stream_key)
    if entri and ttl > 0 and saat - entri[0] < ttl:
        return entri[1]

    with _lock_for(stream_key):
        entri = _cache.get(stream_key)
        if entri and ttl > 0 and saat - entri[0] < ttl:
            return entri[1]
        data = capture(stream_key)
        _cache[stream_key] = (saat, data)
        return data


def cache_clear() -> None:
    with _guard:
        _cache.clear()
