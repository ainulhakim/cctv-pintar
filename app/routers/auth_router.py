"""Halaman login & logout."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..db import get_db
from ..deps import get_current_user_optional
from ..models import User
from ..ratelimit import login_limiter
from ..security import sign_session, verify_password
from ..templating import templates

router = APIRouter(tags=["auth"])


def _safe_next(raw: Optional[str]) -> str:
    """Cegah open-redirect: hanya izinkan path internal."""
    if raw and raw.startswith("/") and not raw.startswith("//"):
        return raw
    return "/"


def _render_login(request: Request, error: Optional[str], next_url: str, username: str, status_code: int = 200):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": error, "next": next_url, "username": username},
        status_code=status_code,
    )


@router.get("/login")
def login_form(request: Request, next: str = "", db: Session = Depends(get_db)):
    if get_current_user_optional(request, db) is not None:
        return RedirectResponse("/", status_code=303)
    return _render_login(request, None, _safe_next(next), "")


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form(""),
    db: Session = Depends(get_db),
):
    username = (username or "").strip()
    ip = audit.client_ip(request) or "unknown"

    if login_limiter.is_blocked(ip):
        sisa = login_limiter.retry_after(ip)
        audit.record(db, request, audit.ACTION_LOGIN_BLOCKED, detail=f"ip={ip}")
        return _render_login(
            request,
            f"Terlalu banyak percobaan gagal. Coba lagi dalam {sisa} detik.",
            _safe_next(next),
            username,
            status_code=429,
        )

    user = (
        db.query(User).filter(User.username == username).one_or_none()
        if username
        else None
    )

    if user is None or not user.active or not verify_password(password, user.password_hash):
        login_limiter.record_failure(ip)
        audit.record(
            db,
            request,
            audit.ACTION_LOGIN_FAILED,
            user=user,
            detail="username=" + (username or "-"),
        )
        return _render_login(
            request,
            "Username atau password salah.",
            _safe_next(next),
            username,
            status_code=401,
        )

    login_limiter.reset(ip)
    audit.record(db, request, audit.ACTION_LOGIN_OK, user=user)

    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(
        key=settings.session_cookie,
        value=sign_session(user.id),
        max_age=settings.session_max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


def _logout_response() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(settings.session_cookie, path="/")
    response.delete_cookie("cctv_override", path="/")  # cabut override admin
    return response


@router.post("/logout")
def logout_post():
    return _logout_response()


@router.get("/logout")
def logout_get():
    return _logout_response()
