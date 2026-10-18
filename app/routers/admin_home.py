"""Ringkasan panel admin."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import require_admin
from ..models import AccessLog, Camera, User, MODE_PUBLIC
from ..schedule import describe, is_open, local_now
from ..templating import templates

router = APIRouter(prefix="/admin", tags=["admin"])


def status_mediamtx(timeout: float = 3.0) -> dict:
    """Status path dari API MediaMTX. Gagal -> dict dengan 'error'.

    Catatan: kunci hasil memakai 'paths', bukan 'items', karena di template Jinja
    `mediamtx.items` akan ter-resolve ke method dict.items (bukan kunci).
    """
    try:
        resp = httpx.get(f"{settings.mediamtx_api}/v3/paths/list", timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - apa pun penyebabnya, tampilkan pesan
        return {"error": f"MediaMTX tidak dapat dihubungi ({exc.__class__.__name__})", "paths": []}

    paths = []
    for path in data.get("items", []):
        paths.append(
            {
                "name": path.get("name"),
                "ready": bool(path.get("ready")),
                "online": bool(path.get("online")),
                "tracks": ", ".join(path.get("tracks") or []),
                "readers": len(path.get("readers") or []),
            }
        )
    return {"error": None, "paths": sorted(paths, key=lambda x: x["name"] or "")}


def cek_disk(path: str = "/") -> dict:
    try:
        pakai = shutil.disk_usage(path)
    except OSError as exc:  # pragma: no cover
        return {"error": str(exc)}
    persen = round(pakai.used / pakai.total * 100, 1) if pakai.total else 0.0
    return {
        "total_gb": round(pakai.total / 1024**3, 1),
        "used_gb": round(pakai.used / 1024**3, 1),
        "free_gb": round(pakai.free / 1024**3, 1),
        "persen": persen,
    }


@router.get("/")
def admin_home(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    sekarang = local_now(settings.tz_name)
    sejak = datetime.utcnow() - timedelta(hours=24)

    kamera = db.query(Camera).order_by(Camera.sort, Camera.name).all()
    daftar_kamera = [
        {
            "slug": c.slug,
            "name": c.name,
            "enabled": c.enabled,
            "open": is_open(c.policy, sekarang),
            "policy": describe(c.policy),
        }
        for c in kamera
    ]

    total_user = db.scalar(select(func.count()).select_from(User)) or 0
    user_aktif = (
        db.scalar(select(func.count()).select_from(User).where(User.active.is_(True))) or 0
    )
    ditolak_24jam = (
        db.scalar(
            select(func.count())
            .select_from(AccessLog)
            .where(AccessLog.at >= sejak, AccessLog.action.in_(("stream_denied", "snapshot_denied")))
        )
        or 0
    )
    login_gagal_24jam = (
        db.scalar(
            select(func.count())
            .select_from(AccessLog)
            .where(AccessLog.at >= sejak, AccessLog.action == "login_failed")
        )
        or 0
    )

    return templates.TemplateResponse(
        request=request,
        name="admin/home.html",
        context={
            "user": user,
            "aktif": "/admin/",
            "sekarang": sekarang.strftime("%d/%m/%Y %H:%M:%S"),
            "cameras": daftar_kamera,
            "jumlah_publik": sum(1 for c in kamera if c.policy and c.policy.mode == MODE_PUBLIC),
            "total_user": total_user,
            "user_aktif": user_aktif,
            "ditolak_24jam": ditolak_24jam,
            "login_gagal_24jam": login_gagal_24jam,
            "mediamtx": status_mediamtx(),
            "disk": cek_disk("/"),
        },
    )
