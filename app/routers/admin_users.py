"""CRUD user (Fase 6.3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..forms import bersihkan_teks, normalize_username, validasi_password
from ..models import ROLE_ADMIN, ROLE_VIEWER, VALID_ROLES, User
from ..security import hash_password
from ..templating import templates
from .admin_common import catat, redirect_ke

router = APIRouter(prefix="/admin/users", tags=["admin"])

ACTION_USER_CREATE = "user_create"
ACTION_USER_UPDATE = "user_update"
ACTION_USER_PASSWORD = "user_password"
ACTION_USER_DELETE = "user_delete"


def _checkbox(nilai: str) -> bool:
    return str(nilai).strip().lower() in {"1", "on", "true", "yes"}


def _admin_aktif_lain(db: Session, user_id: int) -> int:
    """Jumlah admin aktif selain user_id."""
    return (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == ROLE_ADMIN, User.active.is_(True), User.id != user_id)
        )
        or 0
    )


def _render(request: Request, user: User, db: Session):
    pengguna = db.query(User).order_by(User.role, User.username).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/users.html",
        context={
            "user": user,
            "aktif": "/admin/users",
            "users": pengguna,
        },
    )


@router.get("")
def daftar(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _render(request, user, db)


@router.post("")
def buat(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    confirm: str = Form(""),
    full_name: str = Form(""),
    role: str = Form(ROLE_VIEWER),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    nama = normalize_username(username)
    if not nama:
        return redirect_ke("/admin/users", err="Username tidak valid (3-64 karakter: huruf, angka, . _ -).")
    if db.query(User).filter(User.username == nama).one_or_none() is not None:
        return redirect_ke("/admin/users", err=f"Username '{nama}' sudah dipakai.")
    if password != confirm:
        return redirect_ke("/admin/users", err="Konfirmasi password tidak sama.")
    pesan = validasi_password(password)
    if pesan:
        return redirect_ke("/admin/users", err=pesan)

    peran = role if role in VALID_ROLES else ROLE_VIEWER
    baru = User(
        username=nama,
        password_hash=hash_password(password),
        full_name=bersihkan_teks(full_name),
        role=peran,
        active=True,
    )
    db.add(baru)
    catat(db, request, ACTION_USER_CREATE, user=user, detail=f"{nama} ({peran})")
    return redirect_ke("/admin/users", ok=f"User '{nama}' dibuat sebagai {peran}.")


@router.post("/{user_id}/password")
def reset_password(
    user_id: int,
    request: Request,
    password: str = Form(""),
    confirm: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        return redirect_ke("/admin/users", err="User tidak ditemukan.")
    if password != confirm:
        return redirect_ke("/admin/users", err="Konfirmasi password tidak sama.")
    pesan = validasi_password(password)
    if pesan:
        return redirect_ke("/admin/users", err=pesan)

    target.password_hash = hash_password(password)
    catat(db, request, ACTION_USER_PASSWORD, user=user, detail=target.username)
    return redirect_ke("/admin/users", ok=f"Password '{target.username}' direset.")


@router.post("/{user_id}/role")
def ubah_role(
    user_id: int,
    request: Request,
    role: str = Form(ROLE_VIEWER),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        return redirect_ke("/admin/users", err="User tidak ditemukan.")
    peran = role if role in VALID_ROLES else ROLE_VIEWER

    if target.role == ROLE_ADMIN and peran != ROLE_ADMIN and _admin_aktif_lain(db, target.id) == 0:
        return redirect_ke("/admin/users", err="Tidak bisa menurunkan admin aktif terakhir.")

    target.role = peran
    catat(db, request, ACTION_USER_UPDATE, user=user, detail=f"{target.username} -> {peran}")
    return redirect_ke("/admin/users", ok=f"Role '{target.username}' menjadi {peran}.")


@router.post("/{user_id}/active")
def ubah_aktif(
    user_id: int,
    request: Request,
    active: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        return redirect_ke("/admin/users", err="User tidak ditemukan.")

    aktif_baru = _checkbox(active)
    if not aktif_baru and target.id == user.id:
        return redirect_ke("/admin/users", err="Tidak bisa menonaktifkan akun sendiri.")
    if not aktif_baru and target.role == ROLE_ADMIN and _admin_aktif_lain(db, target.id) == 0:
        return redirect_ke("/admin/users", err="Tidak bisa menonaktifkan admin aktif terakhir.")

    target.active = aktif_baru
    catat(db, request, ACTION_USER_UPDATE, user=user, detail=f"{target.username} aktif={aktif_baru}")
    return redirect_ke("/admin/users", ok=f"'{target.username}' {'diaktifkan' if aktif_baru else 'dinonaktifkan'}.")


@router.post("/{user_id}/delete")
def hapus(
    user_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        return redirect_ke("/admin/users", err="User tidak ditemukan.")
    if target.id == user.id:
        return redirect_ke("/admin/users", err="Tidak bisa menghapus akun sendiri.")
    if target.role == ROLE_ADMIN and _admin_aktif_lain(db, target.id) == 0:
        return redirect_ke("/admin/users", err="Tidak bisa menghapus admin aktif terakhir.")

    nama = target.username
    db.delete(target)
    catat(db, request, ACTION_USER_DELETE, user=user, detail=nama)
    return redirect_ke("/admin/users", ok=f"User '{nama}' dihapus.")
