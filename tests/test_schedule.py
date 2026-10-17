"""Test logika jadwal — bagian paling rawan, wajib lengkap (Fase 4)."""

from __future__ import annotations

import datetime as dt

import pytest

from app.models import AccessPolicy, MODE_PUBLIC, MODE_SCHEDULED
from app.schedule import (
    describe,
    format_days,
    hours_until,
    is_open,
    local_now,
    next_open,
    parse_days,
    parse_time,
)

TZ = "Asia/Jakarta"

# 2026-10-19 = Senin (sesuai konvensi Senin=0)
SENIN = dt.datetime(2026, 10, 19, 10, 0)
MINGGU = dt.datetime(2026, 10, 25, 10, 0)


def policy(mode=MODE_PUBLIC, days="0,1,2,3,4,5,6", mulai=None, selesai=None,
           timezone=TZ, active=True, camera_id=1) -> AccessPolicy:
    return AccessPolicy(
        camera_id=camera_id,
        mode=mode,
        days=days,
        start_time=mulai,
        end_time=selesai,
        timezone=timezone,
        active=active,
    )


# --------------------------------------------------------------------------- #
# parse & format
# --------------------------------------------------------------------------- #
class TestParseDays:
    def test_parse_biasa(self):
        assert parse_days("1,2,3") == {1, 2, 3}

    def test_abaikan_nilai_tidak_valid(self):
        assert parse_days("0, 7, -1, x, 3") == {0, 3}

    def test_kosong_berarti_tidak_pernah(self):
        assert parse_days("") == set()
        assert parse_days(None) == set()

    def test_pemisah_spasi_atau_titik_koma(self):
        assert parse_days("0; 1; 2") == {0, 1, 2}

    def test_format_hari(self):
        assert format_days("0,1,2") == "Sen, Sel, Rab"
        assert format_days("0,1,2,3,4,5,6") == "Setiap hari"
        assert format_days("") == "-"


class TestParseTime:
    def test_format_biasa(self):
        assert parse_time("08:30") == dt.time(8, 30)

    @pytest.mark.parametrize("nilai", ["8:00", "08:00", "08:00:00", " 08:00 "])
    def test_varian_format(self, nilai):
        assert parse_time(nilai) == dt.time(8, 0)

    def test_tidak_valid(self):
        assert parse_time("25:00") is None
        assert parse_time("08:99") is None
        assert parse_time("abc") is None
        assert parse_time("") is None
        assert parse_time(None) is None


# --------------------------------------------------------------------------- #
# is_open
# --------------------------------------------------------------------------- #
class TestIsOpenPublic:
    def test_public_selalu_terbuka(self):
        p = policy(MODE_PUBLIC)
        for jam in (0, 6, 12, 23):
            assert is_open(p, SENIN.replace(hour=jam)) is True

    def test_tanpa_policy_tertutup(self):
        assert is_open(None, SENIN) is False

    def test_policy_nonaktif_tertutup(self):
        assert is_open(policy(MODE_PUBLIC, active=False), SENIN) is False

    def test_mode_tidak_dikenal_tertutup(self):
        assert is_open(policy("ngawur"), SENIN) is False


class TestIsOpenScheduled:
    def test_di_dalam_window(self):
        p = policy(MODE_SCHEDULED, days="0,1,2,3,4", mulai=dt.time(8), selesai=dt.time(17))
        assert is_open(p, SENIN.replace(hour=10)) is True
        assert is_open(p, SENIN.replace(hour=8)) is True       # inklusif awal
        assert is_open(p, SENIN.replace(hour=16, minute=59)) is True

    def test_di_luar_window(self):
        p = policy(MODE_SCHEDULED, days="0,1,2,3,4", mulai=dt.time(8), selesai=dt.time(17))
        assert is_open(p, SENIN.replace(hour=7, minute=59)) is False
        assert is_open(p, SENIN.replace(hour=17)) is False      # eksklusif akhir
        assert is_open(p, SENIN.replace(hour=23)) is False

    def test_hari_tidak_termasuk(self):
        p = policy(MODE_SCHEDULED, days="0,1,2,3,4", mulai=dt.time(8), selesai=dt.time(17))
        assert is_open(p, MINGGU) is False       # Minggu
        assert is_open(p, dt.datetime(2026, 10, 24, 10, 0)) is False  # Sabtu

    def test_tanpa_jam_tertutup(self):
        p = policy(MODE_SCHEDULED, days="0,1,2,3,4")
        assert is_open(p, SENIN) is False

    def test_tanpa_hari_tertutup(self):
        p = policy(MODE_SCHEDULED, days="", mulai=dt.time(8), selesai=dt.time(17))
        assert is_open(p, SENIN) is False

    def test_window_24_jam_pada_hari_terpilih(self):
        p = policy(MODE_SCHEDULED, days="5,6", mulai=dt.time(0), selesai=dt.time(0))
        assert is_open(p, dt.datetime(2026, 10, 24, 3, 0)) is True   # Sabtu
        assert is_open(p, SENIN) is False                            # Senin


