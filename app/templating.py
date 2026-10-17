"""Instance Jinja2Templates yang dipakai bersama seluruh router."""

from __future__ import annotations

from fastapi.templating import Jinja2Templates

from .config import settings

templates = Jinja2Templates(directory=str(settings.templates_dir))
templates.env.globals.update(
    app_name="CCTV Pintar",
    tz_name=settings.tz_name,
)
