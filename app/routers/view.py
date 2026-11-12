"""Halaman pantauan (viewer), API status, snapshot, dan override admin."""

from __future__ import annotations

from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from .. import access, audit, health, override, snapshots
from ..config import settings
from ..db import get_db
from ..deps import get_current_user, get_viewer_user
from ..models import Camera, User
from ..schedule import HARI_PANJANG, describe, is_open, local_now, next_open
from ..security import verify_password
from ..templating import templates

router = APIRouter(tags=["view"])


def _publisher_map(timeout: float = 2.0) -> dict:
    """Peta stream_key -> apakah MediaMTX punya publisher dengan video.

    Ini hanya separuh cerita: MediaMTX memakai `runOnDemand`, sehingga path yang
    sedang tidak ditonton tidak pernah "ready". Karena itu hasilnya dipakai
    sebagai *bukti hidup*, bukan bukti mati — lihat `_status_stream`.
    """
    try:
        resp = httpx.get(f"{settings.mediamtx_api}/v3/paths/list", timeout=timeout)
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except Exception:  # noqa: BLE001 - jangan gagalkan halaman karena API media
        return {}
    hasil = {}
    for item in items:
        nama = item.get("name")
        if not nama:
            continue
        tracks = item.get("tracks") or []
        hasil[nama] = bool(item.get("ready")) and bool(tracks)
    return hasil


def _status_stream(timeout: float = 2.0, boleh_probe=None) -> dict:
    """Peta stream_key -> state: `live` / `siap` / `offline`.

    `offline` hanya diberikan kalau probe aktif gagal (kamera/relay benar-benar
    tidak mengirim gambar). kondisi "tidak diketahui" dilaporkan `siap`, karena
    kamera runOnDemand yang sedang siaga bukan kamera yang mati.

    `boleh_probe` (callable stream_key -> bool) membatasi probe ke kamera yang
    memang sedang dalam jadwal buka — supaya kamera tertutup tidak ditarik
    terus-menerus hanya demi badge.
    """
    publisher = _publisher_map(timeout)
    hasil = {}
    for nama, aktif in publisher.items():
        izin = True if boleh_probe is None else bool(boleh_probe(nama))
        hasil[nama] = health.state(nama, aktif, boleh_probe=izin)
    return hasil


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


def camera_payload(kamera: Camera, user: Optional[User] = None, request: Request = None, now=None,
                   live: Optional[dict] = None) -> dict:
    """Bentuk data kamera untuk template dan /api/cameras/status."""
    policy = kamera.policy
    terbuka = is_open(policy, now)
    berikut = None if terbuka else next_open(policy, now)
    grant_sampai = override.deadline(request, user, kamera) if request is not None else None
    # live: peta stream_key -> state dari _status_stream(); None = tidak diketahui
    # -> anggap siap (jangan pernah mengklaim offline tanpa bukti).
    keadaan = health.SIAP if live is None else live.get(kamera.stream_key, health.SIAP)

    return {
        "slug": kamera.slug,
        "name": kamera.name,
        "location": kamera.location,
        "enabled": kamera.enabled,
        "open": terbuka,
        "live": keadaan == health.LIVE,
        "state": keadaan,
        "watchable": keadaan != health.OFFLINE,
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


def _izin_probe(kamera, sekarang):
    """Hanya probe kamera yang memang sedang boleh ditonton (jadwal buka).

    Kamera tertutup tidak perlu ditarik dari MediaMTX hanya demi badge status.
    """
    peta = {k.stream_key: is_open(k.policy, sekarang) for k in kamera}
    return lambda stream_key: peta.get(stream_key, False)


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
    user: Optional[User] = Depends(get_viewer_user),
    db: Session = Depends(get_db),
):
    sekarang = local_now(settings.tz_name)
    kamera = _daftar_kamera(db)
    live = _status_stream(boleh_probe=_izin_probe(kamera, sekarang))
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "cameras": [camera_payload(c, user, request, sekarang, live) for c in kamera],
            "sekarang": sekarang.strftime("%H:%M:%S"),
        },
    )


@router.get("/api/cameras/status")
def cameras_status(
    request: Request,
    user: Optional[User] = Depends(get_viewer_user),
    db: Session = Depends(get_db),
):
    sekarang = local_now(settings.tz_name)
    kamera = _daftar_kamera(db)
    live = _status_stream(boleh_probe=_izin_probe(kamera, sekarang))
    return {
        "now": sekarang.isoformat(),
        "is_admin": bool(user is not None and user.is_admin),
        "cameras": [camera_payload(c, user, request, sekarang, live) for c in kamera],
    }


@router.get("/api/snapshot/{slug}")
async def snapshot(
    slug: str,
    request: Request,
    user: Optional[User] = Depends(get_viewer_user),
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
