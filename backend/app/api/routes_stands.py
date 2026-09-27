"""Stands, claims and sit outcomes.

The stand — not the camera — is the thing a hunter sits in. Cameras are placed
where animals go; stands exist where a bullet can safely stop, and the app was
previously labelling a list of cameras "OTHER STANDS" in the UI, which is the one
place that conflation can get somebody hurt.
"""
from __future__ import annotations

import uuid
import zlib
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.forecasting.conditions import sun_times
from app.forecasting.inference import dark_exit, suggest_approach_arcs
from app.forecasting.wind import shooting_arcs_conflict
from app.models import Camera, Estate, Sit, Stand, User
from app.notifications.hold import deliver_held_in_background, has_held

router = APIRouter(tags=["stands"])

CurrentUser = Annotated[User, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]

OUTCOMES = ("unreported", "nothing", "seen", "shootable_no_shot", "shot", "cancelled")


def tonight(now: datetime | None = None) -> date:
    """The night now belongs to — before 06:00 still counts as last evening."""
    now = now or datetime.now(UTC)
    local = now.astimezone(ZoneInfo(settings.estate_timezone))
    return (local - timedelta(hours=6)).date()


# Finite and on the planet, as for a camera: one pin at latitude 1000 took the map
# down for everyone (audit B-08).
Lat = Annotated[float | None, Field(ge=-90, le=90, allow_inf_nan=False)]
Lon = Annotated[float | None, Field(ge=-180, le=180, allow_inf_nan=False)]


class StandIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    camera_id: uuid.UUID | None = None
    lat: Lat = None
    lon: Lon = None
    shooting_dirs_deg: list[int] | None = None
    approach_dirs_deg: list[int] | None = None
    notes: str | None = None


class StandPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    camera_id: uuid.UUID | None = None
    lat: Lat = None
    lon: Lon = None
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
def list_stands(_: CurrentUser, db: DB) -> list[dict]:
    # Tonight's reservations only. A dawn sit still on from the night before is in
    # /sits (somebody is in that stand now), but the coming evening is free.
    night = tonight()
    claims = {
        c.stand_id: c
        for c in db.scalars(select(Sit).where(Sit.night == night, Sit.outcome != "cancelled"))
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
        raise HTTPException(400, "Set up the estate first.")

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
            "Each stand is placed at its camera. Move it to where you actually sit. "
            "Wind advice starts once you set the directions animals come in from."
        ),
    }


