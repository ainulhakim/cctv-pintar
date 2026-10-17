"""Logika jadwal akses kamera (requirement #2).

Konvensi hari: **Senin=0 … Minggu=6** (sama dengan `datetime.weekday()`).
Jam pada policy (`start_time`/`end_time`) adalah waktu lokal sesuai
`policy.timezone` (default Asia/Jakarta), bukan UTC.

Semua fungsi di modul ini murni (tanpa I/O) supaya mudah diuji.
"""

from __future__ import annotations

import datetime as dt
from typing import Iterable, List, Optional, Set
from zoneinfo import ZoneInfo

from .models import MODE_PUBLIC, MODE_SCHEDULED

HARI_SINGKAT = ("Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min")
HARI_PANJANG = (
    "Senin",
    "Selasa",
    "Rabu",
    "Kamis",
    "Jumat",
    "Sabtu",
    "Minggu",
)

DEFAULT_TZ = "Asia/Jakarta"


# --------------------------------------------------------------------------- #
# Parsing & format
# --------------------------------------------------------------------------- #
def parse_days(raw: Optional[str]) -> Set[int]:
    """Parse string hari ("0,1,2") menjadi set int.

    Nilai di luar 0-6 dan potongan kosong diabaikan. Hasil kosong berarti
    kamera **tidak pernah** dibuka (default aman).
    """
    if not raw:
        return set()
    hasil: Set[int] = set()
    for potongan in str(raw).replace(";", ",").split(","):
        potongan = potongan.strip()
        if not potongan or not potongan.isdigit():
            continue
        nilai = int(potongan)
        if 0 <= nilai <= 6:
            hasil.add(nilai)
    return hasil


def format_days(raw: Optional[str]) -> str:
    """Ubah "0,1,2" menjadi "Sen, Sel, Rab" (untuk UI/log)."""
    days = parse_days(raw)
    if not days:
        return "-"
    if days == set(range(7)):
        return "Setiap hari"
    return ", ".join(HARI_SINGKAT[d] for d in sorted(days))


def parse_time(raw: Optional[str]) -> Optional[dt.time]:
    """Parse "08:00" / "8:00" / "08:00:00" menjadi `datetime.time`."""
    if raw is None:
        return None
    teks = str(raw).strip()
    if not teks:
        return None
    bagian = teks.split(":")
    try:
        jam = int(bagian[0])
        menit = int(bagian[1]) if len(bagian) > 1 else 0
    except (ValueError, IndexError):
        return None
    if not (0 <= jam <= 23 and 0 <= menit <= 59):
        return None
    return dt.time(hour=jam, minute=menit)


def format_time(value: Optional[dt.time]) -> str:
    return value.strftime("%H:%M") if value else "-"


# --------------------------------------------------------------------------- #
# Waktu lokal
# --------------------------------------------------------------------------- #
def policy_tz(policy) -> ZoneInfo:
    nama = (getattr(policy, "timezone", None) or DEFAULT_TZ).strip() or DEFAULT_TZ
    try:
        return ZoneInfo(nama)
    except Exception:  # pragma: no cover - tz tidak dikenal
        return ZoneInfo(DEFAULT_TZ)


def local_now(tz_name: Optional[str] = None, now: Optional[dt.datetime] = None) -> dt.datetime:
    """Waktu sekarang (aware) di zona waktu tertentu.

    `now` boleh naive (dianggap sudah waktu lokal zona itu) atau aware
    (dikonversi ke zona itu).
    """
    try:
        tz = ZoneInfo((tz_name or DEFAULT_TZ).strip() or DEFAULT_TZ)
    except Exception:  # pragma: no cover
        tz = ZoneInfo(DEFAULT_TZ)
    if now is None:
        return dt.datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


