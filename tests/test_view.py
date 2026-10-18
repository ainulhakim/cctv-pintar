"""Test halaman pantauan, API status, dan snapshot (Fase 5.1 & 5.3)."""

from __future__ import annotations

import pytest

from app import snapshots
from app.models import MODE_PUBLIC, MODE_SCHEDULED, AccessLog, AccessPolicy, Camera
from tests.conftest import ADMIN_PW, login


def buat_kamera(db, slug="utara", name=None, mode=MODE_PUBLIC, days="0,1,2,3,4,5,6",
                enabled=True, sort=0):
    kamera = Camera(
        slug=slug,
        name=name or f"Kamera {slug.title()}",
        location="DM VI",
        stream_key=slug,
        enabled=enabled,
        sort=sort,
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


class TestDashboard:
    def test_tanpa_sesi_401(self, client, db):
        buat_kamera(db)
        assert client.get("/").status_code == 401

    def test_menampilkan_kamera_dan_kebijakan(self, client, db, admin_user):
        buat_kamera(db, "utara", "Kamera Utara")
        buat_kamera(db, "selatan", "Kamera Selatan", mode=MODE_SCHEDULED, days="")
        login(client, "admin", ADMIN_PW)

        resp = client.get("/", headers={"accept": "text/html"})
        assert resp.status_code == 200
        assert "Kamera Utara" in resp.text
        assert "Kamera Selatan" in resp.text
        assert "Akses: Publik 24 jam" in resp.text
        assert "/stream/utara/index.m3u8" in resp.text
        assert "/api/snapshot/utara" in resp.text
        assert "hls.js" in resp.text

    def test_kamera_nonaktif_tidak_muncul(self, client, db, admin_user):
        buat_kamera(db, "mati", "Kamera Mati", enabled=False)
        login(client, "admin", ADMIN_PW)
        assert "Kamera Mati" not in client.get("/", headers={"accept": "text/html"}).text

    def test_belum_ada_kamera(self, client, admin_user):
        login(client, "admin", ADMIN_PW)
        resp = client.get("/", headers={"accept": "text/html"})
        assert resp.status_code == 200
        assert "Belum ada kamera aktif" in resp.text


class TestStatusAPI:
    def test_tanpa_sesi_401(self, client, db):
        buat_kamera(db)
        assert client.get("/api/cameras/status").status_code == 401

    def test_publik_terbuka(self, client, db, admin_user):
        buat_kamera(db, "utara")
        login(client, "admin", ADMIN_PW)
        data = client.get("/api/cameras/status").json()
        assert len(data["cameras"]) == 1
        cam = data["cameras"][0]
        assert cam["slug"] == "utara"
        assert cam["open"] is True
        assert cam["policy"] == "Publik 24 jam"
        assert cam["next_open"] is None
        assert cam["stream_url"] == "/stream/utara/index.m3u8"

    def test_terjadwal_tertutup_punya_next_open(self, client, db, admin_user):
        buat_kamera(db, "selatan", mode=MODE_SCHEDULED, days="0,1,2,3,4,5,6")
        # days penuh tapi tanpa jam -> is_open False, next_open None (tanpa window)
        login(client, "admin", ADMIN_PW)
        cam = client.get("/api/cameras/status").json()["cameras"][0]
        assert cam["open"] is False

    def test_urutan_berdasarkan_sort(self, client, db, admin_user):
        buat_kamera(db, "b", sort=2)
        buat_kamera(db, "a", sort=1)
        login(client, "admin", ADMIN_PW)
        slugs = [c["slug"] for c in client.get("/api/cameras/status").json()["cameras"]]
        assert slugs == ["a", "b"]


class TestSnapshot:
    @pytest.fixture(autouse=True)
    def bersihkan_cache(self):
        snapshots.cache_clear()
        yield
        snapshots.cache_clear()

    def test_tanpa_sesi_401(self, client, db):
        buat_kamera(db)
        assert client.get("/api/snapshot/utara").status_code == 401

    def test_slug_tidak_dikenal_404(self, client, admin_user):
        login(client, "admin", ADMIN_PW)
        assert client.get("/api/snapshot/tidak-ada").status_code == 404

    def test_di_luar_jadwal_403_dan_tercatat(self, client, db, admin_user, monkeypatch):
        buat_kamera(db, mode=MODE_SCHEDULED, days="")
        login(client, "admin", ADMIN_PW)

        def jangan_dipanggil(_key):  # pragma: no cover
            raise AssertionError("ffmpeg tidak boleh dipanggil saat tertutup")

        monkeypatch.setattr(snapshots, "capture", jangan_dipanggil)
        assert client.get("/api/snapshot/utara").status_code == 403
        assert "snapshot_denied" in [row.action for row in db.query(AccessLog).all()]

    def test_snapshot_jpeg(self, client, db, admin_user, monkeypatch):
        buat_kamera(db)
        login(client, "admin", ADMIN_PW)
        jpeg = b"\xff\xd8\xff\xe0data-jpeg\xff\xd9"
        panggilan = []

        def capture(key):
            panggilan.append(key)
            return jpeg

        monkeypatch.setattr(snapshots, "capture", capture)
        resp = client.get("/api/snapshot/utara")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert resp.content == jpeg
        assert panggilan == ["utara"]

    def test_snapshot_pakai_cache(self, client, db, admin_user, monkeypatch):
        buat_kamera(db)
        login(client, "admin", ADMIN_PW)
        panggilan = []

        def capture(key):
            panggilan.append(key)
            return b"\xff\xd8\xff\xd9"

        monkeypatch.setattr(snapshots, "capture", capture)
        client.get("/api/snapshot/utara")
        client.get("/api/snapshot/utara")
        assert len(panggilan) == 1  # panggilan kedua dilayani cache

    def test_ffmpeg_gagal_jadi_503(self, client, db, admin_user, monkeypatch):
        buat_kamera(db)
        login(client, "admin", ADMIN_PW)

        def gagal(_key):
            raise snapshots.SnapshotError("ffmpeg timeout")

        monkeypatch.setattr(snapshots, "capture", gagal)
        resp = client.get("/api/snapshot/utara")
        assert resp.status_code == 503
        assert "Snapshot gagal" in resp.json()["detail"]


class TestSnapshotCache:
    def test_cache_menghormati_ttl(self, monkeypatch):
        snapshots.cache_clear()
        panggilan = []

        def capture(key):
            panggilan.append(key)
            return b"x"

        monkeypatch.setattr(snapshots, "capture", capture)
        snapshots.get_snapshot("utara", now=1000, ttl=5)
        snapshots.get_snapshot("utara", now=1003, ttl=5)  # masih cache
        assert len(panggilan) == 1
        snapshots.get_snapshot("utara", now=1006, ttl=5)  # kadaluarsa
        assert len(panggilan) == 2
        snapshots.cache_clear()
