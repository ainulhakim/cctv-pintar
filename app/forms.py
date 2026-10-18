"""Validasi & normalisasi input form admin."""

from __future__ import annotations

import re
from typing import Iterable, List, Optional

from .models import MODE_PUBLIC, MODE_SCHEDULED

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,62}[a-z0-9])?$")
STREAM_KEY_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{1,62}[A-Za-z0-9])?$")

MIN_PASSWORD_LEN = 8
MAX_NAMA_LEN = 128


def normalize_slug(raw: Optional[str]) -> Optional[str]:
    """Slug hanya huruf kecil, angka, dan tanda hubung."""
    nilai = (raw or "").strip().lower()
    nilai = re.sub(r"\s+", "-", nilai)
    return nilai if SLUG_RE.match(nilai) else None


def normalize_stream_key(raw: Optional[str]) -> Optional[str]:
    nilai = (raw or "").strip()
    return nilai if STREAM_KEY_RE.match(nilai) else None


def normalize_username(raw: Optional[str]) -> Optional[str]:
    nilai = (raw or "").strip()
    return nilai if USERNAME_RE.match(nilai) else None


def validasi_password(password: Optional[str]) -> Optional[str]:
    """Kembalikan pesan error, atau None kalau password valid."""
    if not password or len(password) < MIN_PASSWORD_LEN:
        return f"Password minimal {MIN_PASSWORD_LEN} karakter."
    return None


def bersihkan_teks(raw: Optional[str], maks: int = MAX_NAMA_LEN) -> Optional[str]:
    nilai = (raw or "").strip()
    if not nilai:
        return None
    return nilai[:maks]


def validasi_mode(raw: Optional[str]) -> str:
    return MODE_SCHEDULED if (raw or "").strip() == MODE_SCHEDULED else MODE_PUBLIC


def validasi_hari(nilai: Iterable[str]) -> str:
    """Ubah daftar checkbox hari menjadi string "0,1,2" (Senin=0 .. Minggu=6)."""
    hari: List[int] = []
    for item in nilai or []:
        teks = str(item).strip()
        if teks.isdigit() and 0 <= int(teks) <= 6:
            hari.append(int(teks))
    return ",".join(str(d) for d in sorted(set(hari)))