@router.post("/stands", status_code=201)
def create_stand(
    body: StandIn, _: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> dict:
    estate = db.scalar(select(Estate).order_by(Estate.created_at))
    if estate is None:
        raise HTTPException(400, "Set up the estate first.")
    if body.camera_id and db.get(Camera, body.camera_id) is None:
        raise HTTPException(404, "That camera isn't on the app.")
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
        raise HTTPException(404, "That stand isn't on the app.")
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
        raise HTTPException(404, "That stand isn't on the app.")
    sits = db.scalar(select(func.count(Sit.id)).where(Sit.stand_id == stand_id))
    if sits:
        raise HTTPException(
            409,
            f"{sits} sit{'' if sits == 1 else 's'} recorded at this stand. Deleting it would wipe "
            "that history. Rename it instead.",
        )
    db.delete(stand)
    db.commit()


# ── claims ──────────────────────────────────────────────────────────────────

# What a report is worth. A report only moves up this ladder; 'unreported' and
# 'cancelled' are not on it (see update_sit).
RANK = {"nothing": 0, "seen": 1, "shootable_no_shot": 2, "shot": 3}

# A sit started and not ended is on until END SIT, for at most this long, while its
# night lasts. Bounded, because a phone that died before END SIT would otherwise
# keep it on for good.
LIVE_FOR = timedelta(hours=12)

# After the 06:00 changeover only a dawn sit is still on: one reserved before 06:00
# (so it counts toward the night before, audit A-20) and started from 03:00 that
# morning, for at most DAWN_FOR. An evening sit nobody ended is over at 06:00: the
# hunter walked home, so it is asked about ("What happened last night?") and its
# stand is free for the coming evening.
DAWN_FROM = time(3)
DAWN_FOR = timedelta(hours=6)

# How many nights back "What happened last night?" still asks about a sit.
ASK_NIGHTS = 3

# Reserving takes this per-night lock (with the night as the second key), so two
# hunters reserving at once are served one after the other: the same stand, or two
# stands whose fire lanes cross, can't both be given out.
_CLAIM_LOCK = zlib.crc32(b"gamesense.sits.claim") & 0x7FFFFFFF


class ClaimIn(BaseModel):
    stand_id: uuid.UUID


class OutcomeIn(BaseModel):
    outcome: str
    # When the hunter tapped, by the phone's clock. A tap queued with no signal can
    # arrive an hour after a newer one; this is how the server tells them apart.
    at: datetime | None = None
    # Only a deliberate "What happened?" answer sends this. It is the one way to
    # lower a report, because it is the hunter saying so, not a glove.
    correct: bool = False
    species_seen: str | None = None
    notes: str | None = None


class TapIn(BaseModel):
    """START or END SIT, with when it was tapped by the phone's clock."""

    at: datetime | None = None


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
        "reported_at": s.reported_at,
        "species_seen": s.species_seen,
        "wind_status": s.wind_status,
        "wind_text": s.wind_text,
        # The moment that verdict was for (the sit time when it was reserved).
        "wind_at": s.wind_at,
        # The sit's sunset and the sunrise after it, so Sit mode can show them with
        # no signal and nothing else loaded (sunset_local, sunrise_local).
        **sun_times(s.night),
    }


def _sit_reply(db: Session, sit: Sit) -> dict:
    stand = db.get(Stand, sit.stand_id)
    return _sit_out(sit, stand.name if stand else None)


def _done(db: Session, sit: Sit) -> dict:
    """Commit a write to a sit (or nothing, for one that changed nothing) and answer.

    Ends the transaction either way, and the sit's row lock with it (_own_sit)."""
    db.commit()
    return _sit_reply(db, sit)


def _live(now: datetime):
    """On now: started, not ended, not cancelled, and either tonight's (started in
    the last LIVE_FOR) or a dawn sit from the night before (see DAWN_FROM)."""
    night = tonight(now)
    dawn = datetime.combine(night, DAWN_FROM, tzinfo=ZoneInfo(settings.estate_timezone))
    return and_(
        Sit.started_at.is_not(None),
        Sit.ended_at.is_(None),
        Sit.outcome != "cancelled",
        or_(
            and_(Sit.night == night, Sit.started_at >= now - LIVE_FOR),
            and_(
                Sit.night == night - timedelta(days=1),
                Sit.started_at >= dawn,
                Sit.started_at >= now - DAWN_FOR,
            ),
        ),
    )


def _own_sit(db: Session, sit_id: uuid.UUID, user: User) -> Sit:
    """The sit, if this person may write to it: its hunter, or an admin for the record.

    Locked for the rest of the transaction (SELECT ... FOR UPDATE): a PATCH the phone
    gave up on can still be running when the retry or the next tap arrives, and a
    hunter and an admin can write at once. Each write then sees the one before it,
    so an older SEEN can't land on a newer SHOT. Every writer ends its transaction
    before answering, which lets the lock go.
    """
    sit = db.get(Sit, sit_id, with_for_update=True, populate_existing=True)
    if sit is None:
        raise HTTPException(404, "That sit isn't on the app.")
    if user.role == "viewer":
        raise HTTPException(403, "Viewers can look at the sits but can't change them.")
    if sit.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "That sit is another hunter's.")
    return sit


def _client_time(at: datetime | None, now: datetime) -> datetime:
    """The phone's time for a write, never later than the server's clock.

    A phone running fast would otherwise stamp a report in the future, and every
    honest write after it would look older and be ignored.
    """
    if at is None:
        return now
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return min(at, now)


