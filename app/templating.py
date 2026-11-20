"""Instance Jinja2Templates yang dipakai bersama seluruh router."""

from __future__ import annotations

from fastapi.templating import Jinja2Templates

from .config import settings
from .ptz import konfigurasi as _ptz_konfigurasi

templates = Jinja2Templates(directory=str(settings.templates_dir))


def _ptz_siap() -> bool:
    """Menu PTZ hanya ditampilkan bila server benar-benar punya kamera ber-PTZ."""
    try:
        return bool(_ptz_konfigurasi().get("aktif"))
    except Exception:  # noqa: BLE001 - jangan gagalkan render menu
        return False


templates.env.globals.update(
    app_name="CCTV Pintar",
    tz_name=settings.tz_name,
    ptz_siap=_ptz_siap,
)
