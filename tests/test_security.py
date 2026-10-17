"""Test util keamanan: hash password + token sesi."""

from __future__ import annotations

from app.security import (
    hash_password,
    read_session,
    sign_session,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_bukan_plaintext(self):
        h = hash_password("rahasia123")
        assert h != "rahasia123"
        assert h.startswith("$2")  # format bcrypt

    def test_hash_unik_per_pemanggilan(self):
        assert hash_password("sama") != hash_password("sama")

    def test_verify_benar(self):
        h = hash_password("<PASSWORD-KAMERA>")
        assert verify_password("<PASSWORD-KAMERA>", h) is True

    def test_verify_salah(self):
        h = hash_password("<PASSWORD-KAMERA>")
        assert verify_password("<PASSWORD-KAMERA>", h) is False
        assert verify_password("", h) is False

    def test_hash_korup_tidak_melempar(self):
        assert verify_password("apa saja", "bukan-hash") is False

    def test_password_kosong_ditolak(self):
        import pytest

        with pytest.raises(ValueError):
            hash_password("")

    def test_password_panjang_tidak_dipotong(self):
        """Password > 72 byte harus tetap unik di seluruh karakternya."""
        base = "x" * 80
        h1 = hash_password(base + "A")
        h2 = hash_password(base + "B")
        assert verify_password(base + "A", h1) is True
        assert verify_password(base + "B", h1) is False
        assert h1 != h2

    def test_password_unicode(self):
        h = hash_password("sandi-rahasia-üñî😀")
        assert verify_password("sandi-rahasia-üñî😀", h) is True


class TestSession:
    def test_roundtrip(self):
        token = sign_session(42)
        assert read_session(token) == 42

    def test_token_kadaluarsa_ditolak(self):
        token = sign_session(7)
        assert read_session(token, max_age=-1) is None

    def test_token_sampah_ditolak(self):
        assert read_session("token-palsu") is None
        assert read_session("") is None

    def test_token_dari_secret_lain_ditolak(self):
        from itsdangerous import URLSafeTimedSerializer

        lain = URLSafeTimedSerializer("secret-berbeda", salt="cctv-pintar-session")
        assert read_session(lain.dumps({"uid": 1})) is None