@router.get("/sits")
def list_sits(_: CurrentUser, db: DB, night: date | None = None) -> list[dict]:
    """A night's sits: tonight's by default, with any sit still on from the night
    before (a dawn sit after 06:00). An asked-for night is that night only."""
    now = datetime.now(UTC)
    which = Sit.night == night if night else or_(Sit.night == tonight(now), _live(now))
    rows = db.execute(
        select(Sit, Stand.name).join(Stand, Stand.id == Sit.stand_id).where(which)
    ).all()
    return [_sit_out(s, name) for s, name in rows]


@router.get("/sits/mine")
def my_sits(user: CurrentUser, db: DB) -> dict:
    """Your sits that want something from you.

    `live`: on now (see _live), so Tonight can say "Back to sit" after the phone
    killed the app mid-sit. `to_report`: nobody said what happened, from the last
    few nights, or from tonight once it ended. A reserved sit that was never started
    is asked about too: plenty of hunters never open Sit mode, and "unreported" is
    not "saw nothing". So is a sit nobody ended, once it is no longer on: most
    hunters just walk home.
    """
    now = datetime.now(UTC)
    night = tonight(now)
    rows = db.execute(
        select(Sit, Stand.name, _live(now).label("on"))
        .join(Stand, Stand.id == Sit.stand_id)
        .where(
            Sit.user_id == user.id,
            Sit.outcome != "cancelled",
            Sit.night >= night - timedelta(days=ASK_NIGHTS),
        )
        .order_by(Sit.night.desc(), Sit.claimed_at.desc())
    ).all()
    live, to_report = [], []
    for s, name, on in rows:
        if on:
            live.append(_sit_out(s, name))
        elif s.outcome == "unreported" and (
            s.night < night or s.ended_at is not None or s.started_at is not None
        ):
            to_report.append(_sit_out(s, name))
    return {"live": live, "to_report": to_report}


def _refusal(db: Session, stand: Stand, user: User, night: date) -> Sit | str | None:
    """Why this stand can't be given to `user` tonight, or their own claim on it.

    Only meaningful under the night's lock: without it two callers can both read
    "free" and both write.
    """
    existing = db.scalars(select(Sit).where(Sit.night == night, Sit.outcome != "cancelled")).all()
    for other in existing:
        if other.stand_id == stand.id:
            if other.user_id == user.id:
                return other
            return f"{stand.name} is already claimed tonight by another hunter."

    # Safety interlock: never put two people in each other's fire lanes. Only
    # fires when both stands actually have recorded arcs — absent geometry must
    # not manufacture a warning.
    for other in existing:
        other_stand = db.get(Stand, other.stand_id)
        if other_stand and shooting_arcs_conflict(
            stand.shooting_dirs_deg, other_stand.shooting_dirs_deg
        ):
            return (
                f"{stand.name} and {other_stand.name} share a shooting arc, and "
                f"{other_stand.name} is taken tonight. Pick another stand."
            )
    return None


def _lock_night(db: Session, night: date) -> None:
    """Serialise reservations for one night until this transaction ends."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :night)"),
        {"ns": _CLAIM_LOCK, "night": night.toordinal()},
    )


def _stand_wind(db: Session, stand: Stand, night: date | None = None) -> dict:
    """Tonight's wind verdict for a stand (conditions.wind_verdict), with tonight's
    sunset and sunrise. The forecast is fetched with no database connection held
    (K-04). `night`: a dawn sit's, once that night is over, for the air now."""
    from app.forecasting.conditions import release, wind_verdict
    from app.forecasting.model import _tonight_conditions

    now = datetime.now(UTC)
    release(db)
    try:
        cond = _tonight_conditions(now) if night is None else _tonight_conditions(now, night=night)
    except Exception:
        cond = {}
    return {**wind_verdict(db, stand, cond, now=now),
            "sunset_local": cond.get("sunset_local"), "sunrise_local": cond.get("sunrise_local")}


