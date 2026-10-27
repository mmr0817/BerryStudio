"""可预约场景服务（管理员可增改，数据库驱动）。"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from berrystudio.config import get_settings
from berrystudio.db.models import Scene, SceneKind
from berrystudio.services.dto import SceneView, scene_view
from berrystudio.services.errors import BerryError, NotFoundError

KIND_KEYWORDS: dict[str, str] = {
    "排练": SceneKind.REHEARSAL,
    "排练室": SceneKind.REHEARSAL,
    "band": SceneKind.REHEARSAL,
    "rehearsal": SceneKind.REHEARSAL,
    "录音": SceneKind.RECORDING,
    "录音棚": SceneKind.RECORDING,
    "录音室": SceneKind.RECORDING,
    "recording": SceneKind.RECORDING,
    "studio": SceneKind.RECORDING,
    "演出": SceneKind.PERFORMANCE,
    "演出厅": SceneKind.PERFORMANCE,
    "live": SceneKind.PERFORMANCE,
    "performance": SceneKind.PERFORMANCE,
    "其他": SceneKind.OTHER,
    "other": SceneKind.OTHER,
}

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_SEPARATORS_RE = re.compile(r"[\s·・.\-_/／]+")


def _normalize_key(text: str) -> str:
    """去掉空格与分隔符，方便“排练室C”匹配“排练室·C”。"""
    return _SEPARATORS_RE.sub("", (text or "").strip()).lower()


def list_scenes(session: Session, *, bookable_only: bool = True) -> list[Scene]:
    stmt = select(Scene).order_by(Scene.sort_order, Scene.id)
    if bookable_only:
        stmt = stmt.where(Scene.is_bookable.is_(True))
    return list(session.scalars(stmt))


def get_scene(session: Session, code_or_id: str | int) -> Scene | None:
    text = str(code_or_id).strip()
    if text.isdigit():
        scene = session.get(Scene, int(text))
        if scene is not None:
            return scene
    return session.scalar(select(Scene).where(Scene.code == text.upper()))


def resolve_scene(session: Session, keyword: str) -> Scene:
    """按代码 / 名称 / 类型关键字解析唯一场景。"""
    raw = (keyword or "").strip()
    if not raw:
        raise BerryError("请告诉我使用哪个场景，先用 /场景 查看列表", code="scene_required")

    scene = get_scene(session, raw)
    if scene is not None:
        if not scene.is_bookable:
            raise BerryError(f"「{scene.name}」当前暂停预约")
        return scene

    scenes = list_scenes(session, bookable_only=True)
    key = _normalize_key(raw)
    exact = [s for s in scenes if _normalize_key(s.name) == key]
    if len(exact) == 1:
        return exact[0]

    contains = [
        s
        for s in scenes
        if key and (key in _normalize_key(s.name) or key in _normalize_key(s.code))
    ]
    if len(contains) == 1:
        return contains[0]

    kind = KIND_KEYWORDS.get(raw.lower())
    if kind:
        candidates = [s for s in scenes if s.kind == kind]
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            names = "、".join(f"{s.name}({s.code})" for s in candidates)
            raise BerryError(f"「{raw}」对应多个场景：{names}，请指定具体名称或代码")

    if contains:
        names = "、".join(f"{s.name}({s.code})" for s in contains)
        raise BerryError(f"匹配到多个场景：{names}，请说得更具体一些")

    raise NotFoundError(f"没有找到场景「{raw}」，发送 /场景 查看全部场景")


def resolve_scene_optional(session: Session, keyword: str) -> Scene | None:
    if not (keyword or "").strip():
        return None
    return resolve_scene(session, keyword)


def _validate_scene_fields(fields: dict) -> None:
    for key in (
        "open_hour",
        "close_hour",
        "min_minutes",
        "max_minutes",
        "slot_minutes",
        "hourly_price",
        "capacity",
        "sort_order",
    ):
        if key in fields and fields[key] not in (None, ""):
            try:
                fields[key] = int(fields[key])
            except (TypeError, ValueError) as exc:
                raise BerryError("时间 / 价格 / 容量等字段需要填写数字") from exc

    if "code" in fields:
        code = str(fields["code"]).strip().upper()
        if not re.match(r"^[A-Z0-9][A-Z0-9_-]{1,15}$", code):
            raise BerryError("场景代码只能是 2-16 位大写字母 / 数字 / - _")
        fields["code"] = code
    if "name" in fields:
        name = str(fields["name"]).strip()
        if not 1 <= len(name) <= 24:
            raise BerryError("场景名称长度需在 1-24 之间")
        fields["name"] = name
    if "kind" in fields:
        kind = str(fields["kind"]).strip()
        kind = KIND_KEYWORDS.get(kind.lower(), kind)
        if kind not in SceneKind.LABELS:
            raise BerryError("场景类型只能是：排练 / 录音 / 演出 / 其他")
        fields["kind"] = kind
    if "color" in fields:
        color = str(fields["color"]).strip()
        if not _COLOR_RE.match(color):
            raise BerryError("颜色格式需为 #RRGGBB，例如 #5EEAD4")
        fields["color"] = color.upper()

    open_hour = int(fields.get("open_hour", 0) or 0)
    close_hour = int(fields.get("close_hour", 0) or 0)
    if "open_hour" in fields or "close_hour" in fields:
        if not 0 <= open_hour <= 23 or not 1 <= close_hour <= 24:
            raise BerryError("开放时间需在 0-24 点之间")
        if close_hour <= open_hour:
            raise BerryError("打烊时间必须晚于开放时间")

    if "min_minutes" in fields or "max_minutes" in fields:
        min_minutes = int(fields.get("min_minutes", 30) or 30)
        max_minutes = int(fields.get("max_minutes", 240) or 240)
        if min_minutes < 30:
            raise BerryError("最短预约时长不能少于 30 分钟")
        if max_minutes < min_minutes:
            raise BerryError("最长预约时长必须大于最短时长")

    if "slot_minutes" in fields:
        slot = int(fields["slot_minutes"] or 0)
        if slot < 15 or slot > 180 or 60 % slot != 0:
            raise BerryError("时间粒度建议为 15/20/30/60 分钟")

    for key in ("hourly_price", "capacity"):
        if key in fields:
            value = int(fields[key] or 0)
            if value < 0:
                raise BerryError("价格和容量不能为负数")
            fields[key] = value


def create_scene(session: Session, **fields) -> Scene:
    for required, label in (("code", "场景代码"), ("name", "场景名称")):
        if not str(fields.get(required) or "").strip():
            raise BerryError(f"请填写{label}")
    fields.setdefault("slot_minutes", get_settings().slot_minutes)
    _validate_scene_fields(fields)
    code = fields.get("code", "")
    if get_scene(session, code) is not None:
        raise BerryError(f"场景代码 {code} 已存在")
    if session.scalar(select(Scene).where(Scene.name == fields.get("name", ""))):
        raise BerryError(f"场景名称 {fields['name']} 已存在")
    scene = Scene(**fields)
    session.add(scene)
    session.flush()
    return scene


EDITABLE_FIELDS = {
    "code": "code",
    "代码": "code",
    "name": "name",
    "名称": "name",
    "kind": "kind",
    "类型": "kind",
    "price": "hourly_price",
    "价格": "hourly_price",
    "时价": "hourly_price",
    "hourly_price": "hourly_price",
    "capacity": "capacity",
    "容量": "capacity",
    "open": "open_hour",
    "开放": "open_hour",
    "开放时间": "open_hour",
    "slot": "slot_minutes",
    "粒度": "slot_minutes",
    "量化": "slot_minutes",
    "min": "min_minutes",
    "最短": "min_minutes",
    "max": "max_minutes",
    "最长": "max_minutes",
    "color": "color",
    "颜色": "color",
    "描述": "description",
    "description": "description",
    "排序": "sort_order",
    "sort": "sort_order",
    # 直接使用数据库字段名也允许（HTTP 后台 / 内部调用）
    "open_hour": "open_hour",
    "close_hour": "close_hour",
    "min_minutes": "min_minutes",
    "max_minutes": "max_minutes",
    "slot_minutes": "slot_minutes",
    "sort_order": "sort_order",
}


def update_scene(session: Session, scene: Scene, updates: dict) -> Scene:
    fields: dict = {}
    for key, value in updates.items():
        field_name = EDITABLE_FIELDS.get(str(key).strip())
        if field_name is None:
            raise BerryError(
                f"不认识的字段「{key}」，可用字段：名称/类型/价格/容量/开放/粒度/最短/最长/颜色/描述"
            )
        if field_name in {"open_hour"} and isinstance(value, str) and "-" in value:
            start, _, end = value.partition("-")
            fields["open_hour"] = int(start)
            fields["close_hour"] = int(end)
            continue
        fields[field_name] = value
    if not fields:
        raise BerryError("没有需要更新的字段")
    merged = {
        field: getattr(scene, field)
        for field in (
            "code",
            "name",
            "kind",
            "open_hour",
            "close_hour",
            "min_minutes",
            "max_minutes",
            "slot_minutes",
            "hourly_price",
            "capacity",
            "color",
            "sort_order",
        )
    }
    merged.update(fields)
    _validate_scene_fields(merged)

    new_code = merged["code"]
    if new_code != scene.code:
        if get_scene(session, new_code) is not None:
            raise BerryError(f"场景代码 {new_code} 已被占用")
    new_name = merged["name"]
    if new_name != scene.name:
        if session.scalar(select(Scene).where(Scene.name == new_name)):
            raise BerryError(f"场景名称 {new_name} 已被占用")

    for key in fields:
        setattr(scene, key, merged[key])
    session.flush()
    return scene


def set_bookable(session: Session, scene: Scene, enabled: bool) -> Scene:
    scene.is_bookable = enabled
    session.flush()
    return scene


def scene_views(scenes: list[Scene]) -> list[SceneView]:
    return [scene_view(scene) for scene in scenes]
