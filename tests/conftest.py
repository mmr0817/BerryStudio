from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from berrystudio.config import get_settings
from berrystudio.db.migrate import run_migrations
from berrystudio.db.models import Band, Scene, User
from berrystudio.db.seed import seed_default_scenes
from berrystudio.db.session import configure, session_scope
from berrystudio.services.bands import create_band
from berrystudio.services.users import get_or_create_user


@pytest.fixture()
def db(tmp_path):
    engine = configure(f"sqlite+pysqlite:///{tmp_path / 'berrystudio-test.db'}")
    run_migrations(engine)
    with session_scope() as session:
        seed_default_scenes(session)
    yield engine


@pytest.fixture()
def tz():
    return get_settings().tz


@pytest.fixture()
def tomorrow(tz) -> date:
    return (datetime.now(tz) + timedelta(days=1)).date()


@pytest.fixture()
def sample(db):
    """创建一位普通用户、一支乐队和明天的 19:00-21:00 时段。"""
    tz = get_settings().tz
    day = (datetime.now(tz) + timedelta(days=2)).date()
    with session_scope() as session:
        user = get_or_create_user(session, "10001", display_name="小明")
        band = create_band(session, user, "草莓汽水", style="独立摇滚")
        scene = session.scalar(select(Scene).where(Scene.code == "REH-A"))
        assert scene is not None
        return {
            "user_id": user.id,
            "band_id": band.id,
            "scene_id": scene.id,
            "day": day,
            "start": datetime.combine(day, time(19, 0), tzinfo=tz),
            "end": datetime.combine(day, time(21, 0), tzinfo=tz),
        }


def load_user(session, user_id: int) -> User:
    user = session.get(User, user_id)
    assert user is not None
    return user


def load_band(session, band_id: int) -> Band:
    band = session.get(Band, band_id)
    assert band is not None
    return band


def load_scene(session, scene_id: int) -> Scene:
    scene = session.get(Scene, scene_id)
    assert scene is not None
    return scene
