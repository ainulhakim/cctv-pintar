"""Test panel admin: kamera, jadwal, pengguna, log (Fase 6)."""

from __future__ import annotations

import datetime as dt

import pytest

from app.models import (
    MODE_PUBLIC,
    MODE_SCHEDULED,
    ROLE_ADMIN,
    ROLE_VIEWER,
    AccessLog,
    AccessPolicy,
    Camera,
    User,
)
from app.schedule import is_open
from tests.conftest import ADMIN_PW, VIEWER_PW, login

HALAMAN_ADMIN = ["/admin/", "/admin/cameras", "/admin/policies", "/admin/users", "/admin/logs"]


def data_kamera(**ubah) -> dict:
    dasar = {
        "slug": "teras",
        "name": "Kamera Teras",
        "location": "Teras Depan",
        "stream_key": "teras",
        "sort": "3",
        "enabled": "1",
    }
    dasar.update(ubah)
    return dasar


class TestGuardAdmin:
    @pytest.mark.parametrize("path", HALAMAN_ADMIN)
    def test_viewer_ditolak(self, client, viewer_user, path):
        login(client, "viewer", VIEWER_PW)
        assert client.get(path).status_code == 403

    @pytest.mark.parametrize("path", HALAMAN_ADMIN)
    def test_tanpa_sesi_401(self, client, path):
        assert client.get(path).status_code == 401

    @pytest.mark.parametrize("path", HALAMAN_ADMIN)
    def test_admin_boleh_buka(self, client, admin_user, path):
        login(client, "admin", ADMIN_PW)
        resp = client.get(path, headers={"accept": "text/html"})
        assert resp.status_code == 200

    def test_viewer_tidak_bisa_post(self, client, viewer_user):
        login(client, "viewer", VIEWER_PW)
        assert client.post("/admin/cameras", data=data_kamera()).status_code == 403


class TestKameraCRUD:
    def test_tambah_kamera_beserta_policy_publik(self, client, admin_user, db):
        login(client, "admin", ADMIN_PW)
        resp = client.post("/admin/cameras", data=data_kamera(), follow_redirects=False)
        assert resp.status_code == 303
        assert "ok=" in resp.headers["location"]

        kamera = db.query(Camera).filter(Camera.slug == "teras").one()
        assert kamera.name == "Kamera Teras"
        assert kamera.stream_key == "teras"
        assert kamera.enabled is True
        assert kamera.policy is not None
        assert kamera.policy.mode == MODE_PUBLIC
        assert is_open(kamera.policy) is True

    def test_slug_duplikat_ditolak(self, client, admin_user, db):
        login(client, "admin", ADMIN_PW)
        client.post("/admin/cameras", data=data_kamera())
        resp = client.post("/admin/cameras", data=data_kamera(name="Lain"), follow_redirects=False)
        assert "err=" in resp.headers["location"]
        assert db.query(Camera).count() == 1

    @pytest.mark.parametrize("ubah", [
        {"slug": "Slug Salah!"},
        {"name": "   "},
        {"stream_key": "key salah"},
    ])
    def test_input_tidak_valid_ditolak(self, client, admin_user, db, ubah):
        login(client, "admin", ADMIN_PW)
        resp = client.post("/admin/cameras", data=data_kamera(**ubah), follow_redirects=False)
        assert "err=" in resp.headers["location"]
        assert db.query(Camera).count() == 0

    def test_ubah_kamera(self, client, admin_user, db):
        login(client, "admin", ADMIN_PW)
        client.post("/admin/cameras", data=data_kamera())
        kamera = db.query(Camera).one()

        resp = client.post(
            f"/admin/cameras/{kamera.id}",
            data=data_kamera(name="Kamera Teras Baru", location="Teras Belakang", enabled="", sort="9"),
            follow_redirects=False,
        )
        assert "ok=" in resp.headers["location"]
        db.refresh(kamera)
        assert kamera.name == "Kamera Teras Baru"
        assert kamera.location == "Teras Belakang"
        assert kamera.enabled is False  # checkbox kosong = nonaktif
        assert kamera.sort == 9

    def test_ubah_slug_bentrok_ditolak(self, client, admin_user, db):
        login(client, "admin", ADMIN_PW)
        client.post("/admin/cameras", data=data_kamera(slug="a", stream_key="a"))
        client.post("/admin/cameras", data=data_kamera(slug="b", stream_key="b"))
        kamera_b = db.query(Camera).filter(Camera.slug == "b").one()

        resp = client.post(
            f"/admin/cameras/{kamera_b.id}", data=data_kamera(slug="a", stream_key="b"),
            follow_redirects=False,
        )
        assert "err=" in resp.headers["location"]
        db.refresh(kamera_b)
        assert kamera_b.slug == "b"

    def test_hapus_kamera_membersihkan_policy_dan_log(self, client, admin_user, db):
        login(client, "admin", ADMIN_PW)
        client.post("/admin/cameras", data=data_kamera())
        kamera = db.query(Camera).one()
        db.add(AccessLog(camera_id=kamera.id, action="stream_denied", ip="1.2.3.4"))
        db.commit()

        resp = client.post(f"/admin/cameras/{kamera.id}/delete", follow_redirects=False)
        assert "ok=" in resp.headers["location"]
        assert db.query(Camera).count() == 0
        assert db.query(AccessPolicy).count() == 0
        assert db.query(AccessLog).filter(AccessLog.camera_id == kamera.id).count() == 0

    def test_kamera_baru_langsung_tampil_di_pantauan(self, client, admin_user):
        login(client, "admin", ADMIN_PW)
        client.post("/admin/cameras", data=data_kamera())
        assert "Kamera Teras" in client.get("/", headers={"accept": "text/html"}).text


