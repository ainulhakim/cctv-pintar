"""CRUD jadwal akses per kamera (Fase 6.2) — inti requirement #2."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import require_admin
from ..forms import validasi_hari, validasi_mode
from ..models import MODE_PUBLIC, MODE_SCHEDULED, AccessPolicy, Camera, User
from ..schedule import HARI_PANJANG, describe, is_open, local_now, next_open, parse_time
from ..templating import templates
from .admin_common import catat, redirect_ke

router = APIRouter(prefix="/admin/policies", tags=["admin"])

ACTION_POLICY_UPDATE = "policy_update"


def _label(waktu) -> str:
    if waktu is None:
        return "—"
    return f"{HARI_PANJANG[waktu.weekday()]} {waktu.strftime('%d/%m %H:%M')}"


def _render(request: Request, user: User, db: Session):
    sekarang = local_now(settings.tz_name)
    kamera = db.query(Camera).order_by(Camera.sort, Camera.name).all()
    daftar = []
    for c in kamera:
        policy = c.policy
        daftar.append(
            {
                "id": c.id,
                "slug": c.slug,
                "name": c.name,
                "enabled": c.enabled,
                "mode": policy.mode if policy else MODE_PUBLIC,
                "days": policy.days if policy else "",
                "start": policy.start_time.strftime("%H:%M") if policy and policy.start_time else "",
                "end": policy.end_time.strftime("%H:%M") if policy and policy.end_time else "",
                "active": policy.active if policy else True,
                "ringkasan": describe(policy),
                "open": is_open(policy, sekarang),
                "next_open": _label(next_open(policy, sekarang)),
            }
        )
    return templates.TemplateResponse(
        request=request,
        name="admin/policies.html",
        context={
            "user": user,
            "aktif": "/admin/policies",
            "cameras": daftar,
            "hari": list(enumerate(HARI_PANJANG)),
            "sekarang": sekarang.strftime("%d/%m/%Y %H:%M"),
        },
    )


@router.get("")
def daftar(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _render(request, user, db)


@router.post("/{camera_id}")
def simpan(
    camera_id: int,
    request: Request,
    mode: str = Form(MODE_PUBLIC),
    days: List[str] = Form(default=[]),
    start: str = Form(""),
    end: str = Form(""),
    active: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    kamera = db.get(Camera, camera_id)
    if kamera is None:
        return redirect_ke("/admin/policies", err="Kamera tidak ditemukan.")

    mode_bersih = validasi_mode(mode)
    hari_bersih = validasi_hari(days)
    aktif = str(active).strip().lower() in {"1", "on", "true", "yes"}

    policy = kamera.policy
    if policy is None:
        policy = AccessPolicy(camera_id=kamera.id, timezone=settings.tz_name)
        db.add(policy)

    if mode_bersih == MODE_SCHEDULED:
        if not hari_bersih:
            return redirect_ke(
                "/admin/policies",
                err=f"Mode terjadwal butuh minimal satu hari ({kamera.name}).",
            )
        jam_mulai = parse_time(start)
        jam_selesai = parse_time(end)
        if jam_mulai is None or jam_selesai is None:
            return redirect_ke(
                "/admin/policies",
                err=f"Jam mulai/selesai tidak valid untuk {kamera.name} (contoh 08:00).",
            )
    else:
        jam_mulai = None
        jam_selesai = None
        hari_bersih = "0,1,2,3,4,5,6"

    policy.mode = mode_bersih
    policy.days = hari_bersih
    policy.start_time = jam_mulai
    policy.end_time = jam_selesai
    policy.timezone = settings.tz_name
    policy.active = aktif

    catat(db, request, ACTION_POLICY_UPDATE, user=user, camera=kamera, detail=describe(policy))
    return redirect_ke("/admin/policies", ok=f"Jadwal {kamera.name}: {describe(policy)}")
