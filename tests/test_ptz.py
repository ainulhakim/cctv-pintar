"""Test panel kontrol PTZ (Tapo via API lokal).

Semua panggilan ke kamera di-mock: test ini tidak boleh butuh perangkat nyata.
"""

from __future__ import annotations

import pytest

from app import ptz
from app.models import MODE_PUBLIC, AccessPolicy, AccessLog, Camera
from app.audit import ACTION_PTZ, ACTION_PTZ_FAILED
from tests.conftest import ADMIN_PW, VIEWER_PW, login

KEMAMPUAN_HIDUP = {"didukung": True, "alasan": "", "host": "192.168.18.140", "pan": True,
                   "tilt": True, "zoom": False, "model": "C200"}
KEMAMPUAN_MATI = {"didukung": False, "alasan": "Kamera menjawab, tetapi tidak punya motor pan/tilt.",
                  "host": "192.168.18.140", "pan": False, "tilt": False, "zoom": False}


def buat_kamera(db, slug="lantai-atas", name=None):
    kamera = Camera(slug=slug, name=name or f"Kamera {slug}", location="Uji",
                    stream_key=slug, enabled=True, sort=0)
    db.add(kamera)
    db.flush()
    db.add(AccessPolicy(camera_id=kamera.id, mode=MODE_PUBLIC, days="0,1,2,3,4,5,6",
                        timezone="Asia/Jakarta", active=True))
    db.commit()
    db.refresh(kamera)
    return kamera


class TestGuard:
    def test_tanpa_sesi_401(self, client, db):
        buat_kamera(db)
        assert client.get("/admin/ptz").status_code == 401
        assert client.get("/admin/api/ptz/lantai-atas").status_code == 401

    def test_viewer_403(self, client, db, viewer_user):
        buat_kamera(db)
        login(client, "viewer", VIEWER_PW)
        assert client.get("/admin/ptz").status_code == 403
        assert client.post("/admin/api/ptz/lantai-atas", data={"aksi": "gerak", "arah": "kiri"}).status_code == 403


class TestHalaman:
    def test_kamera_tanpa_motor_tidak_dapat_tombol(self, client, db, admin_user, monkeypatch):
        buat_kamera(db, "gudang")
        monkeypatch.setattr("app.routers.admin_ptz.ptz.kemampuan", lambda key, segarkan=False: KEMAMPUAN_MATI)
        login(client, "admin", ADMIN_PW)

        resp = client.get("/admin/ptz", headers={"accept": "text/html"})
        assert resp.status_code == 200
        assert "tanpa motor" in resp.text
        assert "data-arah" not in resp.text

    def test_kamera_bermotor_dapat_tombol(self, client, db, admin_user, monkeypatch):
        buat_kamera(db, "lantai-atas")
        monkeypatch.setattr("app.routers.admin_ptz.ptz.kemampuan", lambda key, segarkan=False: KEMAMPUAN_HIDUP)
        monkeypatch.setattr("app.routers.admin_ptz.ptz.daftar_preset", lambda key: [{"id": "1", "nama": "Pintu"}])
        login(client, "admin", ADMIN_PW)

        resp = client.get("/admin/ptz", headers={"accept": "text/html"})
        assert resp.status_code == 200
        assert "PTZ siap" in resp.text
        for arah in ("atas", "bawah", "kiri", "kanan"):
            assert f'data-arah="{arah}"' in resp.text
        assert "Pintu" in resp.text


