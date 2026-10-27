"""应用配置。

所有业务配置都通过环境变量（``.env`` / 系统环境变量）读取，
这样同一份代码可以部署到不同服务器而无需改动源码。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    raw = _env(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on", "是"}


def _parse_qq_list(raw: str) -> tuple[str, ...]:
    """支持 ``["123", "456"]``、``123,456``、``123 456`` 三种写法。"""
    raw = (raw or "").strip()
    if not raw:
        return ()
    if raw.startswith("["):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = []
        return tuple(str(int(item)) for item in data if str(item).strip().isdigit())
    parts = [p.strip() for p in raw.replace(" ", ",").split(",")]
    return tuple(p for p in parts if p.isdigit())


def _load_env_file() -> None:
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)


@dataclass(frozen=True)
class Settings:
    """业务侧配置快照（NoneBot 自身配置仍由 NoneBot 读取 .env）。"""

    base_dir: Path = BASE_DIR
    db_path: Path = BASE_DIR / "data" / "berrystudio.db"
    timezone_name: str = "Asia/Shanghai"
    admin_qqs: tuple[str, ...] = ()
    admin_api_token: str = ""
    font_path: str = ""
    image_dir: Path = BASE_DIR / "data" / "images"
    slot_minutes: int = 30
    min_lead_minutes: int = 30
    max_advance_days: int = 60
    default_duration_minutes: int = 120
    max_pending_per_user: int = 3
    notify_fallback_group: bool = True
    extra: dict[str, str] = field(default_factory=dict)

    # ---- 派生属性 -------------------------------------------------
    @property
    def db_url(self) -> str:
        return f"sqlite+pysqlite:///{self.db_path}"

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone_name)
        except Exception:  # pragma: no cover - 极端情况下时区数据缺失
            return ZoneInfo("UTC")


def _build_settings() -> Settings:
    _load_env_file()

    db_path = Path(_env("BERRY_DB_PATH", "data/berrystudio.db"))
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    image_dir = Path(_env("BERRY_IMAGE_DIR", "data/images"))
    if not image_dir.is_absolute():
        image_dir = BASE_DIR / image_dir

    admin_qqs: list[str] = list(_parse_qq_list(_env("BERRY_ADMIN_QQ")))
    for qq in _parse_qq_list(_env("SUPERUSERS")):
        if qq not in admin_qqs:
            admin_qqs.append(qq)

    return Settings(
        base_dir=BASE_DIR,
        db_path=db_path,
        timezone_name=_env("BERRY_TIMEZONE", "Asia/Shanghai"),
        admin_qqs=tuple(admin_qqs),
        admin_api_token=_env("BERRY_ADMIN_API_TOKEN", "").strip(),
        font_path=_env("BERRY_FONT_PATH", "").strip(),
        image_dir=image_dir,
        slot_minutes=max(5, _env_int("BERRY_SLOT_MINUTES", 30)),
        min_lead_minutes=max(0, _env_int("BERRY_MIN_LEAD_MINUTES", 30)),
        max_advance_days=max(1, _env_int("BERRY_MAX_ADVANCE_DAYS", 60)),
        default_duration_minutes=max(30, _env_int("BERRY_DEFAULT_DURATION_MINUTES", 120)),
        max_pending_per_user=max(1, _env_int("BERRY_MAX_PENDING_PER_USER", 3)),
        notify_fallback_group=_env_bool("BERRY_NOTIFY_FALLBACK_GROUP", True),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _build_settings()


def reload_settings() -> Settings:
    """清空缓存并重新读取配置（测试或热更新配置时使用）。"""
    get_settings.cache_clear()
    return get_settings()