# --------------------------------------------------------------------------- #
# Inti: apakah terbuka sekarang
# --------------------------------------------------------------------------- #
def is_open(policy, now: Optional[dt.datetime] = None) -> bool:
    """Apakah kamera boleh diakses pada waktu tertentu?

    - policy None / tidak aktif          -> False
    - mode=public                        -> True
    - mode=scheduled                     -> cek hari + window jam
    - window melewati tengah malam (22:00-05:00) didukung
    """
    if policy is None:
        return False
    if not getattr(policy, "active", True):
        return False

    mode = getattr(policy, "mode", MODE_PUBLIC)
    if mode == MODE_PUBLIC:
        return True
    if mode != MODE_SCHEDULED:
        return False

    if policy.start_time is None or policy.end_time is None:
        return False

    lokal = local_now(getattr(policy, "timezone", None), now)
    return _in_window(policy, lokal)


def _in_window(policy, lokal: dt.datetime) -> bool:
    """Cek window jam terhadap hari (termasuk lintas tengah malam)."""
    days = parse_days(getattr(policy, "days", None))
    if not days:
        return False

    mulai: dt.time = policy.start_time
    selesai: dt.time = policy.end_time
    sekarang = lokal.time()
    hari_ini = lokal.weekday()

    if mulai == selesai:
        # window 24 jam pada hari terpilih
        return hari_ini in days

    if mulai < selesai:
        return hari_ini in days and mulai <= sekarang < selesai

    # lintas tengah malam, contoh 22:00-05:00
    if sekarang >= mulai:  # bagian malam dari hari ini
        return hari_ini in days
    if sekarang < selesai:  # bagian dini hari -> milik hari sebelumnya
        return ((hari_ini - 1) % 7) in days
    return False


def next_open(policy, now: Optional[dt.datetime] = None, max_hari: int = 14) -> Optional[dt.datetime]:
    """Waktu buka berikutnya (aware, zona waktu policy).

    - sedang terbuka      -> waktu sekarang
    - public tidak aktif / tidak ada hari dijadwalkan -> None
    """
    if policy is None or not getattr(policy, "active", True):
        return None

    lokal = local_now(getattr(policy, "timezone", None), now)
    if is_open(policy, now):
        return lokal
    if getattr(policy, "mode", MODE_PUBLIC) != MODE_SCHEDULED:
        return None
    if policy.start_time is None or policy.end_time is None:
        return None

    days = parse_days(getattr(policy, "days", None))
    if not days:
        return None

    tz = policy_tz(policy)
    for offset in range(max_hari + 1):
        tanggal = lokal.date() + dt.timedelta(days=offset)
        if tanggal.weekday() not in days:
            continue
        kandidat = dt.datetime.combine(tanggal, policy.start_time, tzinfo=tz)
        if kandidat > lokal:
            return kandidat
    return None


# --------------------------------------------------------------------------- #
# Ringkasan untuk UI/log
# --------------------------------------------------------------------------- #
def describe(policy) -> str:
    """Ringkasan manusiawi: "Publik 24 jam" / "Sen, Sel 08:00-17:00"."""
    if policy is None:
        return "Tidak ada kebijakan"
    if not getattr(policy, "active", True):
        return "Nonaktif"
    if getattr(policy, "mode", MODE_PUBLIC) == MODE_PUBLIC:
        return "Publik 24 jam"
    return "{} {}-{}".format(
        format_days(getattr(policy, "days", None)),
        format_time(policy.start_time),
        format_time(policy.end_time),
    )


def hours_until(waktu: Optional[dt.datetime], now: Optional[dt.datetime] = None) -> Optional[float]:
    """Selisih jam menuju `waktu` (untuk pesan "dibuka dalam X jam")."""
    if waktu is None:
        return None
    if now is None:
        now = waktu.__class__.now(waktu.tzinfo)
    elif now.tzinfo is None and waktu.tzinfo is not None:
        now = now.replace(tzinfo=waktu.tzinfo)
    return (waktu - now).total_seconds() / 3600.0
