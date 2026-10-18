"""Halaman pantauan (viewer) + API status + snapshot."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import audit, snapshots
from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import Camera, User
from ..schedule import HARI_PANJANG, describe, is_open, local_now, next_open
from ..templating import templates

router = APIRouter(tags=["view"])


def _label_waktu(waktu) -> Optional[str]:
    if waktu is None:
        return None
    return "{} {} {}".format(
        HARI_PANJANG[waktu.weekday()],
        waktu.strftime("%d/%m"),
        waktu.strftime("%H:%M"),
    )


def camera_payload(kamera: Camera, now=None) -> dict:
    """Bentuk data kamera untuk template dan /api/cameras/status."""
    policy = kamera.policy
    terbuka = is_open(policy, now)
    berikut = None if terbuka else next_open(policy, now)
    return {
        "slug": kamera.slug,
        "name": kamera.name,
        "location": kamera.location,
        "enabled": kamera.enabled,
        "open": terbuka,
        "policy": describe(policy),
        "next_open": berikut.isoformat() if berikut else None,
        "next_open_label": _label_waktu(berikut),
        "stream_url": f"/stream/{kamera.slug}/index.m3u8",
        "snapshot_url": f"/api/snapshot/{kamera.slug}",
    }


def _daftar_kamera(db: Session):
    return (
        db.query(Camera)
        .filter(Camera.enabled.is_(True))
        .order_by(Camera.sort, Camera.name)
        .all()
    )


@router.get("/")
def dashboard(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sekarang = local_now(settings.tz_name)
    kamera = _daftar_kamera(db)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "cameras": [camera_payload(c, sekarang) for c in kamera],
            "sekarang": sekarang.strftime("%H:%M:%S"),
        },
    )


@router.get("/api/cameras/status")
def cameras_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sekarang = local_now(settings.tz_name)
    return {
        "now": sekarang.isoformat(),
        "cameras": [camera_payload(c, sekarang) for c in _daftar_kamera(db)],
    }


@router.get("/api/snapshot/{slug}")
async def snapshot(
    slug: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    kamera = db.query(Camera).filter(Camera.slug == slug).one_or_none()
    if kamera is None or not kamera.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kamera tidak ditemukan")

    if not is_open(kamera.policy):
        audit.record(
            db,
            request,
            audit.ACTION_SNAPSHOT_DENIED,
            user=user,
            camera=kamera,
            detail="di luar jadwal akses",
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Kamera tertutup di luar jadwal")

    try:
        data = await run_in_threadpool(snapshots.get_snapshot, kamera.stream_key)
    except snapshots.SnapshotError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Snapshot gagal: {exc}",
        ) from exc

    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )
