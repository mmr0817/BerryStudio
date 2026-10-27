"""HTTP 管理后台（FastAPI）。

默认关闭：只有在 ``.env`` 配置了 ``BERRY_ADMIN_API_TOKEN`` 后才会响应业务接口。
鉴权方式：请求头 ``X-Admin-Token: <token>`` 或查询参数 ``?token=<token>``。

接口一览（前缀 /admin/api）::

    GET    /bookings?status=pending&date_from=2026-10-01&date_to=2026-11-01
    GET    /bookings/pending
    POST   /bookings/{code}/approve      {"note": "..."}
    POST   /bookings/{code}/reject       {"reason": "..."}
    POST   /bookings/{code}/cancel       {"reason": "..."}
    GET    /users?keyword=
    GET    /users/{qq}
    POST   /users/{qq}/role              {"role": "admin"}
    POST   /users/{qq}/status            {"status": "banned"}
    GET    /scenes
    POST   /scenes                       {"code": "...", "name": "...", "kind": "rehearsal"}
    PATCH  /scenes/{code}                {"hourly_price": 90}
    POST   /scenes/{code}/bookable       {"enabled": false}
    GET    /stats?days=30
    GET    /audit?limit=20
"""

from __future__ import annotations

import hmac
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from berrystudio.config import Settings
from berrystudio.db.models import BookingStatus, SceneKind, UserRole, UserStatus
from berrystudio.db.session import session_scope
from berrystudio.services import audit
from berrystudio.services.bookings import (
    approve_booking,
    bookings_between,
    cancel_booking,
    get_booking_by_code,
    pending_bookings,
    recent_bookings,
    reject_booking,
)
from berrystudio.services.dto import booking_view, scene_view, user_view
from berrystudio.services.errors import BerryError
from berrystudio.services.scenes import (
    create_scene,
    get_scene,
    list_scenes,
    set_bookable,
    update_scene,
)
from berrystudio.services.stats import studio_stats, user_stats
from berrystudio.services.users import (
    add_admin,
    get_user,
    list_users,
    remove_admin,
    set_status,
)
from berrystudio.utils.format import fmt_hours


class SceneCreatePayload(BaseModel):
    code: str
    name: str
    kind: str = SceneKind.REHEARSAL
    description: str = ""
    capacity: int = 6
    hourly_price: int = 0
    open_hour: int = 9
    close_hour: int = 23
    min_minutes: int = 60
    max_minutes: int = 240
    slot_minutes: int = 30
    color: str = "#5EEAD4"


class SceneUpdatePayload(BaseModel):
    code: str | None = None
    name: str | None = None
    kind: str | None = None
    description: str | None = None
    capacity: int | None = None
    hourly_price: int | None = None
    open_hour: int | None = None
    close_hour: int | None = None
    min_minutes: int | None = None
    max_minutes: int | None = None
    slot_minutes: int | None = None
    color: str | None = None
    is_bookable: bool | None = None


class NotePayload(BaseModel):
    note: str = ""


class ReasonPayload(BaseModel):
    reason: str = ""


class RolePayload(BaseModel):
    role: str


class StatusPayload(BaseModel):
    status: str


class BookablePayload(BaseModel):
    enabled: bool


def _parse_date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field} 需要 YYYY-MM-DD 格式") from exc


