from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from berrystudio.db.models import Scene
from berrystudio.db.session import session_scope
from berrystudio.services.bookings import approve_booking, create_booking
from berrystudio.services.errors import BerryError, NotFoundError
from berrystudio.services.scenes import (
    create_scene,
    get_scene,
    list_scenes,
    resolve_scene,
    set_bookable,
    update_scene,
)
from berrystudio.services.stats import studio_stats, user_stats
from berrystudio.services.users import get_or_create_user
from tests.conftest import load_band, load_scene, load_user


def test_create_and_edit_scene(db):
    with session_scope() as session:
        scene = create_scene(
            session,
            code="reh-c",
            name="排练室·C",
            kind="排练",
            hourly_price="70",
            open_hour="10",
            close_hour="22",
            min_minutes="60",
            max_minutes="180",
            slot_minutes="30",
            capacity="4",
            color="#5eead4",
        )
        assert scene.code == "REH-C"
        assert scene.hourly_price == 70
        assert scene.color == "#5EEAD4"
        assert resolve_scene(session, "排练室C").id == scene.id

        update_scene(session, scene, {"价格": "95", "开放": "9-23", "最长": "240"})
        assert scene.hourly_price == 95
        assert (scene.open_hour, scene.close_hour) == (9, 23)
        assert scene.max_minutes == 240

        with pytest.raises(BerryError):
            create_scene(session, code="REH-D", name="排练室·C", kind="排练")

        set_bookable(session, scene, False)
        with pytest.raises(BerryError):
            resolve_scene(session, "REH-C")


def test_stats(db, sample, tz):
    with session_scope() as session:
        user = load_user(session, sample["user_id"])
        scene = load_scene(session, sample["scene_id"])
        band = load_band(session, sample["band_id"])
        booking = create_booking(
            session, user, scene, sample["start"], sample["end"], band=band
        )
        admin = get_or_create_user(session, "90001", display_name="店长")
        approve_booking(session, booking, admin)

        stats = user_stats(session, user, now=sample["start"] - timedelta(hours=1))
        assert stats.total_bookings == 1
        assert stats.approved_bookings == 1
        assert stats.total_minutes == 120
        assert stats.upcoming

        start = sample["start"] - timedelta(days=1)
        end = sample["start"] + timedelta(days=1)
        studio = studio_stats(session, start, end)
        assert studio.total_bookings == 1
        assert studio.approved == 1
        assert studio.minutes == 120
        assert studio.revenue == 160
        assert studio.occupancy > 0
        assert studio.top_bands == [("草莓汽水", 1)]