class TestJadwal:
    @pytest.fixture
    def kamera(self, db):
        from app.routers.admin_cameras import router  # noqa: F401  (pastikan impor modul)

        kamera = Camera(slug="teras", name="Kamera Teras", stream_key="teras", enabled=True, sort=1)
        db.add(kamera)
        db.flush()
        db.add(AccessPolicy(camera_id=kamera.id, mode=MODE_PUBLIC, days="0,1,2,3,4,5,6",
                            timezone="Asia/Jakarta", active=True))
        db.commit()
        db.refresh(kamera)
        return kamera

    def test_set_mode_terjadwal(self, client, admin_user, db, kamera):
        login(client, "admin", ADMIN_PW)
        resp = client.post(
            f"/admin/policies/{kamera.id}",
            data={"mode": "scheduled", "days": ["0", "2"], "start": "08:00", "end": "17:00", "active": "1"},
            follow_redirects=False,
        )
        assert "ok=" in resp.headers["location"]
        db.refresh(kamera)
        policy = kamera.policy
        assert policy.mode == MODE_SCHEDULED
        assert policy.days == "0,2"
        assert policy.start_time == dt.time(8, 0)
        assert policy.end_time == dt.time(17, 0)
        assert is_open(policy, dt.datetime(2026, 10, 19, 10, 0)) is True   # Senin
        assert is_open(policy, dt.datetime(2026, 10, 20, 10, 0)) is False  # Selasa

    def test_kembali_ke_publik(self, client, admin_user, db, kamera):
        login(client, "admin", ADMIN_PW)
        client.post(f"/admin/policies/{kamera.id}",
                    data={"mode": "public", "days": ["1"], "start": "", "end": "", "active": "1"})
        db.refresh(kamera)
        assert kamera.policy.mode == MODE_PUBLIC
        assert kamera.policy.start_time is None
        assert kamera.policy.days == "0,1,2,3,4,5,6"
        assert is_open(kamera.policy) is True

    def test_terjadwal_tanpa_hari_ditolak(self, client, admin_user, db, kamera):
        login(client, "admin", ADMIN_PW)
        resp = client.post(f"/admin/policies/{kamera.id}",
                           data={"mode": "scheduled", "start": "08:00", "end": "17:00"},
                           follow_redirects=False)
        assert "err=" in resp.headers["location"]
        db.refresh(kamera)
        assert kamera.policy.mode == MODE_PUBLIC

    def test_jam_tidak_valid_ditolak(self, client, admin_user, db, kamera):
        login(client, "admin", ADMIN_PW)
        resp = client.post(f"/admin/policies/{kamera.id}",
                           data={"mode": "scheduled", "days": ["0"], "start": "25:99", "end": "abc"},
                           follow_redirects=False)
        assert "err=" in resp.headers["location"]
        db.refresh(kamera)
        assert kamera.policy.mode == MODE_PUBLIC

    def test_policy_nonaktif_menutup_kamera(self, client, admin_user, db, kamera):
        login(client, "admin", ADMIN_PW)
        client.post(f"/admin/policies/{kamera.id}",
                    data={"mode": "public", "days": ["0"], "start": "", "end": ""})
        db.refresh(kamera)
        assert kamera.policy.active is False
        assert is_open(kamera.policy) is False

    def test_window_lintas_tengah_malam(self, client, admin_user, db, kamera):
        login(client, "admin", ADMIN_PW)
        client.post(f"/admin/policies/{kamera.id}",
                    data={"mode": "scheduled", "days": ["0"], "start": "22:00", "end": "05:00", "active": "1"})
        db.refresh(kamera)
        policy = kamera.policy
        assert is_open(policy, dt.datetime(2026, 10, 19, 23, 0)) is True
        assert is_open(policy, dt.datetime(2026, 10, 20, 2, 0)) is True
        assert is_open(policy, dt.datetime(2026, 10, 19, 12, 0)) is False

    def test_halaman_menampilkan_ringkasan(self, client, admin_user, db, kamera):
        login(client, "admin", ADMIN_PW)
        resp = client.get("/admin/policies", headers={"accept": "text/html"})
        assert "Publik 24 jam" in resp.text
        assert "Kamera Teras" in resp.text