@router.get("/stands/{stand_id}/wind")
def stand_wind(stand_id: uuid.UUID, _: CurrentUser, db: DB, sit: uuid.UUID | None = None) -> dict:
    """Tonight's wind for one stand, as the map, Stands and Tonight give it: what Sit
    mode refreshes its wind line from, so the seat never tells a different story.

    `sit` is the sit Sit mode is showing. A dawn sit still on after 06:00 belongs to
    a night that is over, and is judged for now, not for the coming evening."""
    stand = db.get(Stand, stand_id)
    if stand is None:
        raise HTTPException(404, "That stand isn't on the app.")
    night = None
    if sit is not None:
        now = datetime.now(UTC)
        # On now (_live) at this stand, and of a night already over: a dawn sit.
        mine = db.scalar(select(Sit).where(Sit.id == sit, Sit.stand_id == stand.id, _live(now)))
        if mine is not None and mine.night < tonight(now):
            night = mine.night
    return _stand_wind(db, stand, night)


@router.post("/sits", status_code=201)
def claim_stand(body: ClaimIn, user: CurrentUser, db: DB) -> dict:
    """Claim a stand for tonight.

    This is the app's data-capture mechanism, and it works because claiming has a
    payoff for the person doing it: the wind verdict and the answer to "is anyone
    else on that ridge". The row is written before the sit, when the phone is out
    and hands are clean — not at 23:40 in the dark after a blank evening.

    Two hunters reserving at the same moment are served one after the other (a
    per-night lock), so the second is told the stand, or the fire lane, is taken.
    The weather is asked for before the lock: it can take seconds, and nobody
    should queue behind somebody else's weather call.
    """
    if user.role not in ("admin", "member"):
        raise HTTPException(403, "Viewers can look at the stands but can't reserve one.")
    stand = db.get(Stand, body.stand_id)
    if stand is None:
        raise HTTPException(404, "That stand isn't on the app.")

    # Record what the app told them about the wind, so the advice can be scored
    # later: the verdict every other screen gives this stand, for the sit time.
    verdict = _stand_wind(db, stand)

    night = tonight()
    _lock_night(db, night)
    refusal = _refusal(db, stand, user, night)
    if isinstance(refusal, Sit):
        db.commit()  # ends the transaction, and the lock with it
        return _sit_out(refusal, stand.name)  # idempotent re-claim
    if refusal:
        db.rollback()
        raise HTTPException(409, refusal)

    sit = Sit(
        stand_id=stand.id,
        user_id=user.id,
        night=night,
        outcome="unreported",
        wind_status=verdict["status"],
        wind_text=verdict["text"],
        wind_at=datetime.fromisoformat(verdict["at"]),
    )
    db.add(sit)
    try:
        db.commit()
    except IntegrityError:
        # The unique index caught a second live reservation the lock should have
        # stopped. Answer as the check would have.
        db.rollback()
        mine = db.scalar(
            select(Sit).where(
                Sit.stand_id == stand.id, Sit.night == night, Sit.outcome != "cancelled",
                Sit.user_id == user.id,
            )
        )
        if mine is not None:
            return _sit_out(mine, stand.name)
        raise HTTPException(
            409, f"{stand.name} is already claimed tonight by another hunter."
        ) from None
    return _sit_out(sit, stand.name)


