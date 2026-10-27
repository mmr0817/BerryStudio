"""轻量数据库迁移。

新增表结构时：

1. 在 ``models.py`` 中修改模型；
2. 在 ``MIGRATIONS`` 末尾追加一个新版本；
3. 重启服务或运行 ``python -m berrystudio.cli init-db`` 即可自动应用。

这样既可以用 ``Base.metadata.create_all`` 初始化全新数据库，
也能对已有服务器数据做增量升级，不需要引入额外迁移框架。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import Connection, Engine, inspect, text

from berrystudio.db.models import Base


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    apply: Callable[[Connection], None]


def _create_all(conn: Connection) -> None:
    Base.metadata.create_all(bind=conn)


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "初始化基础表结构", _create_all),
)


def run_migrations(engine: Engine) -> list[int]:
    """按顺序应用未执行的迁移，返回本次应用的版本号列表。"""
    applied: list[int] = []
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")

    with engine.begin() as conn:
        # 迁移记录表不依赖 ORM 元数据，保证全新库也能先建立版本信息
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    description VARCHAR(255) NOT NULL DEFAULT '',
                    applied_at DATETIME NOT NULL
                )
                """
            )
        )
        current = conn.execute(
            text("SELECT COALESCE(MAX(version), 0) FROM schema_version")
        ).scalar_one()

        for migration in MIGRATIONS:
            if migration.version <= int(current or 0):
                continue
            migration.apply(conn)
            conn.execute(
                text(
                    "INSERT INTO schema_version (version, description, applied_at) "
                    "VALUES (:version, :description, :applied_at)"
                ),
                {
                    "version": migration.version,
                    "description": migration.description,
                    "applied_at": now,
                },
            )
            applied.append(migration.version)

    return applied


def schema_version(engine: Engine) -> int:
    """返回当前数据库版本，未初始化时返回 0。"""
    if "schema_version" not in inspect(engine).get_table_names():
        return 0
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT COALESCE(MAX(version), 0) FROM schema_version")
            ).scalar_one()
            or 0
        )
