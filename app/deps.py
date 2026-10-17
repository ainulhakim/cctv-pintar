"""FastAPI dependencies: user terautentikasi dan guard role."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User
from .security import read_session


def get_current_user_optional(
    request: Request, db: Session = Depends(get_db)
) -> Optional[User]:
    """Kembalikan User bila cookie sesi valid dan user aktif, selain itu None."""
    token = request.cookies.get(settings.session_cookie)
    if not token:
        return None
    uid = read_session(token, max_age=settings.session_max_age)
    if uid is None:
        return None
    user = db.get(User, uid)
    if user is None or not user.active:
        return None
    return user


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    """Wajib login. 401 bila tidak ada sesi valid."""
    user = get_current_user_optional(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Perlu login",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Wajib role admin. 403 bila bukan admin."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses khusus admin",
        )
    return user