@router.patch("/sits/{sit_id}")
def update_sit(sit_id: uuid.UUID, body: OutcomeIn, user: CurrentUser, db: DB) -> dict:
    """Record what happened on a sit. Safe to replay, late and in any order.

    Sit mode keeps taps on the phone when there is no signal and sends them later,
    so a report can arrive twice, late, or after a newer one. The rules:

    - A report never goes down (shot > shootable_no_shot > seen > nothing). Only a
      `correct: true` answer lowers it, or clears it back to 'unreported'.
    - A write stamped earlier than the report already kept (`reported_at`) is
      ignored. That is what stops an old queued tap undoing a correction.
    - A cancelled reservation stays cancelled, and only an unreported one can be
      cancelled.

    An ignored write still answers 200 with the sit as it is, so the phone drops it
    from its queue. Reporting never ends the sit; END SIT does.
    """
    sit = _own_sit(db, sit_id, user)
    if body.outcome not in OUTCOMES:
        raise HTTPException(422, f"outcome must be one of {', '.join(OUTCOMES)}")

    current, target = sit.outcome, body.outcome
    if current == "cancelled":
        if target == "cancelled":
            return _done(db, sit)
        raise HTTPException(409, "That reservation was cancelled. Reserve the stand again.")

    at = _client_time(body.at, datetime.now(UTC))
    if sit.reported_at is not None and at < sit.reported_at:
        return _done(db, sit)
    if target == "cancelled" and current != "unreported":
        raise HTTPException(409, "You've already said what happened on this sit.")

    if target == current:
        took, same = False, True
    elif body.correct or target == "cancelled":
        took, same = True, False
    else:
        # Up the ladder only. A lower report, or clearing one, without a correction
        # is a glove on the button or an old tap: keep what is on record.
        took = target in RANK and (current not in RANK or RANK[target] > RANK[current])
        same = False

    if took:
        sit.outcome = target
    if took or same:
        if body.species_seen is not None:
            sit.species_seen = body.species_seen
        if body.notes is not None:
            sit.notes = body.notes
    # Only a write that counted moves the clock. Moving it for an ignored lower tap
    # would make a queued, older SHOT look stale when it finally arrives.
    if took or body.correct:
        sit.reported_at = at
    return _done(db, sit)


@router.post("/sits/{sit_id}/start")
def start_sit(
    sit_id: uuid.UUID, user: CurrentUser, db: DB, body: TapIn | None = None
) -> dict:
    """Sit mode opened. Idempotent: the first start the server hears is kept."""
    sit = _own_sit(db, sit_id, user)
    if sit.outcome == "cancelled":
        raise HTTPException(409, "That reservation was cancelled. Reserve the stand again.")
    if sit.started_at is None:
        at = _client_time(body.at if body else None, datetime.now(UTC))
        sit.started_at = max(at, sit.claimed_at) if sit.claimed_at else at
    return _done(db, sit)


@router.post("/sits/{sit_id}/end")
def end_sit(
    sit_id: uuid.UUID, user: CurrentUser, db: DB, background: BackgroundTasks,
    body: TapIn | None = None,
) -> dict:
    """END SIT. Idempotent: the first end the server hears is the one it keeps.

    The outcome is left alone. A sit ended with nothing reported stays
    'unreported' and the phone asks what happened; a blank sit is never assumed.

    The alerts that waited while the hunter sat go out now, as one message, once
    this has answered (app.notifications.hold).
    """
    sit = _own_sit(db, sit_id, user)
    if sit.outcome == "cancelled":
        raise HTTPException(409, "That reservation was cancelled. Reserve the stand again.")
    if sit.started_at is None:
        raise HTTPException(409, "That sit hasn't started.")
    if sit.ended_at is None:
        at = _client_time(body.at if body else None, datetime.now(UTC))
        sit.ended_at = max(at, sit.started_at)
    out = _done(db, sit)
    if sit.user_id is not None and has_held(db, sit.user_id):
        background.add_task(deliver_held_in_background, sit.user_id)
    return out


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
        raise HTTPException(404, "That stand isn't on the app.")
    return suggest_approach_arcs(db, stand)


@router.get("/stands/{stand_id}/dark-exit")
def stand_dark_exit(
    stand_id: uuid.UUID, _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """When to walk out. Stands die from how you leave them, not how you arrive."""
    stand = db.get(Stand, stand_id)
    if stand is None:
        raise HTTPException(404, "That stand isn't on the app.")
    return dark_exit(db, stand)
