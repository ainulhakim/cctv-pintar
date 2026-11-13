"""Halaman Rekaman — daftar & pemutar segmen rekaman CCTV (Fase 7).

Rekaman disimpan recorder ffmpeg sebagai segmen MPEG-TS di volume berkuota
(`/srv/cctv-rec/<kamera>/YYYYmmdd-HHMMSS_sub.ts`). Modul ini hanya MEMBACA
berkas itu: tidak merekam, tidak menghapus (recycler yang mengurus kuota).

Endpoint:
  GET /admin/recordings              -> daftar segmen (filter kamera + tanggal)
  GET /admin/recordings/play/<..>    -> pemutar satu segmen (HTTP range lewat
                                        FileResponse supaya bisa di-seek)
  GET /admin/recordings/file/<..>    -> berkas mentah, untuk unduh/putar langsung

Akses: login admin. Setiap pemutaran/unduhan tercatat di access_logs.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import require_admin
from ..models import Camera, User
from ..templating import templates
from .. import audit

router = APIRouter(prefix="/admin/recordings", tags=["admin"])

# Nama berkas yang boleh diakses: <YYYYmmdd>-<HHMMSS>_<quality>.<ext>
POLA_BERKAS = re.compile(r"^(\d{8})-(\d{6})_([A-Za-z0-9]+)\.(ts|mp4|mkv|mov)$")
EKSTENSI = {".ts", ".mp4", ".mkv", ".mov"}


def root_rekaman() -> Path:
    """Folder akar rekaman (default /srv/cctv-rec, bisa dioverride lewat env)."""
    import os

    return Path(os.getenv("RECORD_ROOT", "/srv/cctv-rec")).resolve()


def _slug_aman(slug: str) -> str:
    """Cegah path traversal: hanya huruf/angka/tanda hubung/garis bawah."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", slug or ""):
        raise HTTPException(status_code=400, detail="Nama kamera tidak valid")
    return slug


def _berkas_aman(slug: str, nama: str) -> Path:
    """Resolusi path berkas rekaman + pastikan tidak keluar dari folder kamera."""
    slug = _slug_aman(slug)
    if not POLA_BERKAS.match(nama or ""):
        raise HTTPException(status_code=400, detail="Nama berkas tidak valid")
    dasar = root_rekaman() / slug
    path = (dasar / nama).resolve()
    if dasar.resolve() not in path.parents:
        raise HTTPException(status_code=400, detail="Path tidak valid")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Berkas rekaman tidak ditemukan")
    return path


def _scan_kamera(slug: str) -> List[Dict[str, object]]:
    """Daftar segmen satu kamera, terbaru di atas."""
    folder = root_rekaman() / slug
    if not folder.is_dir():
        return []

    hasil: List[Dict[str, object]] = []
    try:
        for path in folder.iterdir():
            if path.suffix.lower() not in EKSTENSI:
                continue
            m = POLA_BERKAS.match(path.name)
            if not m:
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            tanggal, jam = m.group(1), m.group(2)
            try:
                mulai = dt.datetime.strptime(f"{tanggal}{jam}", "%Y%m%d%H%M%S")
            except ValueError:
                continue
            hasil.append(
                {
                    "nama": path.name,
                    "mulai": mulai,
                    "tanggal": f"{tanggal[:4]}-{tanggal[4:6]}-{tanggal[6:]}",
                    "jam": f"{jam[:2]}:{jam[2:4]}:{jam[4:]}",
                    "ukuran": st.st_size,
                    "ukuran_mb": round(st.st_size / (1024 * 1024), 1),
                    "mtime": st.st_mtime,
                }
            )
    except OSError:
        return []
    hasil.sort(key=lambda r: r["mulai"], reverse=True)  # type: ignore[arg-type]
    return hasil


def _ringkas(segmen: List[Dict[str, object]]) -> Dict[str, object]:
    total = sum(int(s["ukuran"]) for s in segmen)
    return {
        "jumlah": len(segmen),
        "total_gb": round(total / (1024 ** 3), 2),
        "total_mb": round(total / (1024 ** 2), 1),
        "pertama": segmen[-1]["mulai"] if segmen else None,
        "terakhir": segmen[0]["mulai"] if segmen else None,
    }


