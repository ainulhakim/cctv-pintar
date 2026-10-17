"""Test rate limiter login (unit + integrasi lewat HTTP)."""

from __future__ import annotations

from app.ratelimit import SlidingWindowLimiter


class TestSlidingWindow:
    def test_belum_diblokir_sebelum_batas(self):
        lim = SlidingWindowLimiter(max_attempts=3, window_seconds=60)
        for _ in range(2):
            lim.record_failure("ip", now=1000)
        assert lim.is_blocked("ip", now=1000) is False

    def test_diblokir_setelah_batas(self):
        lim = SlidingWindowLimiter(max_attempts=3, window_seconds=60)
        for _ in range(3):
            lim.record_failure("ip", now=1000)
        assert lim.is_blocked("ip", now=1000) is True

    def test_terbuka_lagi_setelah_window(self):
        lim = SlidingWindowLimiter(max_attempts=3, window_seconds=60)
        for _ in range(3):
            lim.record_failure("ip", now=1000)
        assert lim.is_blocked("ip", now=1061) is False

    def test_retry_after(self):
        lim = SlidingWindowLimiter(max_attempts=2, window_seconds=60)
        lim.record_failure("ip", now=1000)
        lim.record_failure("ip", now=1000)
        assert lim.retry_after("ip", now=1000) == 60
        assert lim.retry_after("ip", now=1030) == 30
        assert lim.retry_after("ip", now=1061) == 0

    def test_reset_setelah_sukses(self):
        lim = SlidingWindowLimiter(max_attempts=2, window_seconds=60)
        lim.record_failure("ip", now=1000)
        lim.record_failure("ip", now=1000)
        lim.reset("ip")
        assert lim.is_blocked("ip", now=1000) is False

    def test_kunci_terpisah_per_ip(self):
        lim = SlidingWindowLimiter(max_attempts=2, window_seconds=60)
        for _ in range(2):
            lim.record_failure("1.1.1.1", now=1000)
        assert lim.is_blocked("1.1.1.1", now=1000) is True
        assert lim.is_blocked("2.2.2.2", now=1000) is False

    def test_catatan_lama_dibersihkan(self):
        lim = SlidingWindowLimiter(max_attempts=5, window_seconds=60)
        lim.record_failure("ip", now=1000)
        lim.is_blocked("ip", now=2000)
        assert lim.keys_count() == 0


class TestLoginRateLimitHTTP:
    def test_6_percobaan_gagal_diblokir_429(self, client, admin_user):
        from tests.conftest import ADMIN_PW, login

        for _ in range(5):
            assert login(client, "admin", "salah").status_code == 401
        # percobaan ke-6 diblokir walau password benar
        resp = login(client, "admin", ADMIN_PW)
        assert resp.status_code == 429
        assert "Terlalu banyak percobaan" in resp.text

    def test_login_sukses_mereset_hitungan(self, client, admin_user):
        from tests.conftest import ADMIN_PW, login
        from app.ratelimit import login_limiter

        for _ in range(4):
            login(client, "admin", "salah")
        assert login(client, "admin", ADMIN_PW).status_code == 303
        assert login_limiter.is_blocked("testclient") is False
        # setelah reset, percobaan gagal lagi masih 401 (bukan 429)
        assert login(client, "admin", "salah").status_code == 401
