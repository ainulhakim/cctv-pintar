#!/usr/bin/env python3
"""Seed data awal: user admin (+ opsional kamera contoh).

Idempotent: aman dijalankan berulang.

Contoh:
    python scripts/seed.py                       # hanya admin
    python scripts/seed.py --with-cameras        # admin + 2 kamera contoh
    ADMIN_USER=ali ADMIN_PASSWORD=rahasia python scripts/seed.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    DAYS_ALL,
    MODE_PUBLIC,
    ROLE_ADMIN,
    AccessPolicy,
    Camera,
    User,
)
from app.security import hash_password  # noqa: E402

CONTOH_KAMERA = [
    {
        "slug": "utara",
        "name": "Kamera Utara",
        "location": "Area Utara",
        "stream_key": "utara",
        "sort": 0,
    },
    {
        "slug": "selatan",
        "name": "Kamera Selatan",
        "location": "Area Selatan",
        "stream_key": "selatan",
        "sort": 1,
    },
]


def seed_admin(db) -> str:
    username = settings.admin_user
    existing = db.query(User).filter(User.username == username).one_or_none()
    if existing is not None:
        return f"SKIP  user '{username}' sudah ada (id={existing.id})"

    if not settings.admin_password:
        raise SystemExit(
            "ADMIN_PASSWORD kosong. Set di .env / environment sebelum menjalankan seed."
        )
    if len(settings.admin_password) < 8:
        raise SystemExit("ADMIN_PASSWORD minimal 8 karakter.")

    user = User(
        username=username,
        password_hash=hash_password(settings.admin_password),
        full_name="Administrator",
        role=ROLE_ADMIN,
        active=True,
    )
    db.add(user)
    db.commit()
    return f"BUAT  admin '{username}' (id={user.id})"


def seed_cameras(db) -> list:
    results = []
    for item in CONTOH_KAMERA:
        cam = db.query(Camera).filter(Camera.slug == item["slug"]).one_or_none()
        if cam is None:
            cam = Camera(**item, enabled=True)
            db.add(cam)
            db.flush()
            results.append(f"BUAT  kamera '{cam.slug}' (id={cam.id})")
        else:
            results.append(f"SKIP  kamera '{cam.slug}' sudah ada (id={cam.id})")

        if cam.policy is None:
            db.add(
                AccessPolicy(
                    camera_id=cam.id,
                    mode=MODE_PUBLIC,
                    days=DAYS_ALL,
                    timezone=settings.tz_name,
                    active=True,
                )
            )
            results.append(f"BUAT  policy publik untuk '{cam.slug}'")
    db.commit()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed database CCTV Pintar")
    parser.add_argument(
        "--with-cameras",
        action="store_true",
        help="Sekaligus buat 2 kamera contoh (utara, selatan) dengan akses publik 24 jam.",
    )
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        print(seed_admin(db))
        if args.with_cameras:
            for line in seed_cameras(db):
                print(line)
    finally:
        db.close()
    print("Selesai.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
