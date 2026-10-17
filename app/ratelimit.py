"""Rate limiter sederhana (in-memory, sliding window) untuk percobaan login gagal.

Cukup untuk 1 proses uvicorn (deployment prototype). Kalau nanti dipakai
beberapa worker, ganti backend-nya ke Redis.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, Optional


class SlidingWindowLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 300, max_keys: int = 20000) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._data: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    # -- internal --
    def _prune(self, key: str, now: float) -> Optional[Deque[float]]:
        """Buang catatan yang sudah keluar window. Dipanggil dengan lock aktif."""
        antrian = self._data.get(key)
        if antrian is None:
            return None
        batas = now - self.window_seconds
        while antrian and antrian[0] <= batas:
            antrian.popleft()
        if not antrian:
            self._data.pop(key, None)
            return None
        return antrian

    @staticmethod
    def _now(now: Optional[float]) -> float:
        return time.time() if now is None else float(now)

    # -- API publik --
    def is_blocked(self, key: str, now: Optional[float] = None) -> bool:
        saat = self._now(now)
        with self._lock:
            antrian = self._prune(key, saat)
            return bool(antrian) and len(antrian) >= self.max_attempts

    def retry_after(self, key: str, now: Optional[float] = None) -> int:
        """Detik sampai boleh mencoba lagi (0 = tidak diblokir)."""
        saat = self._now(now)
        with self._lock:
            antrian = self._prune(key, saat)
            if not antrian or len(antrian) < self.max_attempts:
                return 0
            return max(1, int(round(antrian[0] + self.window_seconds - saat)))

    def record_failure(self, key: str, now: Optional[float] = None) -> None:
        saat = self._now(now)
        with self._lock:
            if key not in self._data and len(self._data) >= self.max_keys:
                # lindungi memori: buang semua kalau sudah kebanyakan kunci
                self._data.clear()
            self._data.setdefault(key, deque()).append(saat)

    def reset(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def reset_all(self) -> None:
        with self._lock:
            self._data.clear()

    def keys_count(self) -> int:
        with self._lock:
            return len(self._data)


# 5 percobaan gagal per 5 menit per IP
login_limiter = SlidingWindowLimiter(max_attempts=5, window_seconds=300)
