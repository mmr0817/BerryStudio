from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from berrystudio.config import Settings
from berrystudio.db.session import session_scope
from berrystudio.services.bookings import create_booking
from berrystudio.services.users import get_or_create_user
from berrystudio.webadmin import build_router
from tests.conftest import load_scene, load_user


def _client(token: str = "test-token") -> TestClient:
    app = FastAPI()
    app.include_router(build_router(Settings(admin_api_token=token)))
    return TestClient(app)


def test_api_requires_token(db):
    client = _client()
    response = client.get("/admin/api/bookings")
    assert response.status_code == 401
    assert client.get("/admin/api/bookings", params={"token": "wrong"}).status_code == 401


def test_api_disabled_without_token(db):
    app = FastAPI()
    app.include_router(build_router(Settings(admin_api_token="")))
    response = TestClient(app).get("/admin/api/bookings")
    assert response.status_code == 503


def test_api_booking_review_flow(db, sample, tz):
    client = _client()
    headers = {"X-Admin-Token": "test-token"}
    with session_scope() as session:
        user = load_user(session, sample["user_id"])
        scene = load_scene(session, sample["scene_id"])
        booking = create_booking(session, user, scene, sample["start"], sample["end"])
        code = booking.code

    pending = client.get("/admin/api/bookings/pending", headers=headers)
    assert pending.status_code == 200
    assert any(item["code"] == code for item in pending.json())

    approved = client.post(
        f"/admin/api/bookings/{code}/approve",
        headers=headers,
        json={"note": "HTTP 后台审核"},
    )
    assert approved.status_code == 200
    payload = approved.json()
    assert payload["status"] == "approved"
    assert payload["review_note"] == "HTTP 后台审核"

    detail = client.get(f"/admin/api/bookings?status=approved", headers=headers)
    assert detail.status_code == 200
    assert any(item["code"] == code for item in detail.json())


def test_api_users_and_scenes(db):
    client = _client()
    headers = {"X-Admin-Token": "test-token"}
    with session_scope() as session:
        get_or_create_user(session, "10001", display_name="小明")

    users = client.get("/admin/api/users", headers=headers)
    assert users.status_code == 200
    assert users.json()[0]["qq"] == "10001"

    banned = client.post(
        "/admin/api/users/10001/status",
        headers=headers,
        json={"status": "banned"},
    )
    assert banned.status_code == 200
    assert banned.json()["status"] == "banned"

    scenes = client.get("/admin/api/scenes", headers=headers)
    assert scenes.status_code == 200
    assert {item["code"] for item in scenes.json()} >= {"REH-A", "REH-B", "REC-A", "LIVE"}

    created = client.post(
        "/admin/api/scenes",
        headers=headers,
        json={"code": "REH-X", "name": "排练室·X", "kind": "rehearsal", "hourly_price": 88},
    )
    assert created.status_code == 200
    assert created.json()["code"] == "REH-X"

    updated = client.patch(
        "/admin/api/scenes/REH-X",
        headers=headers,
        json={"hourly_price": 99, "is_bookable": False},
    )
    assert updated.status_code == 200
    assert updated.json()["hourly_price"] == 99
    assert updated.json()["is_bookable"] is False


def test_api_stats(db, sample):
    client = _client()
    headers = {"X-Admin-Token": "test-token"}
    with session_scope() as session:
        user = load_user(session, sample["user_id"])
        scene = load_scene(session, sample["scene_id"])
        create_booking(session, user, scene, sample["start"], sample["end"])

    response = client.get("/admin/api/stats?days=30", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total_bookings"] >= 1
    assert body["pending"] >= 1
    assert "scenes" in body
