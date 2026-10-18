"""Log akses + status sistem (Fase 6.4)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import AccessLog, Camera, User
from ..templating import templates
from .admin_home import cek_disk, status_mediamtx

router = APIRouter(prefix="/admin/logs", tags=["admin"])

AKSI = (
    "login_ok",
    "login_failed",
    "login_blocked",
    "stream_denied",
    "snapshot_denied",
    "policy_update",
    "camera_create",
    "camera_update",
    "camera_delete",
    "user_create",
    "user_update",
    "user_password",
    "user_delete",
)


@router.get("")
def daftar(
    request: Request,
    action: str = Query(""),
    camera: str = Query(""),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(AccessLog).order_by(AccessLog.id.desc())

    ada_filter = False
    if action:
        query = query.filter(AccessLog.action == action)
        ada_filter = True

    kamera_terpilih = None
    if camera:
        kamera_terpilih = db.query(Camera).filter(Camera.slug == camera).one_or_none()
        if kamera_terpilih is not None:
            query = query.filter(AccessLog.camera_id == kamera_terpilih.id)
            ada_filter = True

    baris = query.limit(limit).all()

    # lengkapi nama user & kamera tanpa N+1
    id_user = {b.user_id for b in baris if b.user_id}
    id_kamera = {b.camera_id for b in baris if b.camera_id}
    nama_user = {
        u.id: u.username
        for u in (db.query(User).filter(User.id.in_(id_user)).all() if id_user else [])
    }
    nama_kamera = {
        c.id: c.name
        for c in (db.query(Camera).filter(Camera.id.in_(id_kamera)).all() if id_kamera else [])
    }

    log = [
        {
            "id": b.id,
            "at": b.at,
            "action": b.action,
            "user": nama_user.get(b.user_id, "—"),
            "camera": nama_kamera.get(b.camera_id, "—"),
            "ip": b.ip or "—",
            "detail": b.detail or "",
        }
        for b in baris
    ]

    return templates.TemplateResponse(
        request=request,
        name="admin/logs.html",
        context={
            "user": user,
            "aktif": "/admin/logs",
            "log": log,
            "aksi": AKSI,
            "action": action,
            "camera": camera,
            "limit": limit,
            "ada_filter": ada_filter,
            "semua_kamera": [c.slug for c in db.query(Camera).order_by(Camera.name).all()],
            "mediamtx": status_mediamtx(),
            "disk": cek_disk("/"),
        },
    )
