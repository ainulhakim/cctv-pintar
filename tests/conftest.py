"""Fixture pytest: database sementara + TestClient.

PENTING: environment diset SEBELUM `app` di-import, karena Settings dibaca
saat import (module-level singleton).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="cctv-pintar-test-"))
os.environ["APP_ENV"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-untuk-pytest"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["ADMIN_USER"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["COOKIE_SECURE"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import ROLE_ADMIN, ROLE_VIEWER, User  # noqa: E402
from app.ratelimit import login_limiter  # noqa: E402
from app.security import hash_password  # noqa: E402

ADMIN_PW = "admin123"
VIEWER_PW = "viewer123"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    login_limiter.reset_all()
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_user(db, username: str, password: str, role: str, active: bool = True) -> User:
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        active=active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_user(db) -> User:
    return _make_user(db, "admin", ADMIN_PW, ROLE_ADMIN)


@pytest.fixture
def viewer_user(db) -> User:
    return _make_user(db, "viewer", VIEWER_PW, ROLE_VIEWER)


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def login(client: TestClient, username: str, password: str, **kwargs):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
        **kwargs,
    )