class TestPengguna:
    def test_tambah_viewer_lalu_bisa_login(self, client, admin_user, db):
        login(client, "admin", ADMIN_PW)
        resp = client.post("/admin/users", data={
            "username": "budi", "full_name": "Budi Santoso",
            "password": "rahasia123", "confirm": "rahasia123", "role": "viewer",
        }, follow_redirects=False)
        assert "ok=" in resp.headers["location"]

        user = db.query(User).filter(User.username == "budi").one()
        assert user.role == ROLE_VIEWER
        assert user.is_admin is False

        client.post("/logout")
        assert login(client, "budi", "rahasia123").status_code == 303

    def test_username_duplikat_ditolak(self, client, admin_user, db):
        login(client, "admin", ADMIN_PW)
        resp = client.post("/admin/users", data={
            "username": "admin", "password": "rahasia123", "confirm": "rahasia123", "role": "viewer",
        }, follow_redirects=False)
        assert "err=" in resp.headers["location"]
        assert db.query(User).count() == 1

    def test_password_lemah_ditolak(self, client, admin_user, db):
        login(client, "admin", ADMIN_PW)
        resp = client.post("/admin/users", data={
            "username": "budi", "password": "rahasia", "confirm": "rahasia", "role": "viewer",
        }, follow_redirects=False)
        assert "err=" in resp.headers["location"]
        assert db.query(User).filter(User.username == "budi").count() == 0

    def test_konfirmasi_password_beda_ditolak(self, client, admin_user, db):
        login(client, "admin", ADMIN_PW)
        resp = client.post("/admin/users", data={
            "username": "budi", "password": "rahasia123", "confirm": "rahasia456", "role": "viewer",
        }, follow_redirects=False)
        assert "err=" in resp.headers["location"]

    def test_reset_password(self, client, admin_user, db):
        login(client, "admin", ADMIN_PW)
        client.post("/admin/users", data={
            "username": "budi", "password": "rahasia123", "confirm": "rahasia123", "role": "viewer",
        })
        budi = db.query(User).filter(User.username == "budi").one()

        resp = client.post(f"/admin/users/{budi.id}/password",
                           data={"password": "passwordbaru1", "confirm": "passwordbaru1"},
                           follow_redirects=False)
        assert "ok=" in resp.headers["location"]

        client.post("/logout")
        assert login(client, "budi", "rahasia123").status_code == 401
        assert login(client, "budi", "passwordbaru1").status_code == 303

    def test_nonaktifkan_user_menghalangi_login(self, client, admin_user, db):
        login(client, "admin", ADMIN_PW)
        client.post("/admin/users", data={
            "username": "budi", "password": "rahasia123", "confirm": "rahasia123", "role": "viewer",
        })
        budi = db.query(User).filter(User.username == "budi").one()

        resp = client.post(f"/admin/users/{budi.id}/active", data={"active": "0"}, follow_redirects=False)
        assert "ok=" in resp.headers["location"]
        db.refresh(budi)
        assert budi.active is False

        client.post("/logout")
        assert login(client, "budi", "rahasia123").status_code == 401

    def test_tidak_bisa_menonaktifkan_diri_sendiri(self, client, admin_user, db):
        login(client, "admin", ADMIN_PW)
        resp = client.post(f"/admin/users/{admin_user.id}/active", data={"active": "0"}, follow_redirects=False)
        assert "err=" in resp.headers["location"]
        db.refresh(admin_user)
        assert admin_user.active is True

    def test_tidak_bisa_hapus_admin_terakhir(self, client, admin_user, db):
        login(client, "admin", ADMIN_PW)
        resp = client.post(f"/admin/users/{admin_user.id}/delete", follow_redirects=False)
        assert "err=" in resp.headers["location"]

        # akun sendiri tetap tidak boleh dihapus walau ada admin lain
        client.post("/admin/users", data={
            "username": "admin2", "password": "rahasia123", "confirm": "rahasia123", "role": "admin",
        })
        admin2 = db.query(User).filter(User.username == "admin2").one()
        resp = client.post(f"/admin/users/{admin_user.id}/delete", follow_redirects=False)
        assert "err=" in resp.headers["location"]

        # admin lain boleh dihapus
        resp = client.post(f"/admin/users/{admin2.id}/delete", follow_redirects=False)
        assert "ok=" in resp.headers["location"]
        assert db.query(User).filter(User.username == "admin2").count() == 0
        assert db.query(User).filter(User.username == "admin").count() == 1

    def test_ubah_role(self, client, admin_user, db):
        login(client, "admin", ADMIN_PW)
        client.post("/admin/users", data={
            "username": "budi", "password": "rahasia123", "confirm": "rahasia123", "role": "viewer",
        })
        budi = db.query(User).filter(User.username == "budi").one()

        resp = client.post(f"/admin/users/{budi.id}/role", data={"role": "admin"}, follow_redirects=False)
        assert "ok=" in resp.headers["location"]
        db.refresh(budi)
        assert budi.role == ROLE_ADMIN

    def test_role_tidak_dikenal_jadi_viewer(self, client, admin_user, db):
        login(client, "admin", ADMIN_PW)
        client.post("/admin/users", data={
            "username": "budi", "password": "rahasia123", "confirm": "rahasia123", "role": "superuser",
        })
        assert db.query(User).filter(User.username == "budi").one().role == ROLE_VIEWER


