"""Test proxy HLS ber-guard (Fase 5.2) — bagian keamanan paling penting."""

from __future__ import annotations

import httpx
import pytest

from app.models import MODE_PUBLIC, MODE_SCHEDULED, AccessPolicy, Camera
from app.routers import stream as stream_module
from app.routers.stream import rewrite_manifest
from tests.conftest import ADMIN_PW, login


def buat_kamera(db, slug="utara", stream_key="utara", enabled=True, **policy_kwargs):
    kamera = Camera(
        slug=slug,
        name=f"Kamera {slug}",
        location="Area Uji",
        stream_key=stream_key,
        enabled=enabled,
        sort=0,
    )
    db.add(kamera)
    db.flush()
    opsi = {"mode": MODE_PUBLIC, "days": "0,1,2,3,4,5,6", "timezone": "Asia/Jakarta", "active": True}
    opsi.update(policy_kwargs)
    db.add(AccessPolicy(camera_id=kamera.id, **opsi))
    db.commit()
    db.refresh(kamera)
    return kamera


def pasang_upstream(monkeypatch, handler):
    def _client():
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=False
        )

    monkeypatch.setattr(stream_module, "_client", _client)


PLAYLIST = (
    "#EXTM3U\n"
    "#EXT-X-VERSION:10\n"
    "#EXT-X-MAP:URI=\"init.mp4?session=abc\"\n"
    "#EXTINF:2.0,\n"
    "seg45.mp4?session=abc\n"
)


# --------------------------------------------------------------------------- #
# Guard
# --------------------------------------------------------------------------- #
class TestGuard:
    def test_tanpa_sesi_401(self, client, db):
        buat_kamera(db)
        assert client.get("/stream/utara/index.m3u8").status_code == 401

    def test_slug_tidak_dikenal_404(self, client, admin_user):
        login(client, "admin", ADMIN_PW)
        assert client.get("/stream/tidak-ada/index.m3u8").status_code == 404

    def test_kamera_nonaktif_404(self, client, db, admin_user):
        buat_kamera(db, enabled=False)
        login(client, "admin", ADMIN_PW)
        assert client.get("/stream/utara/index.m3u8").status_code == 404

    def test_di_luar_jadwal_403_dan_tercatat(self, client, db, admin_user, monkeypatch):
        buat_kamera(db, mode=MODE_SCHEDULED, days="")  # tidak pernah dibuka
        login(client, "admin", ADMIN_PW)

        def handler(_request):  # pragma: no cover - tidak boleh dipanggil
            raise AssertionError("upstream tidak boleh dihubungi saat tertutup")

        pasang_upstream(monkeypatch, handler)
        resp = client.get("/stream/utara/index.m3u8")
        assert resp.status_code == 403

        from app.models import AccessLog

        aksi = [row.action for row in db.query(AccessLog).all()]
        assert "stream_denied" in aksi

    def test_jadwal_terbuka_lolos(self, client, db, admin_user, monkeypatch):
        buat_kamera(db)
        login(client, "admin", ADMIN_PW)
        pasang_upstream(monkeypatch, lambda _r: httpx.Response(200, text=PLAYLIST))
        assert client.get("/stream/utara/index.m3u8").status_code == 200


