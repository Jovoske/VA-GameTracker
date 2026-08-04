"""Stands, claims and sit outcomes.

The stand — not the camera — is the thing a hunter sits in. Cameras are placed
where animals go; stands exist where a bullet can safely stop, and the app was
previously labelling a list of cameras "OTHER STANDS" in the UI, which is the one
place that conflation can get somebody hurt.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.forecasting.inference import dark_exit, suggest_approach_arcs
from app.forecasting.wind import assess, shooting_arcs_conflict
from app.models import Camera, Estate, Sit, Stand, User

router = APIRouter(tags=["stands"])

OUTCOMES = ("unreported", "nothing", "seen", "shootable_no_shot", "shot", "cancelled")


def tonight(now: datetime | None = None) -> date:
    """The night now belongs to — before 06:00 still counts as last evening."""
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(__import__("zoneinfo").ZoneInfo(settings.estate_timezone))
    return (local - timedelta(hours=6)).date()


class StandIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    camera_id: uuid.UUID | None = None
    lat: float | None = None
    lon: float | None = None
    shooting_dirs_deg: list[int] | None = None
    approach_dirs_deg: list[int] | None = None
    notes: str | None = None


class StandPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    camera_id: uuid.UUID | None = None
    lat: float | None = None
    lon: float | None = None
    shooting_dirs_deg: list[int] | None = None
    approach_dirs_deg: list[int] | None = None
    notes: str | None = None


def _stand_out(s: Stand, claim: Sit | None = None) -> dict:
    return {
        "id": str(s.id),
        "name": s.name,
        "camera_id": str(s.camera_id) if s.camera_id else None,
        "lat": s.lat,
        "lon": s.lon,
        "shooting_dirs_deg": s.shooting_dirs_deg,
        "approach_dirs_deg": s.approach_dirs_deg,
        "notes": s.notes,
        "has_geometry": bool(s.approach_dirs_deg),
        "claimed_tonight": bool(claim),
        "claimed_by": str(claim.user_id) if claim and claim.user_id else None,
    }


@router.get("/stands")
def list_stands(
    _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict]:
    claims = {
        c.stand_id: c
        for c in db.scalars(
            select(Sit).where(Sit.night == tonight(), Sit.outcome != "cancelled")
        ).all()
    }
    rows = db.scalars(select(Stand).order_by(Stand.name)).all()
    return [_stand_out(s, claims.get(s.id)) for s in rows]


@router.post("/stands/bootstrap")
def bootstrap_stands(
    _: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> dict:
    """Create a stand for every camera that has none, at the camera's position.

    Until a stand exists, the Stands tab is empty and Sit Mode has nothing to open,
    so the estate has to be typed in by hand before any of it works. A camera is not
    a stand — the camera watches the ground, the hunter sits somewhere near it — so
    these are a starting point to be dragged and renamed, not an answer.

    Approach arcs are left NULL deliberately. A guessed arc becomes confident wind
    advice, which is the exact failure the wind module exists to refuse; the app
    stays silent on wind until somebody sets them or the inference has enough
    sequences to suggest one.

    Idempotent: cameras that already have a stand are skipped.
    """
    estate = db.scalar(select(Estate).order_by(Estate.created_at))
    if estate is None:
        raise HTTPException(400, "No estate configured yet")

    taken = {s.camera_id for s in db.scalars(select(Stand)).all() if s.camera_id}
    created = []
    for cam in db.scalars(select(Camera).order_by(Camera.name)).all():
        if cam.id in taken:
            continue
        stand = Stand(
            estate_id=estate.id, camera_id=cam.id, name=f"{cam.name} stand",
            lat=cam.lat, lon=cam.lon,
        )
        db.add(stand)
        created.append(stand)
    db.commit()
    return {
        "created": [s.name for s in created],
        "skipped": len(taken),
        "note": (
            "Positions copied from the cameras — drag each stand to where you "
            "actually sit. Approach arcs are unset, so wind advice stays quiet "
            "until you set them."
        ),
    }


@router.post("/stands", status_code=201)
def create_stand(
    body: StandIn, _: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> dict:
    estate = db.scalar(select(Estate).order_by(Estate.created_at))
    if estate is None:
        raise HTTPException(400, "No estate configured yet")
    if body.camera_id and db.get(Camera, body.camera_id) is None:
        raise HTTPException(404, "Camera not found")
    stand = Stand(estate_id=estate.id, **body.model_dump())
    db.add(stand)
    db.commit()
    return _stand_out(stand)


@router.patch("/stands/{stand_id}")
def update_stand(
    stand_id: uuid.UUID,
    body: StandPatch,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    stand = db.get(Stand, stand_id)
    if stand is None:
        raise HTTPException(404, "Stand not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(stand, k, v)
    db.commit()
    return _stand_out(stand)


@router.delete("/stands/{stand_id}", status_code=204, response_model=None)
def delete_stand(
    stand_id: uuid.UUID, _: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> None:
    stand = db.get(Stand, stand_id)
    if stand is None:
        raise HTTPException(404, "Stand not found")
    sits = db.scalar(select(func.count(Sit.id)).where(Sit.stand_id == stand_id))
    if sits:
        raise HTTPException(
            409,
            f"{sits} recorded sit(s) reference this stand. Deleting would erase that "
            "history — rename it instead.",
        )
    db.delete(stand)
    db.commit()


# ── claims ──────────────────────────────────────────────────────────────────


class ClaimIn(BaseModel):
    stand_id: uuid.UUID


class OutcomeIn(BaseModel):
    outcome: str
    species_seen: str | None = None
    notes: str | None = None


def _sit_out(s: Sit, stand_name: str | None = None) -> dict:
    return {
        "id": str(s.id),
        "stand_id": str(s.stand_id),
        "stand": stand_name,
        "night": s.night.isoformat(),
        "user_id": str(s.user_id) if s.user_id else None,
        "claimed_at": s.claimed_at,
        "started_at": s.started_at,
        "ended_at": s.ended_at,
        "outcome": s.outcome,
        "species_seen": s.species_seen,
        "wind_status": s.wind_status,
        "wind_text": s.wind_text,
    }


@router.get("/sits")
def list_sits(
    night: date | None = None,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    target = night or tonight()
    rows = db.execute(
        select(Sit, Stand.name).join(Stand, Stand.id == Sit.stand_id).where(Sit.night == target)
    ).all()
    return [_sit_out(s, name) for s, name in rows]


@router.post("/sits", status_code=201)
def claim_stand(
    body: ClaimIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """Claim a stand for tonight.

    This is the app's data-capture mechanism, and it works because claiming has a
    payoff for the person doing it: the wind verdict and the answer to "is anyone
    else on that ridge". The row is written before the sit, when the phone is out
    and hands are clean — not at 23:40 in the dark after a blank evening.
    """
    stand = db.get(Stand, body.stand_id)
    if stand is None:
        raise HTTPException(404, "Stand not found")

    night = tonight()
    existing = db.scalars(
        select(Sit).where(Sit.night == night, Sit.outcome != "cancelled")
    ).all()

    for other in existing:
        if other.stand_id == stand.id:
            if other.user_id == user.id:
                return _sit_out(other, stand.name)  # idempotent re-claim
            raise HTTPException(409, f"{stand.name} is already claimed tonight.")

    # Safety interlock: never put two people in each other's fire lanes. Only
    # fires when both stands actually have recorded arcs — absent geometry must
    # not manufacture a warning.
    for other in existing:
        other_stand = db.get(Stand, other.stand_id)
        if other_stand and shooting_arcs_conflict(
            stand.shooting_dirs_deg, other_stand.shooting_dirs_deg
        ):
            raise HTTPException(
                409,
                f"{stand.name} shares a shooting arc with {other_stand.name}, which is "
                "already claimed tonight. Pick another stand.",
            )

    # Record what the app told them about the wind, so the advice can be scored later.
    from app.forecasting.model import _tonight_conditions

    try:
        cond = _tonight_conditions(datetime.now(timezone.utc))
    except Exception:
        cond = {}
    verdict = assess(
        stand_name=stand.name,
        wind_dir_deg=cond.get("wind_dir_deg"),
        wind_speed_kmh=cond.get("wind_speed_kmh"),
        approach_dirs_deg=stand.approach_dirs_deg,
    )

    sit = Sit(
        stand_id=stand.id,
        user_id=user.id,
        night=night,
        outcome="unreported",
        wind_status=verdict.status,
        wind_text=verdict.text,
    )
    db.add(sit)
    db.commit()
    return _sit_out(sit, stand.name)


@router.patch("/sits/{sit_id}")
def update_sit(
    sit_id: uuid.UUID,
    body: OutcomeIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    sit = db.get(Sit, sit_id)
    if sit is None:
        raise HTTPException(404, "Sit not found")
    if sit.user_id and sit.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "That sit belongs to someone else")
    if body.outcome not in OUTCOMES:
        raise HTTPException(422, f"outcome must be one of {', '.join(OUTCOMES)}")

    sit.outcome = body.outcome
    if body.species_seen is not None:
        sit.species_seen = body.species_seen
    if body.notes is not None:
        sit.notes = body.notes
    if body.outcome != "unreported" and sit.ended_at is None:
        sit.ended_at = datetime.now(timezone.utc)
    db.commit()
    stand = db.get(Stand, sit.stand_id)
    return _sit_out(sit, stand.name if stand else None)


@router.post("/sits/{sit_id}/start")
def start_sit(
    sit_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    sit = db.get(Sit, sit_id)
    if sit is None:
        raise HTTPException(404, "Sit not found")
    if sit.started_at is None:
        sit.started_at = datetime.now(timezone.utc)
    db.commit()
    stand = db.get(Stand, sit.stand_id)
    return _sit_out(sit, stand.name if stand else None)


@router.get("/stands/{stand_id}/suggested-arcs")
def suggested_arcs(
    stand_id: uuid.UUID, _: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> dict:
    """Propose approach bearings from cross-camera movement, for confirmation.

    Never written automatically: a guessed arc becomes confident wind advice, and
    confident wrong advice costs more trust than an honest "yours to solve".
    """
    stand = db.get(Stand, stand_id)
    if stand is None:
        raise HTTPException(404, "Stand not found")
    return suggest_approach_arcs(db, stand)


@router.get("/stands/{stand_id}/dark-exit")
def stand_dark_exit(
    stand_id: uuid.UUID, _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """When to walk out. Stands die from how you leave them, not how you arrive."""
    stand = db.get(Stand, stand_id)
    if stand is None:
        raise HTTPException(404, "Stand not found")
    return dark_exit(db, stand)
