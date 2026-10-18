"""Test fitur override admin: buka kamera tertutup dengan password sendiri."""

from __future__ import annotations

import httpx
import pytest

from app import override, snapshots
from app.config import settings
from app.models import MODE_PUBLIC, MODE_SCHEDULED, AccessLog, AccessPolicy, Camera
from tests.conftest import ADMIN_PW, VIEWER_PW, login
from tests.test_stream_guard import PLAYLIST, pasang_upstream


def kamera_tertutup(db, slug="teras", stream_key="teras", enabled=True) -> Camera:
    """Kamera terjadwal tanpa hari -> selalu tertutup (paling ketat)."""
    kamera = Camera(slug=slug, name=f"Kamera {slug}", location="Teras",
                    stream_key=stream_key, enabled=enabled, sort=1)
    db.add(kamera)
    db.flush()
    db.add(AccessPolicy(camera_id=kamera.id, mode=MODE_SCHEDULED, days="",
                        timezone="Asia/Jakarta", active=True))
    db.commit()
    db.refresh(kamera)
    return kamera


def kamera_publik(db, slug="utara") -> Camera:
    kamera = Camera(slug=slug, name=f"Kamera {slug}", stream_key=slug, enabled=True, sort=0)
    db.add(kamera)
    db.flush()
    db.add(AccessPolicy(camera_id=kamera.id, mode=MODE_PUBLIC, days="0,1,2,3,4,5,6",
                        timezone="Asia/Jakarta", active=True))
    db.commit()
    db.refresh(kamera)
    return kamera


def aksi_log(db):
    return [row.action for row in db.query(AccessLog).all()]


