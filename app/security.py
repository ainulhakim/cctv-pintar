"""Utilitas keamanan: hash password (bcrypt) dan token sesi (itsdangerous).

Catatan: kita memakai library `bcrypt` secara langsung, TANPA `passlib`.
passlib 1.7.4 membaca `bcrypt.__about__.__version__` yang sudah dihapus sejak
bcrypt 4.1, sehingga muncul "trapped error reading bcrypt version" di log.
Dengan memakai bcrypt langsung, dependensi lebih tipis dan bebas warning.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Optional

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings

_BCRYPT_MAX_BYTES = 72  # batas keras algoritma bcrypt

_SALT = "cctv-pintar-session"


def _password_bytes(password: str) -> bytes:
    """Konversi password ke bytes yang aman untuk bcrypt.

    bcrypt hanya memproses 72 byte pertama. Daripada memotong diam-diam,
    password yang lebih panjang di-pre-hash (SHA-256 + base64 = 44 byte)
    sehingga seluruh karakter tetap berpengaruh.
    """
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        return base64.b64encode(hashlib.sha256(raw).digest())
    return raw


def hash_password(password: str) -> str:
    """Hash password dengan bcrypt."""
    if not isinstance(password, str) or not password:
        raise ValueError("Password tidak boleh kosong")
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Verifikasi password terhadap hash. Tidak pernah melempar exception."""
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(_password_bytes(password), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        # hash korup / format tak dikenal -> anggap gagal
        return False


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=_SALT)


def sign_session(user_id: int) -> str:
    """Buat token sesi bertanda-tangan untuk user_id."""
    return _serializer().dumps({"uid": int(user_id)})


def read_session(token: str, max_age: Optional[int] = None) -> Optional[int]:
    """Baca user_id dari token. Kembalikan None jika tidak valid/kadaluarsa."""
    if not token:
        return None
    if max_age is None:
        max_age = settings.session_max_age
    try:
        data = _serializer().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    except Exception:  # pragma: no cover - defensif
        return None
    if not isinstance(data, dict):
        return None
    uid = data.get("uid")
    if not isinstance(uid, int):
        return None
    return uid


def generate_secret_key(nbytes: int = 48) -> str:  # pragma: no cover - util manual
    return secrets.token_urlsafe(nbytes)
