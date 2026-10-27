"""乐队服务。"""

from __future__ import annotations

import secrets
import string

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from berrystudio.db.models import Band, BandMember, User
from berrystudio.services.dto import BandView, band_view
from berrystudio.services.errors import BerryError, NotFoundError
from berrystudio.services.users import ensure_active

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _generate_invite_code(session: Session) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if session.scalar(select(Band.id).where(Band.invite_code == code)) is None:
            return code
    raise BerryError("生成邀请码失败，请稍后再试")


def create_band(
    session: Session,
    leader: User,
    name: str,
    *,
    style: str = "",
    description: str = "",
) -> Band:
    ensure_active(leader)
    name = (name or "").strip()
    if not 1 <= len(name) <= 24:
        raise BerryError("乐队名称长度需在 1-24 个字符之间")
    if session.scalar(select(Band).where(Band.name == name)) is not None:
        raise BerryError(f"乐队「{name}」已经存在了")

    band = Band(
        name=name,
        style=(style or "").strip()[:32],
        description=(description or "").strip()[:120],
        leader_id=leader.id,
        invite_code=_generate_invite_code(session),
    )
    session.add(band)
    session.flush()
    session.add(
        BandMember(band_id=band.id, user_id=leader.id, role="leader", instrument="")
    )
    session.flush()
    session.refresh(band)
    return band


def get_band(session: Session, band_id: int) -> Band | None:
    return session.get(Band, band_id)


def resolve_band(session: Session, keyword: str) -> Band:
    raw = (keyword or "").strip().lstrip("#")
    if not raw:
        raise BerryError("请提供乐队名称、编号或邀请码")
    if raw.isdigit():
        band = session.get(Band, int(raw))
        if band is not None:
            return band
    band = session.scalar(select(Band).where(Band.name == raw))
    if band is not None:
        return band
    band = session.scalar(select(Band).where(Band.invite_code == raw.upper()))
    if band is not None:
        return band
    matches = list(
        session.scalars(select(Band).where(Band.name.like(f"%{raw}%")).limit(5))
    )
    if len(matches) == 1:
        return matches[0]
    if matches:
        names = "、".join(b.name for b in matches)
        raise BerryError(f"匹配到多个乐队：{names}，请输入完整名称")
    raise NotFoundError(f"没有找到乐队「{raw}」")


def user_bands(session: Session, user: User) -> list[Band]:
    stmt = (
        select(Band)
        .join(BandMember, BandMember.band_id == Band.id)
        .where(BandMember.user_id == user.id)
        .order_by(Band.created_at)
    )
    return list(session.scalars(stmt))


def user_band_membership(session: Session, band: Band, user: User) -> BandMember | None:
    return session.scalar(
        select(BandMember).where(
            BandMember.band_id == band.id, BandMember.user_id == user.id
        )
    )


def band_members(session: Session, band: Band) -> list[BandMember]:
    members = list(
        session.scalars(
            select(BandMember)
            .where(BandMember.band_id == band.id)
            .order_by(BandMember.joined_at)
        )
    )
    members.sort(key=lambda m: (m.role != "leader", m.joined_at))
    return members


def join_band(
    session: Session,
    band: Band,
    user: User,
    *,
    instrument: str = "",
) -> BandMember:
    ensure_active(user)
    if band.status != "active":
        raise BerryError("该乐队已解散，无法加入")
    if user_band_membership(session, band, user) is not None:
        raise BerryError(f"你已经在「{band.name}」里了")
    member = BandMember(
        band_id=band.id,
        user_id=user.id,
        role="member",
        instrument=(instrument or "").strip()[:24],
    )
    session.add(member)
    session.flush()
    return member


def leave_band(session: Session, band: Band, user: User) -> str:
    member = user_band_membership(session, band, user)
    if member is None:
        raise BerryError(f"你不在「{band.name}」里")

    members = band_members(session, band)
    if member.role == "leader" and len(members) > 1:
        successor = next((m for m in members if m.user_id != user.id), None)
        if successor is not None:
            successor.role = "leader"
            band.leader_id = successor.user_id
            session.delete(member)
            session.flush()
            return f"已退出「{band.name}」，队长已转交给 {successor.user.name}"

    session.delete(member)
    session.flush()
    remaining = session.scalar(
        select(func.count(BandMember.id)).where(BandMember.band_id == band.id)
    )
    if not remaining:
        band.status = "archived"
        session.flush()
        return f"已退出「{band.name}」，乐队没有其他成员，已自动解散"
    return f"已退出「{band.name}」"


def update_band(
    session: Session,
    band: Band,
    *,
    style: str | None = None,
    description: str | None = None,
) -> Band:
    if style is not None:
        band.style = style.strip()[:32]
    if description is not None:
        band.description = description.strip()[:120]
    session.flush()
    return band


def band_views(session: Session, bands: list[Band]) -> list[BandView]:
    counts = dict(
        session.execute(
            select(BandMember.band_id, func.count(BandMember.id))
            .where(BandMember.band_id.in_([b.id for b in bands] or [0]))
            .group_by(BandMember.band_id)
        ).all()
    )
    return [band_view(band, member_count=int(counts.get(band.id, 0))) for band in bands]
