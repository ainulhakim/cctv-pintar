"""Test deteksi kesehatan kamera (`app/health.py`).

Bug yang dijaga di sini: MediaMTX memakai `runOnDemand`, jadi path yang sedang
tidak ditonton tidak pernah "ready". Sebelum perbaikan, semua kamera dilaporkan
offline saat viewer sepi — padahal kamera sehat.
"""

from __future__ import annotations

from app import health
from app.config import settings


def test_publisher_aktif_selalu_live(monkeypatch):
    health.reset()
    monkeypatch.setattr(settings, "live_probe", True)
    assert health.state("utara", True) == health.LIVE


def test_tanpa_publisher_dan_tanpa_probe_bukan_offline(monkeypatch):
    """Ketidaktahuan tidak boleh dilaporkan sebagai offline."""
    health.reset()
    monkeypatch.setattr(settings, "live_probe", False)
    assert health.state("balai", False) == health.SIAP


def test_probe_gagal_menjadi_offline(monkeypatch):
    health.reset()
    monkeypatch.setattr(settings, "live_probe", True)
    monkeypatch.setattr(settings, "live_probe_ttl", 90.0)
    monkeypatch.setattr(settings, "live_probe_timeout", 0.1)
    monkeypatch.setattr(health, "_ffprobe", lambda key, timeout: False)

    # probe dijalankan di thread; jalankan sinkron agar deterministik
    health._kerja("camkantor", 0.1)
    assert health.state("camkantor", False) == health.OFFLINE


def test_probe_sukses_hanya_siap_bukan_live(monkeypatch):
    """Ada video saat diprobe, tapi tidak ada penonton -> siaga, bukan live."""
    health.reset()
    monkeypatch.setattr(settings, "live_probe", True)
    monkeypatch.setattr(settings, "live_probe_ttl", 90.0)
    monkeypatch.setattr(health, "_ffprobe", lambda key, timeout: True)

    health._kerja("selatan", 0.1)
    assert health.state("selatan", False) == health.SIAP


def test_hasil_probe_di_cache_selama_ttl(monkeypatch):
    health.reset()
    monkeypatch.setattr(settings, "live_probe", True)
    monkeypatch.setattr(settings, "live_probe_ttl", 3600.0)
    monkeypatch.setattr(health, "_ffprobe", lambda key, timeout: False)
    health._kerja("balai", 0.1)

    dipanggil = {"n": 0}

    def probe_lagi(key, timeout):
        dipanggil["n"] += 1
        return True

    monkeypatch.setattr(health, "_ffprobe", probe_lagi)
    assert health.state("balai", False) == health.OFFLINE
    assert dipanggil["n"] == 0  # masih dalam TTL, probe tidak diulang


def test_publisher_hidup_menimpa_hasil_probe_lama(monkeypatch):
    health.reset()
    monkeypatch.setattr(settings, "live_probe", True)
    monkeypatch.setattr(settings, "live_probe_ttl", 3600.0)
    monkeypatch.setattr(health, "_ffprobe", lambda key, timeout: False)
    health._kerja("utara", 0.1)
    assert health.state("utara", False) == health.OFFLINE
    assert health.state("utara", True) == health.LIVE
    assert health.state("utara", False) == health.LIVE
