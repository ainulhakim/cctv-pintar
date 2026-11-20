"""Panel admin: kontrol PTZ kamera Tapo (pan/tilt + preset).

Hanya role admin. Kredensial kamera tidak pernah dikirim ke browser:
browser hanya mengirim arah/aksi, server yang bicara ke kamera.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import audit, ptz
from ..db import get_db
from ..deps import require_admin
from ..models import Camera, User
from ..templating import templates

router = APIRouter(prefix="/admin", tags=["admin-ptz"])

AKSI_GERAK = "gerak"
AKSI_PRESET = "ke_preset"
AKSI_SIMPAN = "simpan_preset"


def _kamera(db: Session, slug: str) -> Camera:
    kamera = db.query(Camera).filter(Camera.slug == slug).one_or_none()
    if kamera is None or not kamera.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kamera tidak ditemukan")
    return kamera


@router.get("/ptz")
def halaman_ptz(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    kamera = (
        db.query(Camera)
        .filter(Camera.enabled.is_(True))
        .order_by(Camera.sort, Camera.name)
        .all()
    )
    kartu = []
    for k in kamera:
        kemampuan = ptz.kemampuan(k.stream_key)
        preset = []
        if kemampuan["didukung"]:
            try:
                preset = ptz.daftar_preset(k.stream_key)
            except Exception:  # noqa: BLE001 - preset bersifat pelengkap
                preset = []
        kartu.append({"kamera": k, "kemampuan": kemampuan, "preset": preset})

    return templates.TemplateResponse(
        request=request,
        name="admin/ptz.html",
        context={"user": user, "kartu": kartu, "aktif": "/admin/ptz"},
    )


@router.get("/api/ptz/{slug}")
def api_kemampuan(
    slug: str,
    segarkan: bool = False,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    kamera = _kamera(db, slug)
    return ptz.kemampuan(kamera.stream_key, segarkan=segarkan)


@router.post("/api/ptz/{slug}")
def api_aksi(
    slug: str,
    request: Request,
    aksi: str = Form(AKSI_GERAK),
    arah: str = Form(""),
    preset_id: str = Form(""),
    nama: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    kamera = _kamera(db, slug)
    kunci = f"ptz:{user.id or user.username}"
    if ptz.batas_gerak_terlampaui(kunci):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Terlalu banyak gerakan. Tunggu sebentar.",
        )

    try:
        if aksi == AKSI_GERAK:
            hasil = ptz.gerak(kamera.stream_key, arah)
        elif aksi == AKSI_PRESET:
            hasil = ptz.ke_preset(kamera.stream_key, preset_id)
        elif aksi == AKSI_SIMPAN:
            hasil = ptz.simpan_preset(kamera.stream_key, nama)
        else:
            raise ValueError(f"Aksi tidak dikenal: {aksi}")
    except ValueError as exc:
        audit.record(db, request, audit.ACTION_PTZ_FAILED, user=user, camera=kamera, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - kamera tidak menjawab / login gagal
        audit.record(
            db, request, audit.ACTION_PTZ_FAILED, user=user, camera=kamera,
            detail=f"{type(exc).__name__}: {str(exc)[:160]}",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Kamera tidak merespons: {type(exc).__name__}",
        ) from exc

    detail = f"aksi={aksi}"
    if arah:
        detail += f" arah={arah}"
    if preset_id:
        detail += f" preset={preset_id}"
    if nama:
        detail += f" nama={nama}"
    audit.record(db, request, audit.ACTION_PTZ, user=user, camera=kamera, detail=detail)
    return JSONResponse({"ok": True, "hasil": hasil})


@router.get("/api/ptz/{slug}/preset")
def api_preset(
    slug: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    kamera = _kamera(db, slug)
    try:
        return {"preset": ptz.daftar_preset(kamera.stream_key)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Kamera tidak merespons: {type(exc).__name__}",
        ) from exc
