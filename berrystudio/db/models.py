"""SQLAlchemy ORM 模型。

设计原则：

1. 所有业务表都带 ``created_at`` / ``updated_at``，方便后台审计；
2. 可变扩展字段放在 ``extra`` JSON 列里，新增小字段无需立刻改表结构；
3. 状态字段使用字符串常量而不是数据库枚举，未来新增状态无需迁移；
4. 每次状态变化写入 ``booking_logs``，管理员操作写入 ``audit_logs``。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """统一以 UTC 存储时间，读取时恢复为带时区的 UTC datetime。

    SQLite 原生不保存时区偏移，直接使用 ``DateTime(timezone=True)``
    会在读回时丢失时区信息。这里在写入前统一转换为 UTC 并去掉 tzinfo，
    读取时再补回 UTC，避免不同服务器时区导致的时间错位。
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class UserRole:
    USER = "user"
    ADMIN = "admin"

    LABELS = {USER: "用户", ADMIN: "管理员"}


class UserStatus:
    ACTIVE = "active"
    BANNED = "banned"

    LABELS = {ACTIVE: "正常", BANNED: "已封禁"}


class SceneKind:
    REHEARSAL = "rehearsal"
    RECORDING = "recording"
    PERFORMANCE = "performance"
    OTHER = "other"

    LABELS = {
        REHEARSAL: "排练",
        RECORDING: "录音",
        PERFORMANCE: "演出",
        OTHER: "其他",
    }


class BookingStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"

    LABELS = {
        PENDING: "待审核",
        APPROVED: "已通过",
        REJECTED: "已驳回",
        CANCELLED: "已取消",
        COMPLETED: "已完成",
        NO_SHOW: "爽约",
    }

    # 会占用时段的状态
    OCCUPYING = (PENDING, APPROVED)

    # 用户可以主动取消的状态
    CANCELABLE = (PENDING, APPROVED)


class SchemaVersion(Base):
    __tablename__ = "schema_version"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    applied_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AppSetting(Base):
    """键值配置表，为后期拓展（例如开放时间、公告、开关）预留。"""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    qq: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(64), default="")
    nickname: Mapped[str] = mapped_column(String(64), default="")
    role: Mapped[str] = mapped_column(String(16), default=UserRole.USER, index=True)
    status: Mapped[str] = mapped_column(String(16), default=UserStatus.ACTIVE, index=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    led_bands: Mapped[list["Band"]] = relationship(
        back_populates="leader", foreign_keys="Band.leader_id"
    )
    memberships: Mapped[list["BandMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def name(self) -> str:
        return self.display_name or self.nickname or self.qq


class Band(Base):
    __tablename__ = "bands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    style: Mapped[str] = mapped_column(String(64), default="")
    description: Mapped[str] = mapped_column(String(255), default="")
    leader_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    invite_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow
    )
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    leader: Mapped[User | None] = relationship(
        back_populates="led_bands", foreign_keys=[leader_id]
    )
    members: Mapped[list["BandMember"]] = relationship(
        back_populates="band", cascade="all, delete-orphan", lazy="selectin"
    )


class BandMember(Base):
    __tablename__ = "band_members"
    __table_args__ = (UniqueConstraint("band_id", "user_id", name="uq_band_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    band_id: Mapped[int] = mapped_column(ForeignKey("bands.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="member")
    instrument: Mapped[str] = mapped_column(String(32), default="")
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    band: Mapped[Band] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships", lazy="joined")


class Scene(Base):
    """可预约场景 / 场地（排练室、录音棚、演出厅……管理员可增删改）。"""

    __tablename__ = "scenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16), default=SceneKind.REHEARSAL, index=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    capacity: Mapped[int] = mapped_column(Integer, default=6)
    hourly_price: Mapped[int] = mapped_column(Integer, default=0)
    open_hour: Mapped[int] = mapped_column(Integer, default=9)
    close_hour: Mapped[int] = mapped_column(Integer, default=23)
    min_minutes: Mapped[int] = mapped_column(Integer, default=60)
    max_minutes: Mapped[int] = mapped_column(Integer, default=240)
    slot_minutes: Mapped[int] = mapped_column(Integer, default=30)
    color: Mapped[str] = mapped_column(String(16), default="#5EEAD4")
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    is_bookable: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow
    )
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        Index("ix_bookings_scene_time", "scene_id", "start_at", "end_at"),
        Index("ix_bookings_status_time", "status", "start_at"),
        Index("ix_bookings_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True, default="")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    band_id: Mapped[int | None] = mapped_column(
        ForeignKey("bands.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scene_id: Mapped[int] = mapped_column(ForeignKey("scenes.id", ondelete="RESTRICT"), index=True)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(
        String(16), default=BookingStatus.PENDING, index=True
    )
    title: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(String(255), default="")
    attendees: Mapped[int] = mapped_column(Integer, default=1)
    hourly_price: Mapped[int] = mapped_column(Integer, default=0)
    price_estimate: Mapped[int] = mapped_column(Integer, default=0)
    review_note: Mapped[str] = mapped_column(String(255), default="")
    reviewed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    cancelled_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    group_id: Mapped[str] = mapped_column(String(24), default="")
    source: Mapped[str] = mapped_column(String(16), default="bot")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow
    )
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    scene: Mapped[Scene] = relationship(lazy="joined")
    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="joined")
    band: Mapped[Band | None] = relationship(foreign_keys=[band_id], lazy="joined")


class BookingLog(Base):
    __tablename__ = "booking_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str] = mapped_column(String(16), default="")
    to_status: Mapped[str] = mapped_column(String(16), default="")
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AuditLog(Base):
    """管理员后台操作审计。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_qq: Mapped[str] = mapped_column(String(20), default="")
    action: Mapped[str] = mapped_column(String(32), index=True)
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_id: Mapped[str] = mapped_column(String(32), default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
