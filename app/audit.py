"""Helper audit log akses: IP klien asli + pencatatan ke access_logs."""

from __future__ import annotations

from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AccessLog

ACTION_LOGIN_OK = "login_ok"
ACTION_LOGIN_FAILED = "login_failed"
ACTION_LOGIN_BLOCKED = "login_blocked"
ACTION_STREAM_DENIED = "stream_denied"
ACTION_SNAPSHOT_DENIED = "snapshot_denied"


def client_ip(request: Request) -> Optional[str]:
    """IP klien sebenarnya (aplikasi berada di belakang Cloudflare)."""
    for header in ("cf-connecting-ip", "x-forwarded-for"):
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()
    return request.client.host if request.client else None


def record(
    db: Session,
    request: Request,
    action: str,
    user=None,
    camera=None,
    detail: Optional[str] = None,
    commit: bool = True,
) -> AccessLog:
    """Catat satu baris akses. `user`/`camera` boleh objek model atau None."""
    entri = AccessLog(
        user_id=getattr(user, "id", None),
        camera_id=getattr(camera, "id", None),
        action=action,
        detail=detail,
        ip=client_ip(request),
    )
    db.add(entri)
    if commit:
        db.commit()
    return entri
