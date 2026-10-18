"""Helper bersama untuk halaman admin: redirect + pesan flash."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import audit


def redirect_ke(path: str, ok: Optional[str] = None, err: Optional[str] = None) -> RedirectResponse:
    """Redirect 303 dengan pesan sukses/error di query string (pola POST-redirect-GET)."""
    params = {}
    if ok:
        params["ok"] = ok
    if err:
        params["err"] = err
    tujuan = path + ("?" + urlencode(params) if params else "")
    return RedirectResponse(tujuan, status_code=303)


def catat(db: Session, request: Request, action: str, user=None, camera=None, detail=None) -> None:
    audit.record(db, request, action, user=user, camera=camera, detail=detail)
