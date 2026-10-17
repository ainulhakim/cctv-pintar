#!/usr/bin/env python3
"""Smoke test end-to-end lewat HTTP nyata (uvicorn dijalankan di thread).

Dipakai untuk memverifikasi deploy tanpa perlu systemd:

    python scripts/smoke.py

Prasyarat: database sudah di-seed (lihat scripts/seed.py) dan
ADMIN_USER / ADMIN_PASSWORD tersedia di environment atau .env.

Exit code 0 bila semua langkah lolos.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import create_app  # noqa: E402

HOST = os.getenv("SMOKE_HOST", "127.0.0.1")
PORT = int(os.getenv("SMOKE_PORT", "8091"))
BASE = f"http://{HOST}:{PORT}"

hasil: list[tuple[bool, str]] = []


def cek(nama: str, kondisi: bool, detail: str = "") -> None:
    hasil.append((kondisi, nama + (f" — {detail}" if detail else "")))
    print(("  OK   " if kondisi else "  GAGAL") + f"  {nama}" + (f" ({detail})" if detail else ""))


def jalankan_server() -> uvicorn.Server:
    config = uvicorn.Config(create_app(), host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    return server


def tunggu_siap(timeout: float = 20.0) -> bool:
    batas = time.time() + timeout
    while time.time() < batas:
        try:
            httpx.get(f"{BASE}/healthz", timeout=1.0)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def main() -> int:
    server = jalankan_server()
    if not tunggu_siap():
        print("GAGAL: server tidak siap dalam 20 detik")
        return 2

    try:
        with httpx.Client(base_url=BASE, timeout=10.0, follow_redirects=False) as c:
            r = c.get("/healthz")
            cek("/healthz 200 + ok", r.status_code == 200 and r.json().get("ok") is True, str(r.status_code))

            r = c.get("/login")
            cek("halaman login tampil", r.status_code == 200 and "Masuk" in r.text, str(r.status_code))

            r = c.get("/")
            cek("tanpa sesi -> 401", r.status_code == 401, str(r.status_code))

            r = c.get("/", headers={"accept": "text/html"})
            cek("tanpa sesi (browser) -> redirect /login",
                r.status_code == 303 and r.headers.get("location") == "/login",
                f"{r.status_code} {r.headers.get('location')}")

            if not settings.admin_password:
                cek("kredensial admin tersedia", False, "ADMIN_PASSWORD kosong")
            else:
                r = c.post("/login", data={"username": settings.admin_user, "password": settings.admin_password})
                cek("login admin -> 303", r.status_code == 303, str(r.status_code))
                cek("cookie sesi ter-set", "cctv_session" in r.headers.get("set-cookie", ""))

                r = c.get("/", headers={"accept": "text/html"})
                cek("dashboard terbuka setelah login", r.status_code == 200, str(r.status_code))

                r = c.get("/admin/", headers={"accept": "text/html"})
                cek("panel admin terbuka untuk admin", r.status_code == 200, str(r.status_code))

                r = c.post("/logout")
                cek("logout -> redirect /login", r.status_code == 303 and r.headers.get("location") == "/login")
                r = c.get("/")
                cek("sesi hilang setelah logout", r.status_code == 401, str(r.status_code))

            for nama in ("X-Frame-Options", "X-Content-Type-Options"):
                r = c.get("/healthz")
                cek(f"header {nama}", bool(r.headers.get(nama)))
    finally:
        server.should_exit = True
        time.sleep(0.5)

    gagal = [n for ok, n in hasil if not ok]
    print()
    print(f"{len(hasil) - len(gagal)}/{len(hasil)} pemeriksaan lolos")
    if gagal:
        print("Yang gagal:")
        for n in gagal:
            print(" -", n)
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
