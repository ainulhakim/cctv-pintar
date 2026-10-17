"""Test alur autentikasi: login, logout, guard halaman."""

from __future__ import annotations

from tests.conftest import ADMIN_PW, VIEWER_PW, login


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_halaman_login_tampil(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "Masuk" in resp.text


def test_akses_tanpa_sesi_401_json(client):
    resp = client.get("/")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Perlu login"


def test_akses_tanpa_sesi_dari_browser_redirect(client):
    resp = client.get("/", headers={"accept": "text/html"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_login_password_salah(client, admin_user):
    resp = login(client, "admin", "salah-banget")
    assert resp.status_code == 401
    assert "Username atau password salah" in resp.text
    assert "set-cookie" not in resp.headers


def test_login_username_tidak_ada(client, admin_user):
    resp = login(client, "hantu", ADMIN_PW)
    assert resp.status_code == 401


def test_login_sukses_set_cookie(client, admin_user):
    resp = login(client, "admin", ADMIN_PW)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    cookie = resp.headers["set-cookie"]
    assert "cctv_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie.lower() or "samesite=lax" in cookie.lower()


def test_login_lalu_buka_dashboard(client, admin_user):
    login(client, "admin", ADMIN_PW)
    resp = client.get("/", headers={"accept": "text/html"})
    assert resp.status_code == 200
    assert "admin" in resp.text


def test_login_redirect_ke_next(client, admin_user):
    resp = client.post(
        "/login",
        data={"username": "admin", "password": ADMIN_PW, "next": "/admin/"},
        follow_redirects=False,
    )
    assert resp.headers["location"] == "/admin/"


def test_next_open_redirect_ditolak(client, admin_user):
    resp = client.post(
        "/login",
        data={"username": "admin", "password": ADMIN_PW, "next": "//evil.example.com"},
        follow_redirects=False,
    )
    assert resp.headers["location"] == "/"


def test_user_nonaktif_tidak_bisa_login(client, db):
    from tests.conftest import _make_user
    from app.models import ROLE_VIEWER

    _make_user(db, "nonaktif", "password123", ROLE_VIEWER, active=False)
    resp = login(client, "nonaktif", "password123")
    assert resp.status_code == 401


def test_viewer_ditolak_ke_admin(client, viewer_user):
    login(client, "viewer", VIEWER_PW)
    resp = client.get("/admin/")
    assert resp.status_code == 403


def test_admin_bisa_buka_admin(client, admin_user):
    login(client, "admin", ADMIN_PW)
    resp = client.get("/admin/", headers={"accept": "text/html"})
    assert resp.status_code == 200
    assert "Panel Admin" in resp.text


def test_logout_hapus_sesi(client, admin_user):
    login(client, "admin", ADMIN_PW)
    assert client.get("/", headers={"accept": "text/html"}).status_code == 200

    resp = client.post("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
    # cookie dihapus -> akses berikutnya 401
    assert client.get("/").status_code == 401


def test_cookie_ngawur_ditolak(client, admin_user):
    client.cookies.set("cctv_session", "token-ngawur")
    assert client.get("/").status_code == 401


def test_halaman_login_saat_sudah_masuk_redirect(client, admin_user):
    login(client, "admin", ADMIN_PW)
    resp = client.get("/login", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_header_keamanan_ada(client):
    resp = client.get("/healthz")
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_log_akses_tercatat(client, admin_user, db):
    from app.models import AccessLog

    login(client, "admin", "salah")
    login(client, "admin", ADMIN_PW)
    actions = {row.action for row in db.query(AccessLog).all()}
    assert "login_failed" in actions
    assert "login_ok" in actions
