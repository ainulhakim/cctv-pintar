"""Test mode viewer publik (`PUBLIC_VIEW=1`).

Aturan: halaman pantauan, API status, stream, dan snapshot boleh diakses tanpa
login. Jadwal kamera TETAP dipaksa (kamera tertutup -> 403), dan panel admin
tetap wajib login.
"""

from __future__ import annotations

import httpx
import pytest

from app import snapshots
from app.config import settings
from app.models import MODE_PUBLIC, MODE_SCHEDULED, AccessLog, AccessPolicy, Camera
from app.routers import stream as stream_module

PLAYLIST = "#EXTM3U\n#EXT-X-VERSION:10\n#EXTINF:2.0,\nseg1.mp4?session=abc\n"


@pytest.fixture
def publik(monkeypatch):
    """Aktifkan viewer publik untuk satu test."""
    monkeypatch.setattr(settings, "public_view", True)
    return settings


def buat_kamera(db, slug="utara", mode=MODE_PUBLIC, days="0,1,2,3,4,5,6"):
    kamera = Camera(
        slug=slug,
        name=f"Kamera {slug}",
        location="Area Uji",
        stream_key=slug,
        enabled=True,
        sort=0,
    )
    db.add(kamera)
    db.flush()
    db.add(
        AccessPolicy(
            camera_id=kamera.id,
            mode=mode,
            days=days,
            timezone="Asia/Jakarta",
            active=True,
        )
    )
    db.commit()
    db.refresh(kamera)
    return kamera


def pasang_upstream(monkeypatch, handler):
    def _client():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)

    monkeypatch.setattr(stream_module, "_client", _client)


class TestViewerPublik:
    def test_dashboard_tanpa_login_200(self, client, db, publik):
        buat_kamera(db, "utara")
        resp = client.get("/", headers={"accept": "text/html"})
        assert resp.status_code == 200
        assert "Kamera utara" in resp.text
        assert "Pantauan Langsung" in resp.text

    def test_status_tanpa_login(self, client, db, publik):
        buat_kamera(db)
        data = client.get("/api/cameras/status").json()
        assert data["is_admin"] is False
        assert data["cameras"][0]["open"] is True

    def test_stream_kamera_publik_lolos(self, client, db, publik, monkeypatch):
        buat_kamera(db)
        pasang_upstream(
            monkeypatch,
            lambda _r: httpx.Response(200, text=PLAYLIST, headers={"content-type": "application/vnd.apple.mpegurl"}),
        )
        assert client.get("/stream/utara/index.m3u8").status_code == 200

    def test_stream_kamera_tertutup_tetap_403(self, client, db, publik, monkeypatch):
        buat_kamera(db, mode=MODE_SCHEDULED, days="")
        pasang_upstream(monkeypatch, lambda _r: httpx.Response(200, text=PLAYLIST))
        assert client.get("/stream/utara/index.m3u8").status_code == 403
        assert "stream_denied" in [row.action for row in db.query(AccessLog).all()]

    def test_snapshot_tanpa_login(self, client, db, publik, monkeypatch):
        buat_kamera(db)
        snapshots.cache_clear()
        monkeypatch.setattr(snapshots, "capture", lambda _k: b"\xff\xd8\xff\xd9")
        resp = client.get("/api/snapshot/utara")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"

    def test_panel_admin_tetap_wajib_login(self, client, db, publik):
        assert client.get("/admin").status_code == 401

    def test_viewer_publik_bisa_override_tetap_ditolak(self, client, db, publik):
        buat_kamera(db, mode=MODE_SCHEDULED, days="")
        resp = client.post("/api/cameras/utara/override", data={"password": "apa saja"})
        assert resp.status_code == 401


class TestViewerTertutup:
    def test_tanpa_login_tetap_401_bila_fitur_mati(self, client, db, monkeypatch):
        monkeypatch.setattr(settings, "public_view", False)
        buat_kamera(db)
        # follow_redirects=False: 401 pada halaman HTML diarahkan ke /login
        assert (
            client.get("/", headers={"accept": "text/html"}, follow_redirects=False).status_code
            in (303, 401)
        )
        assert client.get("/").status_code == 401
        assert client.get("/api/cameras/status").status_code == 401
        assert client.get("/stream/utara/index.m3u8").status_code == 401
