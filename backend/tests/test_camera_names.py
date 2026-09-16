"""App display names survive both provider syncs and can return to imported defaults."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.routes_cameras import router
from app.core.db import get_db
from app.core.security import create_access_token
from app.ingestion.spypoint import SpypointCamera
from app.ingestion.sync import upsert_camera as upsert_spypoint
from app.ingestion.ubox import UboxDevice
from app.ingestion.ubox_sync import upsert_camera as upsert_ubox
from app.models import Camera, Estate, Image, User

from .conftest import requires_db

pytestmark = requires_db


@pytest.fixture
def naming_app(db_session):
    estate = Estate(name="Naming test", timezone="Europe/Amsterdam")
    db_session.add(estate)
    db_session.flush()
    users = {}
    for role in ("admin", "member", "viewer"):
        user = User(estate_id=estate.id, email=f"{role}@example.test",
                    password_hash="test", role=role)
        db_session.add(user)
        users[role] = user
    db_session.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as client:
        yield client, users, estate


def _headers(user):
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def _import(db, estate, provider, name):
    if provider == "ubox":
        return upsert_ubox(db, estate.id, UboxDevice(uid="test-ubox", name=name))
    return upsert_spypoint(db, estate.id, SpypointCamera(spypoint_id="test-spypoint", name=name))


@pytest.mark.parametrize("provider,role", [("ubox", "admin"), ("spypoint", "member")])
def test_rename_survives_sync_and_reset_uses_latest_imported_name(
    db_session, naming_app, provider, role,
):
    client, users, estate = naming_app
    camera = _import(db_session, estate, provider, "Imported camera")
    photo = Image(camera_id=camera.id, captured_at=datetime.now(UTC), original_path="photo.jpg")
    db_session.add(photo)
    db_session.commit()
    camera_id, image_id = camera.id, photo.id
    url = f"/api/cameras/{camera_id}/name"
    headers = _headers(users[role])
    assert client.get("/api/cameras", headers=headers).json()[0]["provider_name"] == "Imported camera"
    response = client.patch(url, json={"name": "  North meadow 🦌  "}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {
        "id": str(camera_id), "name": "North meadow 🦌", "provider_name": "Imported camera",
        "name_is_custom": True, "can_rename": True,
    }

    _import(db_session, estate, provider, "Provider changed its name")
    db_session.commit()
    displayed = client.get("/api/cameras", headers=headers).json()[0]
    assert displayed["name"] == "North meadow 🦌"
    assert displayed["provider_name"] == "Provider changed its name"
    assert displayed["name_is_custom"] and displayed["can_rename"]
    assert displayed["image_count"] == 1
    assert db_session.get(Image, image_id).camera_id == camera_id

    response = client.patch(url, json={"name": None}, headers=headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Provider changed its name"
    assert not response.json()["name_is_custom"]
    _import(db_session, estate, provider, "Next provider name")
    db_session.commit()
    assert client.get("/api/cameras", headers=headers).json()[0]["name"] == "Next provider name"
    assert len(db_session.scalars(select(Camera)).all()) == 1


def test_viewer_cannot_rename_and_members_cannot_rename_other_estate(db_session, naming_app):
    client, users, estate = naming_app
    local = _import(db_session, estate, "ubox", "Own estate")
    other_estate = Estate(name="Other estate", timezone="UTC")
    db_session.add(other_estate)
    db_session.flush()
    other = Camera(estate_id=other_estate.id, name="Private camera")
    db_session.add(other)
    db_session.commit()
    local_id, other_id = local.id, other.id
    viewer_headers = _headers(users["viewer"])
    listed = client.get("/api/cameras", headers=viewer_headers).json()
    assert len(listed) == 1 and not listed[0]["can_rename"]
    assert client.patch(f"/api/cameras/{local_id}/name", json={"name": "No"},
                        headers=viewer_headers).status_code == 403
    for target in (other_id, uuid.uuid4()):
        assert client.patch(f"/api/cameras/{target}/name", json={"name": "No"},
                            headers=_headers(users["member"])).status_code == 404
    assert client.patch(f"/api/cameras/{local_id}/name", json={"name": "No"}).status_code in (401, 403)
    db_session.expire_all()
    assert db_session.get(Camera, local_id).name == "Own estate"
    assert db_session.get(Camera, other_id).name == "Private camera"


@pytest.mark.parametrize("body", [
    {}, {"name": ""}, {"name": "   "}, {"name": "x" * 101}, {"name": "Bad\nname"},
    {"name": "Bad\x00name"}, {"name": "Bad\u202ename"}, {"name": 123},
])
def test_invalid_names_return_422_without_mutating_camera(db_session, naming_app, body):
    client, users, estate = naming_app
    camera = _import(db_session, estate, "ubox", "Original")
    db_session.commit()
    response = client.patch(f"/api/cameras/{camera.id}/name", json=body,
                            headers=_headers(users["admin"]))
    assert response.status_code == 422
    db_session.refresh(camera)
    assert camera.name == camera.provider_name == "Original"
    assert not camera.name_is_custom


def test_local_camera_keeps_initial_default_and_accepts_100_characters(db_session, naming_app):
    client, users, estate = naming_app
    camera = Camera(estate_id=estate.id, name="FTP camera")
    db_session.add(camera)
    db_session.commit()
    url = f"/api/cameras/{camera.id}/name"
    headers = _headers(users["member"])
    response = client.patch(url, json={"name": "x" * 100}, headers=headers)
    assert response.status_code == 200
    assert response.json()["provider_name"] == "FTP camera"
    assert client.patch(url, json={"name": None}, headers=headers).json()["name"] == "FTP camera"


@pytest.mark.parametrize("provider", ["ubox", "spypoint"])
def test_sync_refreshes_stale_camera_after_another_session_renames_it(
    db_session, naming_app, provider,
):
    _, _, estate = naming_app
    camera = _import(db_session, estate, provider, "Original")
    db_session.commit()
    camera_id = camera.id
    assert camera.name == "Original"  # Populate the sync session's identity map.
    with Session(db_session.bind) as other:
        other.execute(update(Camera).where(Camera.id == camera_id).values(
            name="Saved concurrently", name_is_custom=True,
        ))
        other.commit()
    synced = _import(db_session, estate, provider, "Latest provider label")
    db_session.commit()
    assert synced.name == "Saved concurrently"
    assert synced.provider_name == "Latest provider label"
    assert synced.name_is_custom
