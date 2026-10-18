"""Halaman pantauan (viewer), API status, snapshot, dan override admin."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from .. import access, audit, override, snapshots
from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import Camera, User
from ..schedule import HARI_PANJANG, describe, is_open, local_now, next_open
from ..security import verify_password
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


def _label_override(waktu) -> Optional[str]:
    """Jam berakhirnya override dalam zona waktu aplikasi."""
    if waktu is None:
        return None
    lokal = local_now(settings.tz_name, waktu)
    return lokal.strftime("%H:%M")


def camera_payload(kamera: Camera, user: Optional[User] = None, request: Request = None, now=None) -> dict:
    """Bentuk data kamera untuk template dan /api/cameras/status."""
    policy = kamera.policy
    terbuka = is_open(policy, now)
    berikut = None if terbuka else next_open(policy, now)
    grant_sampai = override.deadline(request, user, kamera) if request is not None else None

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
        # override admin (hanya relevan saat kamera tertutup)
        "override_active": grant_sampai is not None,
        "override_until": _label_override(grant_sampai),
        "can_override": bool(user is not None and user.is_admin and not terbuka),
    }


def _daftar_kamera(db: Session):
    return (
        db.query(Camera)
        .filter(Camera.enabled.is_(True))
        .order_by(Camera.sort, Camera.name)
        .all()
    )


def _ambil_kamera(db: Session, slug: str) -> Camera:
    kamera = db.query(Camera).filter(Camera.slug == slug).one_or_none()
    if kamera is None or not kamera.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kamera tidak ditemukan")
    return kamera


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
            "cameras": [camera_payload(c, user, request, sekarang) for c in kamera],
            "sekarang": sekarang.strftime("%H:%M:%S"),
        },
    )


@router.get("/api/cameras/status")
def cameras_status(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sekarang = local_now(settings.tz_name)
    return {
        "now": sekarang.isoformat(),
        "is_admin": bool(user.is_admin),
        "cameras": [camera_payload(c, user, request, sekarang) for c in _daftar_kamera(db)],
    }


@router.get("/api/snapshot/{slug}")
async def snapshot(
    slug: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    kamera = _ambil_kamera(db, slug)

    if not access.boleh_akses(request, user, kamera):
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


@router.post("/api/cameras/{slug}/override")
def override_kamera(
    slug: str,
    request: Request,
    password: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Buka kamera tertutup untuk sementara — hanya admin, wajib password sendiri."""
    kamera = _ambil_kamera(db, slug)

    if not user.is_admin:
        audit.record(
            db,
            request,
            audit.ACTION_OVERRIDE_FAILED,
            user=user,
            camera=kamera,
            detail="bukan admin",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya admin yang boleh membuka kamera tertutup.",
        )

    if is_open(kamera.policy):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kamera sedang terbuka sesuai jadwal.",
        )

    kunci = override.kunci_limiter(request, user)
    if override.override_limiter.is_blocked(kunci):
        sisa = override.override_limiter.retry_after(kunci)
        audit.record(
            db,
            request,
            audit.ACTION_OVERRIDE_BLOCKED,
            user=user,
            camera=kamera,
            detail=f"percobaan berlebih, sisa {sisa}s",
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Terlalu banyak percobaan. Coba lagi dalam {sisa} detik.",
        )

    if not verify_password(password, user.password_hash):
        override.override_limiter.record_failure(kunci)
        audit.record(
            db,
            request,
            audit.ACTION_OVERRIDE_FAILED,
            user=user,
            camera=kamera,
            detail="password salah",
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Password salah.")

    override.override_limiter.reset(kunci)
    menit = max(1, settings.override_ttl // 60)
    audit.record(
        db,
        request,
        audit.ACTION_OVERRIDE_GRANTED,
        user=user,
        camera=kamera,
        detail=f"berlaku {menit} menit",
    )

    response = JSONResponse(
        {"ok": True, "slug": kamera.slug, "override_seconds": settings.override_ttl}
    )
    response.set_cookie(
        key=override.OVERRIDE_COOKIE,
        value=override.grant(user.id, kamera.id),
        max_age=settings.override_ttl,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return response
