"""Entry point aplikasi FastAPI CCTV Pintar.

Fase 3: skeleton, config, model, autentikasi + halaman login.
Router pantauan (fase 5) dan admin (fase 6) akan di-include di sini.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import __version__
from .config import settings
from .db import Base, engine, get_db
from .deps import get_current_user, require_admin
from .models import Camera, User
from .routers import auth_router
from .templating import templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pastikan tabel ada (migrasi penuh menyusul bila skema berubah).
    Base.metadata.create_all(bind=engine)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="CCTV Pintar",
        version=__version__,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )

    app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
    app.include_router(auth_router.router)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """401 pada halaman HTML diarahkan ke /login; selain itu balas JSON."""
        wants_html = "text/html" in request.headers.get("accept", "")
        is_page = not request.url.path.startswith(("/api", "/stream"))
        if exc.status_code == status.HTTP_401_UNAUTHORIZED and wants_html and is_page:
            return RedirectResponse("/login", status_code=303)
        return JSONResponse(
            {"detail": exc.detail},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.get("/healthz", tags=["system"])
    def healthz():
        return {"ok": True, "version": __version__, "env": settings.env}

    @app.get("/", tags=["view"])
    def home(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        """Placeholder dashboard — digantikan grid kamera pada Fase 5."""
        total_cameras = db.scalar(select(func.count()).select_from(Camera)) or 0
        active_cameras = (
            db.scalar(
                select(func.count()).select_from(Camera).where(Camera.enabled.is_(True))
            )
            or 0
        )
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={"user": user, "total_cameras": total_cameras, "active_cameras": active_cameras},
        )

    @app.get("/admin/", tags=["admin"])
    def admin_home(request: Request, user: User = Depends(require_admin)):
        """Placeholder panel admin — diisi pada Fase 6."""
        return templates.TemplateResponse(
            request=request,
            name="admin/home.html",
            context={"user": user},
        )

    return app


app = create_app()
