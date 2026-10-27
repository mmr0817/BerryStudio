"""服务器端命令行管理工具。

常用操作::

    python -m berrystudio.cli init-db
    python -m berrystudio.cli add-admin 123456789 --name 店长
    python -m berrystudio.cli list-admins
    python -m berrystudio.cli bookings --status pending
    python -m berrystudio.cli approve B261028001 --note 已确认
    python -m berrystudio.cli stats --days 30
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path

from berrystudio.config import get_settings
from berrystudio.db.migrate import schema_version
from berrystudio.db.models import BookingStatus
from berrystudio.db.session import get_engine, init_database, session_scope
from berrystudio.services import audit
from berrystudio.services.bookings import (
    approve_booking,
    archive_past_bookings,
    bookings_between,
    cancel_booking,
    get_booking_by_code,
    pending_count,
    recent_bookings,
    reject_booking,
)
from berrystudio.services.dto import booking_view, scene_view, user_view
from berrystudio.services.errors import BerryError
from berrystudio.services.scenes import (
    get_scene,
    list_scenes,
    set_bookable,
    update_scene,
)
from berrystudio.services.scenes import create_scene as create_scene_service
from berrystudio.services.stats import studio_stats
from berrystudio.services.users import (
    add_admin,
    list_admins,
    list_users,
    remove_admin,
)
from berrystudio.utils.format import fmt_hours, fmt_range


def _db_url(path: str | None) -> str:
    if not path:
        return get_settings().db_url
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+pysqlite:///{resolved}"


def _prepare(args: argparse.Namespace) -> None:
    url = _db_url(getattr(args, "db", None))
    applied = init_database(url)
    if getattr(args, "verbose", False):
        print(f"数据库：{url}")
        print(f"schema 版本：{schema_version(get_engine())}，本次迁移：{applied or '无'}")


def cmd_init_db(args: argparse.Namespace) -> None:
    _prepare(args)
    print(f"数据库已就绪：{_db_url(getattr(args, 'db', None))}")


def cmd_add_admin(args: argparse.Namespace) -> None:
    _prepare(args)
    with session_scope() as session:
        user = add_admin(session, args.qq, display_name=args.name)
        audit.record(
            session, None, "admin.add.cli", target_type="user", target_id=user.qq,
            detail={"name": args.name},
        )
        print(f"已添加管理员：{user.name}（{user.qq}）")


def cmd_remove_admin(args: argparse.Namespace) -> None:
    _prepare(args)
    with session_scope() as session:
        user = remove_admin(session, args.qq)
        audit.record(
            session, None, "admin.remove.cli", target_type="user", target_id=user.qq
        )
        print(f"已移除管理员：{user.name}（{user.qq}）")
        if str(args.qq) in get_settings().admin_qqs:
            print("注意：该 QQ 仍存在于 .env 的 SUPERUSERS / BERRY_ADMIN_QQ")


def cmd_list_admins(args: argparse.Namespace) -> None:
    _prepare(args)
    with session_scope() as session:
        admins = list_admins(session)
        print(f"数据库管理员（{len(admins)} 人）：")
        for user in admins:
            print(f"  - {user.name}（{user.qq}）")
        configured = get_settings().admin_qqs
        print("配置超级管理员：" + ("、".join(configured) if configured else "未配置"))


def cmd_list_users(args: argparse.Namespace) -> None:
    _prepare(args)
    with session_scope() as session:
        users = list_users(session, keyword=args.keyword, limit=args.limit)
        print(f"用户（{len(users)} 条）：")
        for user in users:
            print(
                f"  - {user.name}（{user.qq}）role={user.role} status={user.status} "
                f"joined={user.created_at:%Y-%m-%d}"
            )


def cmd_list_scenes(args: argparse.Namespace) -> None:
    _prepare(args)
    with session_scope() as session:
        scenes = list_scenes(session, bookable_only=False)
        if not scenes:
            print("还没有场景，运行 add-scene 或首次 init-db 会自动写入默认场景")
            return
        for scene in scenes:
            view = scene_view(scene)
            print(
                f"{view.code:8} {view.name}（{view.kind}）"
                f"{'开放' if view.is_bookable else '关闭'} "
                f"{view.open_hour:02d}-{view.close_hour:02d} ¥{view.hourly_price}/h "
                f"{view.min_minutes}-{view.max_minutes}min slot={view.slot_minutes}"
            )


def cmd_add_scene(args: argparse.Namespace) -> None:
    _prepare(args)
    fields = {
        "code": args.code,
        "name": args.name,
        "kind": args.kind,
        "hourly_price": args.price,
        "open_hour": args.open_hour,
        "close_hour": args.close_hour,
        "min_minutes": args.min_minutes,
        "max_minutes": args.max_minutes,
        "slot_minutes": args.slot_minutes,
        "capacity": args.capacity,
        "color": args.color,
        "description": args.description,
    }
    with session_scope() as session:
        scene = create_scene_service(session, **fields)
        audit.record(
            session, None, "scene.create.cli", target_type="scene", target_id=scene.code,
            detail=fields,
        )
        print(f"已创建场景：{scene.name}（{scene.code}）")


def cmd_update_scene(args: argparse.Namespace) -> None:
    _prepare(args)
    updates: dict[str, str] = {}
    for item in args.set:
        if "=" not in item:
            raise SystemExit(f"--set 参数需要 key=value 格式：{item}")
        key, _, value = item.partition("=")
        updates[key.strip()] = value.strip()
    with session_scope() as session:
        scene = get_scene(session, args.code)
        if scene is None:
            raise SystemExit(f"场景不存在：{args.code}")
        try:
            update_scene(session, scene, updates)
        except BerryError as exc:
            raise SystemExit(str(exc)) from exc
        audit.record(
            session, None, "scene.update.cli", target_type="scene", target_id=scene.code,
            detail=updates,
        )
        print(f"已更新场景：{scene.name}（{scene.code}）")


def cmd_scene_bookable(args: argparse.Namespace) -> None:
    _prepare(args)
    with session_scope() as session:
        scene = get_scene(session, args.code)
        if scene is None:
            raise SystemExit(f"场景不存在：{args.code}")
        set_bookable(session, scene, args.enabled)
        audit.record(
            session, None, "scene.bookable.cli", target_type="scene", target_id=scene.code,
            detail={"enabled": args.enabled},
        )
        print(f"场景 {scene.name} 已{'开启' if args.enabled else '关闭'}预约")


def cmd_bookings(args: argparse.Namespace) -> None:
    _prepare(args)
    tz = get_settings().tz
    statuses = tuple(item for item in (args.status or "").split(",") if item) or None
    with session_scope() as session:
        if args.days:
            end = datetime.now(tz) + timedelta(days=1)
            start = end - timedelta(days=args.days)
            bookings = bookings_between(
                session,
                start,
                end,
                statuses=statuses
                or (
                    BookingStatus.PENDING,
                    BookingStatus.APPROVED,
                    BookingStatus.COMPLETED,
                    BookingStatus.REJECTED,
                    BookingStatus.CANCELLED,
                ),
                limit=args.limit,
            )
        else:
            bookings = recent_bookings(session, statuses=statuses, limit=args.limit)
        if args.csv:
            path = Path(args.csv).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    ["编号", "场景", "开始", "结束", "状态", "申请人", "QQ", "乐队", "人数", "预估金额"]
                )
                for booking in bookings:
                    view = booking_view(booking)
                    writer.writerow(
                        [
                            view.code,
                            view.scene_name,
                            view.start.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                            view.end.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                            view.status_label,
                            view.owner_name,
                            view.owner_qq,
                            view.band_name,
                            view.attendees,
                            view.price_estimate,
                        ]
                    )
            print(f"已导出 {len(bookings)} 条预约到 {path}")
            return
        if not bookings:
            print("没有匹配的预约")
            return
        for booking in bookings:
            view = booking_view(booking)
            print(
                f"{view.code} | {view.scene_name:8} | "
                f"{fmt_range(view.start, view.end, tz):28} | {view.status_label:4} | "
                f"{view.owner_name}（{view.owner_qq}）"
            )
        print(f"共 {len(bookings)} 条；待审核总数 {pending_count(session)}")


def cmd_approve(args: argparse.Namespace) -> None:
    _prepare(args)
    with session_scope() as session:
        booking = get_booking_by_code(session, args.code)
        admin = list_admins(session)[0] if list_admins(session) else None
        approve_booking(session, booking, admin, note=args.note)
        audit.record(
            session, admin, "booking.approve.cli", target_type="booking",
            target_id=booking.code, detail={"note": args.note},
        )
        view = booking_view(booking)
        print(f"已通过 {view.code}：{view.scene_name} {fmt_range(view.start, view.end, get_settings().tz)}")


def cmd_reject(args: argparse.Namespace) -> None:
    _prepare(args)
    with session_scope() as session:
        booking = get_booking_by_code(session, args.code)
        admin = list_admins(session)[0] if list_admins(session) else None
        reject_booking(session, booking, admin, reason=args.reason)
        audit.record(
            session, admin, "booking.reject.cli", target_type="booking",
            target_id=booking.code, detail={"reason": args.reason},
        )
        print(f"已驳回 {booking.code}：{args.reason}")


def cmd_cancel(args: argparse.Namespace) -> None:
    _prepare(args)
    with session_scope() as session:
        booking = get_booking_by_code(session, args.code)
        admin = list_admins(session)[0] if list_admins(session) else None
        cancel_booking(session, booking, admin, reason=args.reason, by_admin=True)
        audit.record(
            session, admin, "booking.cancel.cli", target_type="booking",
            target_id=booking.code, detail={"reason": args.reason},
        )
        print(f"已取消 {booking.code}")


def cmd_stats(args: argparse.Namespace) -> None:
    _prepare(args)
    tz = get_settings().tz
    today = datetime.now(tz).date()
    if args.days:
        end = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=tz)
        start = end - timedelta(days=args.days)
    else:
        first = today.replace(day=1)
        start = datetime.combine(first, datetime.min.time(), tzinfo=tz)
        if first.month == 12:
            next_month = first.replace(year=first.year + 1, month=1)
        else:
            next_month = first.replace(month=first.month + 1)
        end = datetime.combine(next_month, datetime.min.time(), tzinfo=tz)
    with session_scope() as session:
        stats = studio_stats(session, start, end)
        print(f"统计区间：{start:%Y-%m-%d} ~ {end:%Y-%m-%d}")
        print(
            f"预约 {stats.total_bookings}（通过 {stats.approved} / 待审 {stats.pending} / "
            f"驳回 {stats.rejected} / 取消 {stats.cancelled}）"
        )
        print(
            f"生效时长 {fmt_hours(stats.minutes)}，预估收入 ¥{stats.revenue}，"
            f"占用率 {stats.occupancy * 100:.1f}%"
        )
        for scene in stats.scene_stats:
            print(
                f"  - {scene.name}: {scene.bookings} 单 / {fmt_hours(scene.minutes)} / ¥{scene.revenue}"
            )
        if stats.top_bands:
            print("  活跃乐队：" + "、".join(f"{name}×{count}" for name, count in stats.top_bands))


def cmd_archive(args: argparse.Namespace) -> None:
    _prepare(args)
    with session_scope() as session:
        count = archive_past_bookings(session)
        audit.record(
            session, None, "booking.archive", target_type="booking",
            detail={"count": count},
        )
        print(f"已归档 {count} 条已结束的预约")


def cmd_user_info(args: argparse.Namespace) -> None:
    _prepare(args)
    from berrystudio.services.users import get_user
    from berrystudio.services.stats import user_stats
    from berrystudio.services.bands import user_bands

    with session_scope() as session:
        user = get_user(session, args.qq)
        if user is None:
            raise SystemExit(f"用户不存在：{args.qq}")
        stats = user_stats(session, user)
        print(f"QQ：{user.qq}")
        print(f"昵称：{user.name}（role={user.role}, status={user.status}）")
        print(f"乐队：{('、'.join(b.name for b in user_bands(session, user))) or '暂无'}")
        print(
            f"预约：总计 {stats.total_bookings} / 待审 {stats.pending_bookings} / "
            f"生效时长 {fmt_hours(stats.total_minutes)}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="berrystudio",
        description="BerryStudio 工作室预约系统服务器端管理工具",
    )
    parser.add_argument("--db", help="SQLite 文件路径（默认读取 BERRY_DB_PATH）")
    parser.add_argument("--verbose", action="store_true", help="输出数据库连接信息")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="初始化 / 升级数据库并写入默认场景").set_defaults(
        func=cmd_init_db
    )

    p = sub.add_parser("add-admin", help="添加管理员账号")
    p.add_argument("qq")
    p.add_argument("--name", default="")
    p.set_defaults(func=cmd_add_admin)

    p = sub.add_parser("remove-admin", help="移除管理员账号")
    p.add_argument("qq")
    p.set_defaults(func=cmd_remove_admin)

    sub.add_parser("list-admins", help="列出管理员").set_defaults(func=cmd_list_admins)

    p = sub.add_parser("list-users", help="列出用户")
    p.add_argument("--keyword", default="")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_list_users)

    p = sub.add_parser("user-info", help="查看单个用户")
    p.add_argument("qq")
    p.set_defaults(func=cmd_user_info)

    sub.add_parser("list-scenes", help="列出场景").set_defaults(func=cmd_list_scenes)

    p = sub.add_parser("add-scene", help="新增场景")
    p.add_argument("code")
    p.add_argument("name")
    p.add_argument("--kind", default="rehearsal", help="rehearsal/recording/performance/other")
    p.add_argument("--price", type=int, default=0, help="每小时价格")
    p.add_argument("--open-hour", type=int, default=9)
    p.add_argument("--close-hour", type=int, default=23)
    p.add_argument("--min-minutes", type=int, default=60)
    p.add_argument("--max-minutes", type=int, default=240)
    p.add_argument("--slot-minutes", type=int, default=30)
    p.add_argument("--capacity", type=int, default=6)
    p.add_argument("--color", default="#5EEAD4")
    p.add_argument("--description", default="")
    p.set_defaults(func=cmd_add_scene)

    p = sub.add_parser("update-scene", help="修改场景（key=value）")
    p.add_argument("code")
    p.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="例如 --set 价格=90 --set 开放=10-23",
    )
    p.set_defaults(func=cmd_update_scene)

    p = sub.add_parser("scene-bookable", help="开启 / 关闭场景预约")
    p.add_argument("code")
    p.add_argument("--enabled", action="store_true")
    p.add_argument("--disabled", dest="enabled", action="store_false")
    p.set_defaults(func=cmd_scene_bookable, enabled=True)

    p = sub.add_parser("bookings", help="查询 / 导出预约")
    p.add_argument("--status", default="", help="pending,approved,rejected,cancelled,completed")
    p.add_argument("--days", type=int, default=0, help="按天过滤，0 表示最近记录")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--csv", default="", help="导出 CSV 路径")
    p.set_defaults(func=cmd_bookings)

    p = sub.add_parser("approve", help="审核通过")
    p.add_argument("code")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("reject", help="驳回预约")
    p.add_argument("code")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_reject)

    p = sub.add_parser("cancel", help="管理员取消预约")
    p.add_argument("code")
    p.add_argument("--reason", default="")
    p.set_defaults(func=cmd_cancel)

    p = sub.add_parser("stats", help="运营统计")
    p.add_argument("--days", type=int, default=0, help="最近 N 天，0 表示本月")
    p.set_defaults(func=cmd_stats)

    sub.add_parser("archive", help="归档已结束的预约").set_defaults(func=cmd_archive)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except BerryError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
