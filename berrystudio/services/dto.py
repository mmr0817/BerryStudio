"""展示 / 通知用的纯数据对象（与 ORM 会话解耦）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from berrystudio.db.models import Band, Booking, Scene, User
from berrystudio.utils.format import status_label


@dataclass(frozen=True)
class BookingView:
    id: int
    code: str
    status: str
    status_label: str
    scene_name: str
    scene_code: str
    scene_color: str
    scene_kind: str
    user_id: int
    owner_name: str
    owner_qq: str
    band_name: str
    title: str
    note: str
    attendees: int
    price_estimate: int
    start: datetime
    end: datetime
    duration_minutes: int
    review_note: str
    created_at: datetime
    reviewed_at: datetime | None
    group_id: str
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def date_key(self) -> str:
        return self.start.strftime("%Y-%m-%d")


@dataclass(frozen=True)
class SceneView:
    id: int
    code: str
    name: str
    kind: str
    description: str
    capacity: int
    hourly_price: int
    open_hour: int
    close_hour: int
    min_minutes: int
    max_minutes: int
    slot_minutes: int
    color: str
    is_bookable: bool


@dataclass(frozen=True)
class BandView:
    id: int
    name: str
    style: str
    description: str
    invite_code: str
    leader_name: str
    member_count: int


@dataclass(frozen=True)
class UserView:
    id: int
    qq: str
    name: str
    role: str
    status: str
    created_at: datetime


def scene_view(scene: Scene) -> SceneView:
    return SceneView(
        id=scene.id,
        code=scene.code,
        name=scene.name,
        kind=scene.kind,
        description=scene.description,
        capacity=scene.capacity,
        hourly_price=scene.hourly_price,
        open_hour=scene.open_hour,
        close_hour=scene.close_hour,
        min_minutes=scene.min_minutes,
        max_minutes=scene.max_minutes,
        slot_minutes=scene.slot_minutes,
        color=scene.color,
        is_bookable=scene.is_bookable,
    )


def band_view(band: Band, *, member_count: int | None = None) -> BandView:
    return BandView(
        id=band.id,
        name=band.name,
        style=band.style,
        description=band.description,
        invite_code=band.invite_code,
        leader_name=band.leader.name if band.leader else "",
        member_count=member_count if member_count is not None else len(band.members),
    )


def user_view(user: User) -> UserView:
    return UserView(
        id=user.id,
        qq=user.qq,
        name=user.name,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
    )


def booking_view(booking: Booking) -> BookingView:
    return BookingView(
        id=booking.id,
        code=booking.code,
        status=booking.status,
        status_label=status_label(booking.status),
        scene_name=booking.scene.name,
        scene_code=booking.scene.code,
        scene_color=booking.scene.color,
        scene_kind=booking.scene.kind,
        user_id=booking.user_id,
        owner_name=booking.user.name,
        owner_qq=booking.user.qq,
        band_name=booking.band.name if booking.band else "",
        title=booking.title,
        note=booking.note,
        attendees=booking.attendees,
        price_estimate=booking.price_estimate,
        start=booking.start_at,
        end=booking.end_at,
        duration_minutes=int((booking.end_at - booking.start_at).total_seconds() // 60),
        review_note=booking.review_note,
        created_at=booking.created_at,
        reviewed_at=booking.reviewed_at,
        group_id=booking.group_id,
        extra=dict(booking.extra or {}),
    )