class TestAksi:
    def test_gerak_tercatat_di_audit(self, client, db, admin_user, monkeypatch):
        kamera = buat_kamera(db, "lantai-atas")
        dipanggil = []

        def palsu(stream_key, arah):
            dipanggil.append((stream_key, arah))
            return {"ok": True, "arah": arah}

        monkeypatch.setattr("app.routers.admin_ptz.ptz.gerak", palsu)
        login(client, "admin", ADMIN_PW)

        resp = client.post("/admin/api/ptz/lantai-atas", data={"aksi": "gerak", "arah": "kiri"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert dipanggil == [("lantai-atas", "kiri")]

        log = db.query(AccessLog).filter(AccessLog.action == ACTION_PTZ).all()
        assert len(log) == 1
        assert log[0].camera_id == kamera.id
        assert "kiri" in (log[0].detail or "")

    def test_arah_tidak_dikenal_400(self, client, db, admin_user):
        buat_kamera(db, "lantai-atas")
        login(client, "admin", ADMIN_PW)
        resp = client.post("/admin/api/ptz/lantai-atas", data={"aksi": "gerak", "arah": "miring"})
        assert resp.status_code == 400
        log = db.query(AccessLog).filter(AccessLog.action == ACTION_PTZ_FAILED).count()
        assert log == 1

    def test_kamera_gagal_jadi_503(self, client, db, admin_user, monkeypatch):
        buat_kamera(db, "lantai-atas")

        def gagal(stream_key, arah):
            raise RuntimeError("Invalid authentication data")

        monkeypatch.setattr("app.routers.admin_ptz.ptz.gerak", gagal)
        login(client, "admin", ADMIN_PW)

        resp = client.post("/admin/api/ptz/lantai-atas", data={"aksi": "gerak", "arah": "kanan"})
        assert resp.status_code == 503
        assert "Kamera tidak merespons" in resp.json()["detail"]

    def test_slug_tidak_ada_404(self, client, db, admin_user):
        login(client, "admin", ADMIN_PW)
        assert client.post("/admin/api/ptz/entah", data={"aksi": "gerak", "arah": "kiri"}).status_code == 404

    def test_rate_limit_429(self, client, db, admin_user, monkeypatch):
        buat_kamera(db, "lantai-atas")
        monkeypatch.setattr("app.routers.admin_ptz.ptz.gerak", lambda key, arah: {"ok": True})
        monkeypatch.setattr(ptz, "BATAS_GERAK", 2)
        ptz.lupakan_semua()
        login(client, "admin", ADMIN_PW)

        kode = [client.post("/admin/api/ptz/lantai-atas",
                            data={"aksi": "gerak", "arah": "kiri"}).status_code for _ in range(3)]
        assert kode == [200, 200, 429]


class TestModulPtz:
    def test_parse_kemampuan(self):
        assert ptz._parse_kemampuan({"motor": {"capability": {"horizontal": 1, "vertical": 1}}}) == {
            "pan": True, "tilt": True, "zoom": False}
        assert ptz._parse_kemampuan({"motor": {"capability": {"zoom": 1}}})["zoom"] is True
        assert ptz._parse_kemampuan({})["pan"] is False

    def test_konfigurasi_kosong_tidak_aktif(self, tmp_path, monkeypatch):
        kosong = tmp_path / "ptz.env"
        kosong.write_text("# kosong\n", encoding="utf-8")
        monkeypatch.setattr(ptz, "PTZ_ENV", str(kosong))
        ptz.lupakan_semua()
        konf = ptz.konfigurasi()
        assert konf["aktif"] is False

    def test_konfigurasi_membaca_peta_host(self, tmp_path, monkeypatch):
        berkas = tmp_path / "ptz.env"
        berkas.write_text(
            "TAPO_USER=a@b.c\nTAPO_PASS=rahasia\nPTZ_HOSTS=cam140=192.168.18.140,cam142=192.168.18.142\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(ptz, "PTZ_ENV", str(berkas))
        ptz.lupakan_semua()
        konf = ptz.konfigurasi()
        assert konf["aktif"] is True
        assert konf["hosts"] == {"cam140": "192.168.18.140", "cam142": "192.168.18.142"}

    def test_kamera_tanpa_host_tidak_didukung(self, tmp_path, monkeypatch):
        berkas = tmp_path / "ptz.env"
        berkas.write_text("TAPO_USER=a@b.c\nTAPO_PASS=rahasia\nPTZ_HOSTS=cam140=192.168.18.140\n",
                          encoding="utf-8")
        monkeypatch.setattr(ptz, "PTZ_ENV", str(berkas))
        ptz.lupakan_semua()
        hasil = ptz.kemampuan("gudang")
        assert hasil["didukung"] is False
        assert "tidak terdaftar" in hasil["alasan"]

    def test_gerak_menolak_arah_asing(self, tmp_path, monkeypatch):
        with pytest.raises(ValueError):
            ptz.gerak("lantai-atas", "serong")
