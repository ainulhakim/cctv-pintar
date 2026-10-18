"""Override jadwal akses oleh admin (per kamera, berbatas waktu).

Aturan:
- hanya role admin yang boleh minta override;
- wajib memasukkan password admin **milik akunnya sendiri**;
- grant berlaku per kamera dan kedaluwarsa (default 30 menit, `OVERRIDE_TTL`);
- setiap grant/gagal dicatat di `access_logs`.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional, Tuple

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings
from .models import ROLE_ADMIN
from .ratelimit import SlidingWindowLimiter

OVERRIDE_COOKIE = "cctv_override"
_SALT = "cctv-pintar-override"

# 5 percobaan password salah per 5 menit (per user+IP)
override_limiter = SlidingWindowLimiter(max_attempts=5, window_seconds=300)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=_SALT)


def grant(user_id: int, camera_id: int) -> str:
    """Token override untuk (user, kamera)."""
    return _serializer().dumps({"uid": int(user_id), "cid": int(camera_id)})


def read(token: str, max_age: Optional[int] = None) -> Optional[Tuple[int, int]]:
    """Baca (user_id, camera_id) dari token. None bila tidak valid/kedaluwarsa."""
    if not token:
        return None
    if max_age is None:
        max_age = settings.override_ttl
    try:
        data = _serializer().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    except Exception:  # pragma: no cover - defensif
        return None
    if not isinstance(data, dict):
        return None
    uid = data.get("uid")
    cid = data.get("cid")
    if not isinstance(uid, int) or not isinstance(cid, int):
        return None
    return uid, cid


def deadline(request, user, camera) -> Optional[dt.datetime]:
    """Waktu berakhirnya override aktif (UTC aware), atau None bila tidak ada."""
    if user is None or camera is None:
        return None
    if getattr(user, "role", None) != ROLE_ADMIN:
        return None
    token = request.cookies.get(OVERRIDE_COOKIE)
    if not token:
        return None
    try:
        data, ts = _serializer().loads(token, max_age=settings.override_ttl, return_timestamp=True)
    except (BadSignature, SignatureExpired):
        return None
    except Exception:  # pragma: no cover
        return None
    if not isinstance(data, dict):
        return None
    if data.get("uid") != user.id or data.get("cid") != camera.id:
        return None
    return ts + dt.timedelta(seconds=settings.override_ttl)


def aktif(request, user, camera) -> bool:
    """True bila user admin ini punya override yang masih berlaku untuk kamera itu."""
    return deadline(request, user, camera) is not None


def kunci_limiter(request, user) -> str:
    from . import audit  # hindari impor melingkar

    return f"{getattr(user, 'id', '-')}:{audit.client_ip(request) or 'unknown'}"
