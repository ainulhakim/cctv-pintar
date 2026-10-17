"""Model database.

Catatan keamanan: kredensial kamera TIDAK disimpan di aplikasi ini.
Kredensial RTSP hanya ada di konfigurasi MediaMTX di server rumah.
App hanya menyimpan `slug` (URL publik) dan `stream_key` (nama path di MediaMTX).
"""

from __future__ import annotations

import datetime as dt
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

ROLE_ADMIN = "admin"
ROLE_VIEWER = "viewer"
VALID_ROLES = (ROLE_ADMIN, ROLE_VIEWER)

MODE_PUBLIC = "public"
MODE_SCHEDULED = "scheduled"
VALID_MODES = (MODE_PUBLIC, MODE_SCHEDULED)

# Konvensi hari: Senin=0 ... Minggu=6 (sama dengan datetime.weekday()).
DAYS_ALL = "0,1,2,3,4,5,6"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default=ROLE_VIEWER, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    def __repr__(self) -> str:  # pragma: no cover - bantu debug
        return f"<User {self.username} ({self.role})>"


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(255))
    # nama path di MediaMTX (bukan kredensial kamera)
    stream_key: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    policy: Mapped[Optional["AccessPolicy"]] = relationship(
        back_populates="camera", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Camera {self.slug}>"


class AccessPolicy(Base):
    """Kebijakan akses per kamera (requirement #2).

    mode=public    -> dapat diakses 24 jam.
    mode=scheduled -> hanya pada hari & jam tertentu (mendukung lintas tengah malam).
    """

    __tablename__ = "access_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    mode: Mapped[str] = mapped_column(String(16), default=MODE_PUBLIC, nullable=False)
    # daftar hari dipisah koma, contoh "0,1,2,3,4" (Senin=0 .. Minggu=6)
    days: Mapped[str] = mapped_column(String(32), default=DAYS_ALL, nullable=False)
    start_time: Mapped[Optional[dt.time]] = mapped_column(Time)
    end_time: Mapped[Optional[dt.time]] = mapped_column(Time)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Jakarta", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    camera: Mapped[Camera] = relationship(back_populates="policy")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AccessPolicy cam={self.camera_id} mode={self.mode}>"


class AccessLog(Base):
    __tablename__ = "access_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    camera_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text)
    ip: Mapped[Optional[str]] = mapped_column(String(64))
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, index=True, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AccessLog {self.action} at={self.at}>"