def build_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/admin/api", tags=["berrystudio-admin"])

    def verify(
        header_token: str | None = Header(default=None, alias="X-Admin-Token"),
        query_token: str | None = Query(default=None, alias="token"),
    ) -> None:
        expected = settings.admin_api_token
        if not expected:
            raise HTTPException(
                status_code=503,
                detail="HTTP 后台未启用：请在 .env 配置 BERRY_ADMIN_API_TOKEN",
            )
        if not header_token and not query_token:
            raise HTTPException(status_code=401, detail="缺少管理令牌")
        if not (
            (header_token and hmac.compare_digest(header_token, expected))
            or (query_token and hmac.compare_digest(query_token, expected))
        ):
            raise HTTPException(status_code=401, detail="管理令牌无效")

    auth = Depends(verify)

    def guard(func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except BerryError as exc:
            raise HTTPException(status_code=400, detail=exc.message) from exc

    tz = settings.tz

    @router.get("/bookings", dependencies=[auth])
    def list_bookings(
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        statuses = tuple(item for item in (status or "").split(",") if item) or None
        start_day = _parse_date(date_from, "date_from")
        end_day = _parse_date(date_to, "date_to")
        with session_scope() as session:
            if start_day or end_day:
                start = datetime.combine(
                    start_day or date.today(), datetime.min.time(), tzinfo=tz
                )
                end = datetime.combine(
                    (end_day + timedelta(days=1)) if end_day else date.today() + timedelta(days=1),
                    datetime.min.time(),
                    tzinfo=tz,
                )
                bookings = bookings_between(
                    session,
                    start,
                    end,
                    statuses=statuses or (
                        BookingStatus.PENDING,
                        BookingStatus.APPROVED,
                        BookingStatus.COMPLETED,
                        BookingStatus.REJECTED,
                        BookingStatus.CANCELLED,
                    ),
                    limit=limit,
                )
            else:
                bookings = recent_bookings(session, statuses=statuses, limit=limit)
            return [asdict(booking_view(item)) for item in bookings]

    @router.get("/bookings/pending", dependencies=[auth])
    def list_pending(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
        with session_scope() as session:
            return [asdict(booking_view(item)) for item in pending_bookings(session, limit=limit)]

    @router.post("/bookings/{code}/approve", dependencies=[auth])
    def api_approve(code: str, payload: NotePayload) -> dict[str, Any]:
        with session_scope() as session:
            booking = guard(get_booking_by_code, session, code)
            guard(approve_booking, session, booking, None, note=payload.note)
            audit.record(
                session,
                None,
                "booking.approve",
                target_type="booking",
                target_id=booking.code,
                detail={"note": payload.note, "channel": "http"},
            )
            return asdict(booking_view(booking))

    @router.post("/bookings/{code}/reject", dependencies=[auth])
    def api_reject(code: str, payload: ReasonPayload) -> dict[str, Any]:
        with session_scope() as session:
            booking = guard(get_booking_by_code, session, code)
            guard(reject_booking, session, booking, None, reason=payload.reason)
            audit.record(
                session,
                None,
                "booking.reject",
                target_type="booking",
                target_id=booking.code,
                detail={"reason": payload.reason, "channel": "http"},
            )
            return asdict(booking_view(booking))

    @router.post("/bookings/{code}/cancel", dependencies=[auth])
    def api_cancel(code: str, payload: ReasonPayload) -> dict[str, Any]:
        with session_scope() as session:
            booking = guard(get_booking_by_code, session, code)
            guard(
                cancel_booking,
                session,
                booking,
                None,
                reason=payload.reason,
                by_admin=True,
            )
            audit.record(
                session,
                None,
                "booking.cancel",
                target_type="booking",
                target_id=booking.code,
                detail={"reason": payload.reason, "channel": "http"},
            )
            return asdict(booking_view(booking))

    @router.get("/users", dependencies=[auth])
    def api_users(keyword: str = "", limit: int = Query(default=50, ge=1, le=200)):
        with session_scope() as session:
            users = list_users(session, keyword=keyword, limit=limit)
            result = []
            for user in users:
                data = asdict(user_view(user))
                stats = user_stats(session, user)
                data["total_bookings"] = stats.total_bookings
                data["pending_bookings"] = stats.pending_bookings
                data["bands"] = stats.bands
                result.append(data)
            return result

    @router.get("/users/{qq}", dependencies=[auth])
    def api_user(qq: str):
        with session_scope() as session:
            user = get_user(session, qq)
            if user is None:
                raise HTTPException(status_code=404, detail="用户不存在")
            stats = user_stats(session, user)
            data = asdict(user_view(user))
            data.update(
                {
                    "bands": stats.bands,
                    "total_bookings": stats.total_bookings,
                    "pending_bookings": stats.pending_bookings,
                    "total_minutes": stats.total_minutes,
                }
            )
            return data

    @router.post("/users/{qq}/role", dependencies=[auth])
    def api_set_role(qq: str, payload: RolePayload):
        if payload.role not in {UserRole.USER, UserRole.ADMIN}:
            raise HTTPException(status_code=422, detail="role 只能是 user / admin")
        with session_scope() as session:
            user = get_user(session, qq)
            if user is None:
                raise HTTPException(status_code=404, detail="用户不存在")
            if payload.role == UserRole.ADMIN:
                user = add_admin(session, qq)
            else:
                user = remove_admin(session, qq)
            audit.record(
                session, None, "user.set_role", target_type="user", target_id=qq,
                detail={"role": payload.role, "channel": "http"},
            )
            return asdict(user_view(user))

    @router.post("/users/{qq}/status", dependencies=[auth])
    def api_set_status(qq: str, payload: StatusPayload):
        if payload.status not in {UserStatus.ACTIVE, UserStatus.BANNED}:
            raise HTTPException(status_code=422, detail="status 只能是 active / banned")
        with session_scope() as session:
            user = get_user(session, qq)
            if user is None:
                raise HTTPException(status_code=404, detail="用户不存在")
            set_status(session, user, payload.status)
            audit.record(
                session, None, "user.set_status", target_type="user", target_id=qq,
                detail={"status": payload.status, "channel": "http"},
            )
            return asdict(user_view(user))

    @router.get("/scenes", dependencies=[auth])
    def api_scenes():
        with session_scope() as session:
            return [asdict(scene_view(item)) for item in list_scenes(session, bookable_only=False)]

    @router.post("/scenes", dependencies=[auth])
    def api_create_scene(payload: SceneCreatePayload):
        with session_scope() as session:
            scene = guard(create_scene, session, **payload.model_dump())
            audit.record(
                session, None, "scene.create", target_type="scene", target_id=scene.code,
                detail={"channel": "http"},
            )
            return asdict(scene_view(scene))

    @router.patch("/scenes/{code}", dependencies=[auth])
    def api_update_scene(code: str, payload: SceneUpdatePayload):
        with session_scope() as session:
            scene = get_scene(session, code)
            if scene is None:
                raise HTTPException(status_code=404, detail="场景不存在")
            updates = payload.model_dump(exclude_none=True)
            bookable = updates.pop("is_bookable", None)
            if updates:
                guard(update_scene, session, scene, updates)
            if bookable is not None:
                set_bookable(session, scene, bookable)
            audit.record(
                session, None, "scene.update", target_type="scene", target_id=scene.code,
                detail={"fields": list(updates), "channel": "http"},
            )
            return asdict(scene_view(scene))

    @router.post("/scenes/{code}/bookable", dependencies=[auth])
    def api_scene_bookable(code: str, payload: BookablePayload):
        with session_scope() as session:
            scene = get_scene(session, code)
            if scene is None:
                raise HTTPException(status_code=404, detail="场景不存在")
            set_bookable(session, scene, payload.enabled)
            audit.record(
                session, None, "scene.bookable", target_type="scene", target_id=scene.code,
                detail={"enabled": payload.enabled, "channel": "http"},
            )
            return asdict(scene_view(scene))

    @router.get("/stats", dependencies=[auth])
    def api_stats(days: int = Query(default=30, ge=1, le=365)):
        # 统计窗口：今天前后各 days 天，便于同时看到历史与未来预约
        today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=days)
        end = today + timedelta(days=days + 1)
        with session_scope() as session:
            stats = studio_stats(session, start, end)
            return {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "total_bookings": stats.total_bookings,
                "approved": stats.approved,
                "pending": stats.pending,
                "rejected": stats.rejected,
                "cancelled": stats.cancelled,
                "minutes": stats.minutes,
                "hours": fmt_hours(stats.minutes),
                "revenue": stats.revenue,
                "occupancy": round(stats.occupancy, 4),
                "active_users": stats.active_users,
                "scenes": [asdict(item) for item in stats.scene_stats],
                "top_bands": stats.top_bands,
            }

    @router.get("/audit", dependencies=[auth])
    def api_audit(limit: int = Query(default=20, ge=1, le=200)):
        with session_scope() as session:
            logs = audit.recent(session, limit=limit)
            return [
                {
                    "id": log.id,
                    "actor_qq": log.actor_qq,
                    "action": log.action,
                    "target_type": log.target_type,
                    "target_id": log.target_id,
                    "detail": log.detail,
                    "created_at": log.created_at,
                }
                for log in logs
            ]

    return router