class TestLog:
    def test_menampilkan_log_dan_status(self, client, admin_user, db):
        db.add(AccessLog(action="stream_denied", detail="di luar jadwal akses", ip="9.9.9.9"))
        db.commit()
        login(client, "admin", ADMIN_PW)
        resp = client.get("/admin/logs", headers={"accept": "text/html"})
        assert resp.status_code == 200
        assert "stream_denied" in resp.text
        assert "9.9.9.9" in resp.text
        assert "MediaMTX" in resp.text
        assert "Disk server" in resp.text

    def test_filter_aksi(self, client, admin_user, db):
        db.add_all([
            AccessLog(action="stream_denied", ip="1.1.1.1"),
            AccessLog(action="login_ok", ip="2.2.2.2"),
        ])
        db.commit()
        login(client, "admin", ADMIN_PW)
        resp = client.get("/admin/logs?action=login_ok", headers={"accept": "text/html"})
        assert "2.2.2.2" in resp.text
        assert "1.1.1.1" not in resp.text

    def test_aksi_admin_tercatat(self, client, admin_user, db):
        login(client, "admin", ADMIN_PW)
        client.post("/admin/cameras", data=data_kamera())
        aksi = [row.action for row in db.query(AccessLog).all()]
        assert "camera_create" in aksi

    def test_ringkasan_menampilkan_angka_ditolak(self, client, admin_user, db):
        db.add(AccessLog(action="stream_denied", detail="di luar jadwal"))
        db.commit()
        login(client, "admin", ADMIN_PW)
        resp = client.get("/admin/", headers={"accept": "text/html"})
        assert "Akses ditolak (24 jam)" in resp.text


class TestStatusMediaMTX:
    """Regresi: `mediamtx.items` di Jinja ter-resolve ke method dict.items."""

    def test_parser_saat_mediamtx_hidup(self, monkeypatch):
        from app.routers import admin_home

        class Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "items": [
                        {
                            "name": "utara",
                            "ready": True,
                            "online": True,
                            "tracks": ["H264"],
                            "readers": [{"type": "hlsSession"}],
                        }
                    ]
                }

        monkeypatch.setattr(admin_home.httpx, "get", lambda *a, **k: Resp())
        hasil = admin_home.status_mediamtx()
        assert hasil["error"] is None
        assert hasil["paths"][0]["name"] == "utara"
        assert hasil["paths"][0]["readers"] == 1

    def test_parser_saat_mediamtx_mati(self, monkeypatch):
        from app.routers import admin_home

        def gagal(*_a, **_k):
            raise OSError("connection refused")

        monkeypatch.setattr(admin_home.httpx, "get", gagal)
        hasil = admin_home.status_mediamtx()
        assert hasil["error"]
        assert hasil["paths"] == []

    @pytest.mark.parametrize("path", ["/admin/", "/admin/logs"])
    def test_halaman_render_saat_mediamtx_online(self, client, admin_user, monkeypatch, path):
        from app.routers import admin_home, admin_logs

        sehat = {
            "error": None,
            "paths": [
                {"name": "utara", "ready": True, "online": True, "tracks": "H264", "readers": 2}
            ],
        }
        monkeypatch.setattr(admin_home, "status_mediamtx", lambda *a, **k: sehat)
        monkeypatch.setattr(admin_logs, "status_mediamtx", lambda *a, **k: sehat)

        login(client, "admin", ADMIN_PW)
        resp = client.get(path, headers={"accept": "text/html"})
        assert resp.status_code == 200
        assert "utara" in resp.text
        assert "H264" in resp.text
