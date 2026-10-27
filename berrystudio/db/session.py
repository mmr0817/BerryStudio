"""数据库引擎与会话管理。"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from berrystudio.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_write_lock = threading.RLock()


def _sqlite_pragmas(dbapi_conn, _record) -> None:  # pragma: no cover - 依赖驱动
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=15000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def configure(url: str | None = None, *, echo: bool = False) -> Engine:
    """（重新）建立引擎；测试用内存/临时数据库时会调用它。"""
    global _engine, _session_factory

    settings = get_settings()
    db_url = url or settings.db_url
    if db_url.startswith("sqlite"):
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        db_url,
        echo=echo,
        future=True,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    if db_url.startswith("sqlite"):
        event.listen(engine, "connect", _sqlite_pragmas)

    with _write_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = engine
        _session_factory = sessionmaker(
            bind=engine, expire_on_commit=False, autoflush=False
        )
    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        configure()
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        configure()
    assert _session_factory is not None
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务上下文：正常提交，异常回滚。"""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_database(url: str | None = None) -> list[int]:
    """初始化数据库：建表 / 迁移 / 写入默认场景与管理员。"""
    from berrystudio.db.migrate import run_migrations
    from berrystudio.db.seed import ensure_default_data

    engine = configure(url)
    applied = run_migrations(engine)
    ensure_default_data()
    return applied


@contextmanager
def write_lock() -> Iterator[None]:
    """串行化“检查冲突 + 写入”的临界区，避免并发重复预约。"""
    with _write_lock:
        yield
