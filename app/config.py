"""Konfigurasi aplikasi.

Semua nilai dibaca dari environment variable. Saat development, file `.env`
di root proyek dimuat otomatis (loader minimalis tanpa dependensi tambahan).
Di produksi nilai disuntikkan lewat systemd `EnvironmentFile`.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Loader .env sederhana. Tidak menimpa env yang sudah ada."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_dotenv(BASE_DIR / ".env")


def _bool_env(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    """Konfigurasi runtime aplikasi."""

    def __init__(self) -> None:
        self.base_dir = BASE_DIR
        self.env = os.getenv("APP_ENV", "development").strip().lower()

        self.secret_key = os.getenv("SECRET_KEY", "").strip()
        if not self.secret_key:
            if self.env == "production":
                raise RuntimeError(
                    "SECRET_KEY wajib diisi (APP_ENV=production). "
                    "Buat dengan: python -c \"import secrets;print(secrets.token_urlsafe(48))\""
                )
            # Nilai dev agar app tetap bisa dijalankan tanpa .env
            self.secret_key = "dev-insecure-secret-key-jangan-dipakai-di-produksi"

        self.database_url = os.getenv("DATABASE_URL", "").strip() or (
            "sqlite:///" + str(BASE_DIR / "data" / "cctv.db")
        )

        self.mediamtx_hls_base = os.getenv("MEDIAMTX_HLS_BASE", "http://127.0.0.1:8888").rstrip("/")
        self.mediamtx_api = os.getenv("MEDIAMTX_API", "http://127.0.0.1:9997").rstrip("/")

        self.tz_name = os.getenv("TZ_NAME", "Asia/Jakarta").strip() or "Asia/Jakarta"
        self.session_max_age = int(os.getenv("SESSION_MAX_AGE", "43200"))  # 12 jam
        self.session_cookie = os.getenv("SESSION_COOKIE", "cctv_session").strip() or "cctv_session"
        self.cookie_secure = _bool_env("COOKIE_SECURE", self.env == "production")

        self.admin_user = os.getenv("ADMIN_USER", "admin").strip() or "admin"
        self.admin_password = os.getenv("ADMIN_PASSWORD", "")

    # ---- path helpers ----
    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def templates_dir(self) -> Path:
        return self.base_dir / "app" / "templates"

    @property
    def static_dir(self) -> Path:
        return self.base_dir / "app" / "static"

    @property
    def data_dir(self) -> Path:
        return self.base_dir / "data"


settings = Settings()