class TestIsOpenOvernight:
    """Window 22:00-05:00 (lintas tengah malam)."""

    @pytest.fixture
    def p(self):
        # Senin & Selasa
        return policy(MODE_SCHEDULED, days="0,1", mulai=dt.time(22), selesai=dt.time(5))

    def test_malam_senin_terbuka(self, p):
        assert is_open(p, dt.datetime(2026, 10, 19, 23, 0)) is True

    def test_dini_hari_selasa_terbuka(self, p):
        assert is_open(p, dt.datetime(2026, 10, 20, 2, 0)) is True

    def test_siang_senin_tertutup(self, p):
        assert is_open(p, dt.datetime(2026, 10, 19, 12, 0)) is False

    def test_dini_hari_senin_tertutup(self, p):
        # dini hari Senin = milik malam Minggu (Minggu tidak dijadwalkan)
        assert is_open(p, dt.datetime(2026, 10, 19, 2, 0)) is False

    def test_batas_awal_inklusif_dan_akhir_eksklusif(self, p):
        assert is_open(p, dt.datetime(2026, 10, 19, 22, 0)) is True
        assert is_open(p, dt.datetime(2026, 10, 20, 4, 59)) is True
        assert is_open(p, dt.datetime(2026, 10, 20, 5, 0)) is False


class TestTimezone:
    def test_now_naive_dianggap_waktu_lokal(self):
        p = policy(MODE_SCHEDULED, days="0", mulai=dt.time(8), selesai=dt.time(17))
        assert is_open(p, dt.datetime(2026, 10, 19, 9, 0)) is True

    def test_now_utc_dikonversi_ke_zona_policy(self):
        p = policy(MODE_SCHEDULED, days="0", mulai=dt.time(8), selesai=dt.time(17))
        # 01:00 UTC = 08:00 WIB (Senin)
        utc = dt.datetime(2026, 10, 19, 1, 0, tzinfo=dt.timezone.utc)
        assert is_open(p, utc) is True
        assert is_open(p, dt.datetime(2026, 10, 18, 23, 0, tzinfo=dt.timezone.utc)) is False

    def test_zona_tidak_dikenal_jatuh_ke_default(self):
        p = policy(MODE_SCHEDULED, days="0", mulai=dt.time(8), selesai=dt.time(17),
                   timezone="Antarctica/TidakAda")
        assert is_open(p, dt.datetime(2026, 10, 19, 9, 0)) is True

    def test_local_now_aware(self):
        hasil = local_now(TZ, dt.datetime(2026, 10, 19, 1, 0, tzinfo=dt.timezone.utc))
        assert hasil.hour == 8
        assert hasil.tzinfo is not None


# --------------------------------------------------------------------------- #
# next_open
# --------------------------------------------------------------------------- #
class TestNextOpen:
    p = None

    def _p(self):
        return policy(MODE_SCHEDULED, days="0,1,2,3,4", mulai=dt.time(8), selesai=dt.time(17))

    def test_sedang_terbuka_kembalikan_sekarang(self):
        p = self._p()
        hasil = next_open(p, SENIN.replace(hour=10))
        assert hasil is not None
        assert hasil.hour == 10 and hasil.day == 19

    def test_setelah_jam_tutup_ke_hari_kerja_berikutnya(self):
        p = self._p()
        hasil = next_open(p, SENIN.replace(hour=18))
        assert (hasil.day, hasil.hour) == (20, 8)   # Selasa 08:00

    def test_dari_akhir_pekan_ke_senin(self):
        p = self._p()
        hasil = next_open(p, dt.datetime(2026, 10, 24, 12, 0))  # Sabtu
        assert (hasil.day, hasil.hour, hasil.weekday()) == (26, 8, 0)

    def test_window_malam_berikutnya(self):
        p = policy(MODE_SCHEDULED, days="2", mulai=dt.time(22), selesai=dt.time(5))
        # Rabu 12:00 -> Rabu 22:00
        hasil = next_open(p, dt.datetime(2026, 10, 21, 12, 0))
        assert (hasil.day, hasil.hour) == (21, 22)

    def test_public_terbuka_sekarang(self):
        p = policy(MODE_PUBLIC)
        assert next_open(p, SENIN).hour == 10

    def test_nonaktif_none(self):
        assert next_open(policy(MODE_PUBLIC, active=False), SENIN) is None

    def test_tidak_ada_hari_none(self):
        p = policy(MODE_SCHEDULED, days="", mulai=dt.time(8), selesai=dt.time(17))
        assert next_open(p, SENIN) is None

    def test_tanpa_jam_none(self):
        p = policy(MODE_SCHEDULED, days="0")
        assert next_open(p, SENIN) is None

    def test_hasil_aware_sesuai_zona(self):
        p = self._p()
        hasil = next_open(p, SENIN.replace(hour=18))
        assert hasil.tzinfo is not None
        assert str(hasil.tzinfo) == TZ or hasil.utcoffset() == dt.timedelta(hours=7)


class TestDescribe:
    def test_public(self):
        assert describe(policy(MODE_PUBLIC)) == "Publik 24 jam"

    def test_scheduled(self):
        p = policy(MODE_SCHEDULED, days="0,1,2", mulai=dt.time(8), selesai=dt.time(17))
        assert describe(p) == "Sen, Sel, Rab 08:00-17:00"

    def test_nonaktif(self):
        assert describe(policy(MODE_PUBLIC, active=False)) == "Nonaktif"

    def test_none(self):
        assert describe(None) == "Tidak ada kebijakan"


class TestHoursUntil:
    def test_hitung_jam(self):
        p = policy(MODE_SCHEDULED, days="0,1,2,3,4", mulai=dt.time(8), selesai=dt.time(17))
        target = next_open(p, SENIN.replace(hour=18))
        assert hours_until(target, local_now(TZ, SENIN.replace(hour=18))) == pytest.approx(14.0)

    def test_none(self):
        assert hours_until(None) is None