class TestHakOverride:
    def test_tanpa_sesi_401(self, client, db):
        kamera_tertutup(db)
        assert client.post("/api/cameras/teras/override", data={"password": "apa saja"}).status_code == 401

    def test_viewer_ditolak_walau_password_admin_benar(self, client, db, viewer_user):
        kamera_tertutup(db)
        login(client, "viewer", VIEWER_PW)
        resp = client.post("/api/cameras/teras/override", data={"password": ADMIN_PW})
        assert resp.status_code == 403
        assert "Hanya admin" in resp.json()["detail"]
        assert "override_failed" in aksi_log(db)

    def test_admin_password_salah_401(self, client, db, admin_user):
        kamera_tertutup(db)
        login(client, "admin", ADMIN_PW)
        resp = client.post("/api/cameras/teras/override", data={"password": "salah-banget"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Password salah."
        assert "override_failed" in aksi_log(db)
        assert "set-cookie" not in resp.headers

    def test_kamera_terbuka_tidak_perlu_override(self, client, db, admin_user):
        kamera_publik(db)
        login(client, "admin", ADMIN_PW)
        resp = client.post("/api/cameras/utara/override", data={"password": ADMIN_PW})
        assert resp.status_code == 400

    def test_kamera_tidak_ada_404(self, client, db, admin_user):
        login(client, "admin", ADMIN_PW)
        assert client.post("/api/cameras/hantu/override", data={"password": ADMIN_PW}).status_code == 404

    def test_rate_limit_percobaan_berlebih(self, client, db, admin_user):
        kamera_tertutup(db)
        login(client, "admin", ADMIN_PW)
        for _ in range(5):
            assert client.post("/api/cameras/teras/override", data={"password": "salah"}).status_code == 401
        # percobaan ke-6 diblokir walau password benar
        resp = client.post("/api/cameras/teras/override", data={"password": ADMIN_PW})
        assert resp.status_code == 429
        assert "override_blocked" in aksi_log(db)


class TestOverrideBerhasil:
    def test_grant_lalu_stream_dan_snapshot_lolos(self, client, db, admin_user, monkeypatch):
        kamera_tertutup(db)
        login(client, "admin", ADMIN_PW)

        # sebelum override: tertutup
        assert client.get("/stream/teras/index.m3u8").status_code == 403

        resp = client.post("/api/cameras/teras/override", data={"password": ADMIN_PW})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert "cctv_override=" in resp.headers["set-cookie"]
        assert "override_granted" in aksi_log(db)

        pasang_upstream(monkeypatch, lambda _r: httpx.Response(200, text=PLAYLIST,
                                                              headers={"content-type": "application/vnd.apple.mpegurl"}))
        assert client.get("/stream/teras/index.m3u8").status_code == 200

        monkeypatch.setattr(snapshots, "capture", lambda key: b"\xff\xd8\xff\xd9")
        assert client.get("/api/snapshot/teras").status_code == 200

    def test_override_hanya_berlaku_untuk_kamera_itu(self, client, db, admin_user, monkeypatch):
        kamera_tertutup(db, slug="teras", stream_key="teras")
        kamera_tertutup(db, slug="garasi", stream_key="garasi")
        login(client, "admin", ADMIN_PW)
        assert client.post("/api/cameras/teras/override", data={"password": ADMIN_PW}).status_code == 200

        pasang_upstream(monkeypatch, lambda _r: httpx.Response(200, text=PLAYLIST))
        assert client.get("/stream/teras/index.m3u8").status_code == 200
        assert client.get("/stream/garasi/index.m3u8").status_code == 403

    def test_override_kedaluwarsa(self, client, db, admin_user, monkeypatch):
        kamera_tertutup(db)
        login(client, "admin", ADMIN_PW)
        assert client.post("/api/cameras/teras/override", data={"password": ADMIN_PW}).status_code == 200

        pasang_upstream(monkeypatch, lambda _r: httpx.Response(200, text=PLAYLIST))
        assert client.get("/stream/teras/index.m3u8").status_code == 200

        monkeypatch.setattr(settings, "override_ttl", -1)  # token langsung dianggap basi
        assert client.get("/stream/teras/index.m3u8").status_code == 403

    def test_token_override_tidak_berguna_untuk_viewer(self, client, db, admin_user, viewer_user):
        kamera_tertutup(db)
        login(client, "admin", ADMIN_PW)
        token = override.grant(admin_user.id, db.query(Camera).one().id)

        client.post("/logout")
        login(client, "viewer", VIEWER_PW)
        client.cookies.set("cctv_override", token)
        assert client.get("/stream/teras/index.m3u8").status_code == 403

    def test_logout_mencabut_cookie_override(self, client, db, admin_user):
        kamera_tertutup(db)
        login(client, "admin", ADMIN_PW)
        client.post("/api/cameras/teras/override", data={"password": ADMIN_PW})
        resp = client.post("/logout", follow_redirects=False)
        set_cookie = resp.headers.get_list("set-cookie")
        assert any("cctv_override=" in item and "Max-Age=0" in item for item in set_cookie)


class TestTampilan:
    def test_status_api_menandai_override(self, client, db, admin_user):
        kamera_tertutup(db)
        login(client, "admin", ADMIN_PW)

        sebelum = client.get("/api/cameras/status").json()
        assert sebelum["is_admin"] is True
        assert sebelum["cameras"][0]["override_active"] is False
        assert sebelum["cameras"][0]["can_override"] is True

        client.post("/api/cameras/teras/override", data={"password": ADMIN_PW})
        sesudah = client.get("/api/cameras/status").json()["cameras"][0]
        assert sesudah["override_active"] is True
        assert sesudah["override_until"] is not None
        assert sesudah["open"] is False  # tetap tertutup menurut jadwal

    def test_viewer_tidak_punya_hak_override(self, client, db, viewer_user):
        kamera_tertutup(db)
        login(client, "viewer", VIEWER_PW)
        cam = client.get("/api/cameras/status").json()["cameras"][0]
        assert cam["can_override"] is False
        assert cam["override_active"] is False

    def test_dashboard_admin_menampilkan_form_override(self, client, db, admin_user):
        kamera_tertutup(db)
        login(client, "admin", ADMIN_PW)
        html = client.get("/", headers={"accept": "text/html"}).text
        assert "Buka sebagai admin" in html
        assert "Tertutup" in html

    def test_dashboard_viewer_tanpa_form_override(self, client, db, viewer_user):
        kamera_tertutup(db)
        login(client, "viewer", VIEWER_PW)
        html = client.get("/", headers={"accept": "text/html"}).text
        assert "Buka sebagai admin" not in html
        assert "hanya untuk admin" in html

    def test_dashboard_admin_kamera_terbuka_tanpa_form(self, client, db, admin_user):
        kamera_publik(db)
        login(client, "admin", ADMIN_PW)
        html = client.get("/", headers={"accept": "text/html"}).text
        assert "Buka sebagai admin" not in html


class TestUnitOverride:
    def test_grant_dan_read(self):
        token = override.grant(7, 3)
        assert override.read(token) == (7, 3)

    def test_token_sampah_ditolak(self):
        assert override.read("bukan-token") is None
        assert override.read("") is None

    def test_token_kedaluwarsa_ditolak(self):
        token = override.grant(1, 1)
        assert override.read(token, max_age=-1) is None

    def test_deadline_menolak_user_berbeda(self, client, db, admin_user, viewer_user):
        kamera = kamera_tertutup(db)

        class Req:
            cookies = {"cctv_override": override.grant(admin_user.id, kamera.id)}

        assert override.deadline(Req, admin_user, kamera) is not None
        assert override.deadline(Req, viewer_user, kamera) is None

    def test_deadline_menolak_kamera_lain(self, client, db, admin_user):
        kamera = kamera_tertutup(db)
        lain = kamera_tertutup(db, slug="garasi", stream_key="garasi")

        class Req:
            cookies = {"cctv_override": override.grant(admin_user.id, kamera.id)}

        assert override.deadline(Req, admin_user, lain) is None

    def test_limiter_kunci_memakai_user_dan_ip(self, client, db, admin_user):
        from tests.test_override import kamera_tertutup as _k  # noqa: F401

        class Req:
            cookies = {}
            headers = {"cf-connecting-ip": "1.2.3.4"}
            client = None

        kunci = override.kunci_limiter(Req, admin_user)
        assert kunci == f"{admin_user.id}:1.2.3.4"
