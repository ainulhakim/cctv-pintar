"""Proxy HLS ber-guard (requirement #1 dan #2).

Aturan akses (dipaksa di sini, bukan hanya di UI):
1. wajib sesi login        -> 401
2. kamera ada & aktif      -> 404
3. `is_open(policy)`       -> 403

Catatan perilaku MediaMTX (hasil probing): permintaan playlist pertama dibalas
302 ke `<url>?cookieCheck=1`. Kalau kita ikut mengirim cookie `cookieCheck`,
MediaMTX justru menandai playlist tanpa `?session=` dan permintaan variannya
gagal ("session not found"). Karena itu proxy ini **tidak pernah** meneruskan
cookie ke MediaMTX dan mengikuti redirect secara manual.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import Camera, User
from ..schedule import is_open

router = APIRouter(tags=["stream"])

_TIMEOUT = httpx.Timeout(10.0, read=30.0)
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_MAX_REDIRECT = 3

_ABS_URI_IN_TAG = re.compile(r'URI="(/[^"]*)"')


def _client() -> httpx.AsyncClient:
    """Klien HTTP tanpa cookie jar (selalu dibuat baru per hop)."""
    return httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False)


async def _fetch_upstream(path_with_query: str) -> httpx.Response:
    """Ambil dari MediaMTX, mengikuti redirect manual tanpa membawa cookie."""
    url = f"{settings.mediamtx_hls_base}{path_with_query}"
    for _ in range(_MAX_REDIRECT + 1):
        async with _client() as client:
            resp = await client.get(url)
        if resp.status_code in _REDIRECT_CODES:
            lokasi = resp.headers.get("location")
            if not lokasi:
                break
            url = urljoin(url, lokasi)
            continue
        return resp
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Terlalu banyak redirect dari MediaMTX",
    )


def rewrite_manifest(teks: str, slug: str) -> str:
    """Pastikan semua URI di manifest lewat proxy app (bukan langsung MediaMTX).

    MediaMTX memakai URI relatif (`video1_stream.m3u8`, `..._seg45.mp4?session=...`)
    yang otomatis tetap relatif terhadap URL proxy, jadi hanya URI absolut
    (berawalan `/`) yang perlu diawali `/stream/<slug>`.
    """
    prefix = f"/stream/{slug}"
    keluaran = []
    for baris in teks.splitlines():
        if baris.startswith("#"):
            keluaran.append(_ABS_URI_IN_TAG.sub(lambda m: f'URI="{prefix}{m.group(1)}"', baris))
        elif baris.strip():
            uri = baris.strip()
            keluaran.append(prefix + uri if uri.startswith("/") else uri)
        else:
            keluaran.append(baris)
    hasil = "\n".join(keluaran)
    return hasil + "\n" if teks.endswith("\n") else hasil


def _ambil_kamera(db: Session, slug: str) -> Camera:
    kamera = db.query(Camera).filter(Camera.slug == slug).one_or_none()
    if kamera is None or not kamera.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kamera tidak ditemukan")
    return kamera


def _wajib_terbuka(db: Session, request: Request, kamera: Camera, user: User, action: str) -> None:
    if is_open(kamera.policy):
        return
    audit.record(
        db,
        request,
        action,
        user=user,
        camera=kamera,
        detail="di luar jadwal akses",
    )
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Kamera tertutup di luar jadwal")


@router.get("/stream/{slug}/{path:path}")
async def stream_proxy(
    slug: str,
    path: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    kamera = _ambil_kamera(db, slug)
    _wajib_terbuka(db, request, kamera, user, audit.ACTION_STREAM_DENIED)

    query = request.url.query
    upstream_path = f"/{kamera.stream_key}/{path}" + (f"?{query}" if query else "")

    try:
        resp = await _fetch_upstream(upstream_path)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MediaMTX tidak dapat dihubungi ({exc.__class__.__name__})",
        ) from exc

    if resp.status_code == status.HTTP_404_NOT_FOUND:
        raise HTTPException(status_code=404, detail="Berkas tidak ditemukan di MediaMTX")
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MediaMTX membalas {resp.status_code}",
        )

    content_type = resp.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
    body = resp.content

    if path.endswith(".m3u8") or "mpegurl" in content_type:
        body = rewrite_manifest(body.decode("utf-8", "replace"), slug).encode("utf-8")
        content_type = "application/vnd.apple.mpegurl"

    return Response(
        content=body,
        media_type=content_type or "application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )
