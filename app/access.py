"""Keputusan akses kamera (dipakai bersama oleh proxy stream dan snapshot).

Urutan pemeriksaan: jadwal dulu, lalu override admin. Dengan begitu override
hanya relevan saat kamera memang tertutup.
"""

from __future__ import annotations

from .override import aktif as override_aktif
from .schedule import is_open

OPEN = "open"
OVERRIDE = "override"
CLOSED = "closed"


def keputusan_akses(request, user, camera, now=None) -> str:
    if camera is None:
        return CLOSED
    if is_open(camera.policy, now):
        return OPEN
    if override_aktif(request, user, camera):
        return OVERRIDE
    return CLOSED


def boleh_akses(request, user, camera, now=None) -> bool:
    return keputusan_akses(request, user, camera, now) != CLOSED
