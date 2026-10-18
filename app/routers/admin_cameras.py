"""CRUD kamera (Fase 6.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import require_admin
from ..forms import bersihkan_teks, normalize_slug, normalize_stream_key
from ..models import MODE_PUBLIC, AccessLog, AccessPolicy, Camera, User
from ..schedule import describe, is_open, local_now
from ..templating import templates
from .admin_common import catat, redirect_ke

router = APIRouter(prefix="/admin/cameras", tags=["admin"])

ACTION_CAMERA_CREATE = "camera_create"
ACTION_CAMERA_UPDATE = "camera_update"
ACTION_CAMERA_DELETE = "camera_delete"


def _ambil(db: Session, camera_id: int) -> Camera:
    kamera = db.get(Camera, camera_id)
    if kamera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kamera tidak ditemukan")
    return kamera


def _checkbox(nilai: str) -> bool:
    return str(nilai).strip().lower() in {"1", "on", "true", "yes"}


def _render(request: Request, user: User, db: Session):
    sekarang = local_now(settings.tz_name)
    kamera = db.query(Camera).order_by(Camera.sort, Camera.name).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/cameras.html",
        context={
            "user": user,
            "aktif": "/admin/cameras",
            "cameras": [
                {
                    "id": c.id,
                    "slug": c.slug,
                    "name": c.name,
                    "location": c.location,
                    "stream_key": c.stream_key,
                    "enabled": c.enabled,
                    "sort": c.sort,
                    "policy": describe(c.policy),
                    "open": is_open(c.policy, sekarang),
                }
                for c in kamera
            ],
        },
    )


@router.get("")
def daftar(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _render(request, user, db)


@router.post("")
def buat(
    request: Request,
    slug: str = Form(""),
    name: str = Form(""),
    location: str = Form(""),
    stream_key: str = Form(""),
    sort: str = Form("0"),
    enabled: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    slug_bersih = normalize_slug(slug)
    key_bersih = normalize_stream_key(stream_key)
    nama = bersihkan_teks(name)

    if not slug_bersih:
        return redirect_ke("/admin/cameras", err="Slug tidak valid (huruf kecil, angka, tanda hubung).")
    if not nama:
        return redirect_ke("/admin/cameras", err="Nama kamera wajib diisi.")
    if not key_bersih:
        return redirect_ke("/admin/cameras", err="Stream key tidak valid (huruf/angka/._-).")
    if db.query(Camera).filter(Camera.slug == slug_bersih).one_or_none() is not None:
        return redirect_ke("/admin/cameras", err=f"Slug '{slug_bersih}' sudah dipakai.")

    try:
        urutan = int(sort)
    except ValueError:
        urutan = 0

    kamera = Camera(
        slug=slug_bersih,
        name=nama,
        location=bersihkan_teks(location, 255),
        stream_key=key_bersih,
        enabled=_checkbox(enabled),
        sort=urutan,
    )
    db.add(kamera)
    db.flush()
    # kamera baru default publik 24 jam
    db.add(
        AccessPolicy(
            camera_id=kamera.id,
            mode=MODE_PUBLIC,
            days="0,1,2,3,4,5,6",
            timezone=settings.tz_name,
            active=True,
        )
    )
    catat(db, request, ACTION_CAMERA_CREATE, user=user, camera=kamera, detail=kamera.slug)
    return redirect_ke("/admin/cameras", ok=f"Kamera '{kamera.name}' ditambahkan.")


@router.post("/{camera_id}")
def ubah(
    camera_id: int,
    request: Request,
    slug: str = Form(""),
    name: str = Form(""),
    location: str = Form(""),
    stream_key: str = Form(""),
    sort: str = Form("0"),
    enabled: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    kamera = _ambil(db, camera_id)
    slug_bersih = normalize_slug(slug)
    key_bersih = normalize_stream_key(stream_key)
    nama = bersihkan_teks(name)

    if not slug_bersih or not nama or not key_bersih:
        return redirect_ke("/admin/cameras", err="Data tidak valid. Periksa slug, nama, dan stream key.")

    bentrok = db.query(Camera).filter(Camera.slug == slug_bersih, Camera.id != camera_id).one_or_none()
    if bentrok is not None:
        return redirect_ke("/admin/cameras", err=f"Slug '{slug_bersih}' sudah dipakai kamera lain.")

    try:
        urutan = int(sort)
    except ValueError:
        urutan = kamera.sort

    kamera.slug = slug_bersih
    kamera.name = nama
    kamera.location = bersihkan_teks(location, 255)
    kamera.stream_key = key_bersih
    kamera.enabled = _checkbox(enabled)
    kamera.sort = urutan
    catat(db, request, ACTION_CAMERA_UPDATE, user=user, camera=kamera, detail=kamera.slug)
    return redirect_ke("/admin/cameras", ok=f"Kamera '{kamera.name}' diperbarui.")


@router.post("/{camera_id}/delete")
def hapus(
    camera_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    kamera = _ambil(db, camera_id)
    nama = kamera.name
    # SQLite tidak menegakkan ON DELETE secara default -> bersihkan manual
    db.query(AccessLog).filter(AccessLog.camera_id == kamera.id).update(
        {AccessLog.camera_id: None}, synchronize_session=False
    )
    db.query(AccessPolicy).filter(AccessPolicy.camera_id == kamera.id).delete(synchronize_session=False)
    db.delete(kamera)
    catat(db, request, ACTION_CAMERA_DELETE, user=user, detail=nama)
    return redirect_ke("/admin/cameras", ok=f"Kamera '{nama}' dihapus.")
