#!/usr/bin/env python3
"""Set/ubah nilai di file .env tanpa merusak baris lain.

Contoh:
    python scripts/set_env.py APP_ENV=production COOKIE_SECURE=1
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"


def main(argv: list) -> int:
    if not argv:
        print("pemakaian: set_env.py KEY=VALUE [KEY=VALUE ...]")
        return 2

    pasangan = {}
    for item in argv:
        if "=" not in item:
            print(f"argumen tidak valid (butuh KEY=VALUE): {item}")
            return 2
        key, _, value = item.partition("=")
        pasangan[key.strip()] = value
    if not pasangan or not ENV.exists():
        print(f".env tidak ditemukan: {ENV}")
        return 1

    baris = ENV.read_text(encoding="utf-8").splitlines()
    terpakai = set()
    keluaran = []
    for isi in baris:
        bersih = isi.strip()
        if bersih and not bersih.startswith("#") and "=" in bersih:
            key = bersih.split("=", 1)[0].strip()
            if key in pasangan:
                keluaran.append(f"{key}={pasangan[key]}")
                terpakai.add(key)
                continue
        keluaran.append(isi)

    for key, value in pasangan.items():
        if key not in terpakai:
            keluaran.append(f"{key}={value}")

    ENV.write_text("\n".join(keluaran).rstrip("\n") + "\n", encoding="utf-8")
    print("diperbarui: " + ", ".join(sorted(pasangan)) + f" -> {ENV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