@router.get("")
def daftar(
    request: Request,
    kamera: str = Query(""),
    tanggal: str = Query(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    kamera_semua = db.query(Camera).order_by(Camera.name).all()
    slug_tersedia = [c.slug for c in kamera_semua]

    # default: semua kamera yang punya folder rekaman
    if kamera and kamera not in slug_tersedia:
        kamera = ""

    dipilih = [kamera] if kamera else slug_tersedia
    per_kamera: Dict[str, List[Dict[str, object]]] = {}
    for slug in dipilih:
        per_kamera[slug] = _scan_kamera(slug)

    # filter tanggal (YYYY-MM-DD) kalau diisi
    if tanggal:
        for slug in list(per_kamera):
            per_kamera[slug] = [
                s for s in per_kamera[slug] if s["tanggal"] == tanggal
            ]

    semua_segmen = [s for daftar_ in per_kamera.values() for s in daftar_]
    ringkasan = _ringkas(semua_segmen)

    # daftar tanggal yang tersedia (untuk saran filter)
    tanggal_tersedia = sorted(
        {str(s["tanggal"]) for slug in slug_tersedia for s in _scan_kamera(slug)},
        reverse=True,
    )[:30]

    return templates.TemplateResponse(
        request=request,
        name="admin/recordings.html",
        context={
            "user": user,
            "aktif": "/admin/recordings",
            "kamera_semua": kamera_semua,
            "kamera": kamera,
            "tanggal": tanggal,
            "tanggal_tersedia": tanggal_tersedia,
            "per_kamera": per_kamera,
            "ringkasan": ringkasan,
            "root": str(root_rekaman()),
        },
    )


@router.get("/play/{slug}/{nama}")
def play(
    request: Request,
    slug: str,
    nama: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    path = _berkas_aman(slug, nama)
    kamera = db.query(Camera).filter(Camera.slug == slug).one_or_none()
    audit.record(
        db, request, "recording_play", user=user, camera=kamera, detail=nama[:120]
    )

    m = POLA_BERKAS.match(nama)
    tanggal, jam = m.group(1), m.group(2)  # type: ignore[union-attr]
    semua = _scan_kamera(slug)
    idx = next((i for i, s in enumerate(semua) if s["nama"] == nama), None)
    sebelumnya = semua[idx + 1] if idx is not None and idx + 1 < len(semua) else None
    berikutnya = semua[idx - 1] if idx is not None and idx > 0 else None

    return templates.TemplateResponse(
        request=request,
        name="admin/recording_play.html",
        context={
            "user": user,
            "aktif": "/admin/recordings",
            "slug": slug,
            "nama": nama,
            "kamera": kamera,
            "ukuran_mb": round(path.stat().st_size / (1024 * 1024), 1),
            "tanggal": f"{tanggal[:4]}-{tanggal[4:6]}-{tanggal[6:]}",
            "jam": f"{jam[:2]}:{jam[2:4]}:{jam[4:]}",
            "sebelumnya": sebelumnya,
            "berikutnya": berikutnya,
            "mime": "video/mp2t" if nama.lower().endswith(".ts") else "video/mp4",
        },
    )


@router.get("/file/{slug}/{nama}")
def file_mentah(
    request: Request,
    slug: str,
    nama: str,
    unduh: int = Query(0, ge=0, le=1),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Berkas rekaman dengan dukungan HTTP range (bisa di-seek pemutar video)."""
    path = _berkas_aman(slug, nama)
    kamera = db.query(Camera).filter(Camera.slug == slug).one_or_none()
    audit.record(
        db,
        request,
        "recording_download" if unduh else "recording_stream",
        user=user,
        camera=kamera,
        detail=nama[:120],
    )
    media = "video/mp2t" if nama.lower().endswith(".ts") else "video/mp4"
    return FileResponse(
        path,
        media_type=media,
        filename=nama if unduh else None,
        content_disposition_type="attachment" if unduh else "inline",
    )