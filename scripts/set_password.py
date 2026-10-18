#!/usr/bin/env python3
"""Ganti password user dari CLI — jalur pemulihan bila lupa password admin.

Contoh (di server rumah):

    cd ~/cctv-pintar
    NEW_PASSWORD='RahasiaBaru2026!' .venv/bin/python scripts/set_password.py admin
    # atau tanpa env (akan diminta memasukkan dua kali):
    .venv/bin/python scripts/set_password.py admin
    # buat admin baru kalau usernya belum ada:
    .venv/bin/python scripts/set_password.py admin2 --create-admin

Catatan: `scripts/seed.py` hanya membuat admin pertama dan TIDAK mengubah user
yang sudah ada, jadi untuk memulihkan akses pakai skrip ini.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.forms import MIN_PASSWORD_LEN, normalize_username  # noqa: E402
from app.models import ROLE_ADMIN, ROLE_VIEWER, VALID_ROLES, User  # noqa: E402
from app.security import hash_password  # noqa: E402


def ambil_password(dari_arg: str | None) -> str:
    if dari_arg:
        return dari_arg
    dari_env = os.getenv("NEW_PASSWORD")
    if dari_env:
        return dari_env
    pertama = getpass.getpass("Password baru: ")
    kedua = getpass.getpass("Ulangi password baru: ")
    if pertama != kedua:
        raise SystemExit("Password tidak sama.")
    return pertama


def main() -> int:
    parser = argparse.ArgumentParser(description="Ganti password user CCTV Pintar")
    parser.add_argument("username", help="username yang passwordnya diganti")
    parser.add_argument("--password", help="password baru (kalau kosong: env NEW_PASSWORD atau prompt)")
    parser.add_argument("--create-admin", action="store_true",
                        help="buat user baru sebagai admin kalau belum ada")
    parser.add_argument("--role", choices=list(VALID_ROLES), default=ROLE_VIEWER,
                        help="role saat pembuatan user baru (default viewer)")
    args = parser.parse_args()

    username = normalize_username(args.username)
    if not username:
        raise SystemExit("Username tidak valid (3-64 karakter: huruf, angka, . _ -).")

    password = ambil_password(args.password)
    if len(password) < MIN_PASSWORD_LEN:
        raise SystemExit(f"Password minimal {MIN_PASSWORD_LEN} karakter.")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).one_or_none()
        if user is None:
            if not args.create_admin:
                raise SystemExit(
                    f"User '{username}' tidak ada. Tambahkan --create-admin untuk membuatnya."
                )
            peran = ROLE_ADMIN if args.create_admin and args.role == ROLE_VIEWER else args.role
            user = User(username=username, password_hash=hash_password(password),
                        full_name="Administrator (dipulihkan)", role=peran, active=True)
            db.add(user)
            db.commit()
            print(f"BUAT  user '{username}' role={peran} (id={user.id})")
        else:
            user.password_hash = hash_password(password)
            user.active = True
            db.commit()
            print(f"GANTI password '{username}' (id={user.id}, role={user.role}) — akun diaktifkan")

        print("Selesai. Silakan login ulang di aplikasi.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