# --------------------------------------------------------------------------- #
# Proxy
# --------------------------------------------------------------------------- #
class TestProxy:
    def test_playlist_diteruskan_dengan_content_type(self, client, db, admin_user, monkeypatch):
        buat_kamera(db)
        login(client, "admin", ADMIN_PW)
        pasang_upstream(
            monkeypatch,
            lambda _r: httpx.Response(200, text=PLAYLIST, headers={"content-type": "application/vnd.apple.mpegurl"}),
        )
        resp = client.get("/stream/utara/index.m3u8")
        assert resp.status_code == 200
        assert "mpegurl" in resp.headers["content-type"]
        assert resp.headers["cache-control"] == "no-store"
        assert "seg45.mp4?session=abc" in resp.text

    def test_redirect_cookie_check_diikuti_tanpa_cookie(self, client, db, admin_user, monkeypatch):
        buat_kamera(db)
        login(client, "admin", ADMIN_PW)
        panggilan = []

        def handler(request: httpx.Request):
            panggilan.append(request)
            if len(panggilan) == 1:
                return httpx.Response(
                    302,
                    headers={
                        "location": "/utara/index.m3u8?cookieCheck=1",
                        "set-cookie": "cookieCheck=1; HttpOnly; Secure; SameSite=None",
                    },
                )
            return httpx.Response(200, text=PLAYLIST, headers={"content-type": "application/vnd.apple.mpegurl"})

        pasang_upstream(monkeypatch, handler)
        resp = client.get("/stream/utara/index.m3u8")
        assert resp.status_code == 200
        assert len(panggilan) == 2
        assert "cookieCheck=1" in str(panggilan[1].url)
        # cookie MediaMTX tidak boleh diteruskan (kalau dikirim, playlist kehilangan ?session=)
        assert "cookie" not in {k.lower() for k in panggilan[1].headers.keys()}

    def test_query_diteruskan_ke_upstream(self, client, db, admin_user, monkeypatch):
        buat_kamera(db)
        login(client, "admin", ADMIN_PW)
        terlihat = {}

        def handler(request: httpx.Request):
            terlihat["url"] = str(request.url)
            return httpx.Response(200, content=b"data", headers={"content-type": "video/mp4"})

        pasang_upstream(monkeypatch, handler)
        resp = client.get("/stream/utara/video1_stream.m3u8?session=xyz")
        assert resp.status_code == 200
        assert terlihat["url"].endswith("/utara/video1_stream.m3u8?session=xyz")

    def test_stream_key_dipakai_bukan_slug(self, client, db, admin_user, monkeypatch):
        buat_kamera(db, slug="kamera-utara", stream_key="utara")
        login(client, "admin", ADMIN_PW)
        terlihat = {}

        def handler(request: httpx.Request):
            terlihat["url"] = str(request.url)
            return httpx.Response(200, content=b"x", headers={"content-type": "video/mp4"})

        pasang_upstream(monkeypatch, handler)
        client.get("/stream/kamera-utara/seg1.mp4")
        assert terlihat["url"].endswith("/utara/seg1.mp4")

    def test_upstream_404_jadi_404(self, client, db, admin_user, monkeypatch):
        buat_kamera(db)
        login(client, "admin", ADMIN_PW)
        pasang_upstream(monkeypatch, lambda _r: httpx.Response(404))
        assert client.get("/stream/utara/hilang.mp4").status_code == 404

    def test_upstream_500_jadi_502(self, client, db, admin_user, monkeypatch):
        buat_kamera(db)
        login(client, "admin", ADMIN_PW)
        pasang_upstream(monkeypatch, lambda _r: httpx.Response(500))
        assert client.get("/stream/utara/index.m3u8").status_code == 502

    def test_mediamtx_mati_jadi_502(self, client, db, admin_user, monkeypatch):
        buat_kamera(db)
        login(client, "admin", ADMIN_PW)

        def handler(request: httpx.Request):
            raise httpx.ConnectError("connection refused", request=request)

        pasang_upstream(monkeypatch, handler)
        resp = client.get("/stream/utara/index.m3u8")
        assert resp.status_code == 502
        assert "MediaMTX" in resp.json()["detail"]

    def test_redirect_berlebihan_jadi_502(self, client, db, admin_user, monkeypatch):
        buat_kamera(db)
        login(client, "admin", ADMIN_PW)
        pasang_upstream(monkeypatch, lambda _r: httpx.Response(302, headers={"location": "/utara/index.m3u8"}))
        assert client.get("/stream/utara/index.m3u8").status_code == 502


class TestRewriteManifest:
    def test_uri_relatif_dibiarkan(self):
        assert rewrite_manifest(PLAYLIST, "utara") == PLAYLIST

    def test_uri_absolut_diawali_proxy(self):
        teks = '#EXTM3U\n#EXT-X-MAP:URI="/utara/init.mp4"\n/utara/seg1.mp4\n'
        hasil = rewrite_manifest(teks, "utara")
        assert 'URI="/stream/utara/utara/init.mp4"' not in hasil or True  # dokumentasi: prefix ditambahkan
        assert 'URI="/stream/utara/utara/init.mp4"' in hasil
        assert hasil.rstrip().endswith("/stream/utara/utara/seg1.mp4")

    def test_newline_dipertahankan(self):
        assert rewrite_manifest("#EXTM3U\n", "utara").endswith("\n")
        assert not rewrite_manifest("#EXTM3U", "utara").endswith("\n")
