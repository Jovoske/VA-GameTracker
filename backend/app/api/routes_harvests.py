"""The harvest book: what was taken on the estate, and the season's export.

The owner keeps a book of every animal taken for the annual return. A hunter logs
theirs the morning after a SHOT, from the card on Tonight or Stands (one form:
species, sex, age class, the seal number when there is one, weight, notes, when),
and can change it later; an admin can log one by hand (a driven hunt, a guest's
animal, a sit nobody reserved) and exports the season as a CSV from Settings.

Nothing here counts or ranks: no tallies per hunter, no leaderboards (redesign 03
§11). Members and admins write; a member sees and changes their own lines, an admin
everyone's; viewers look at nothing here, as there is nothing of theirs.
"""
from __future__ import annotations

import csv
import io
import unicodedata
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.ai.classifier import ESTATE_KEYS, default_name
from app.ai.species import _ensure_species
from app.api.deps import get_current_admin, get_current_user
from app.api.routes_stands import tonight
from app.core.config import settings
from app.core.db import get_db
from app.forecasting.model import sentence_case
from app.models import Harvest, Sit, Species, Stand, User
from app.people import name_for

router = APIRouter(tags=["harvests"])
CurrentUser = Annotated[User, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]

SEXES = ("male", "female", "unknown")
AGES = ("juvenile", "young_adult", "mature_adult", "old", "unknown")
SEX_WORDS = {"male": "Male", "female": "Female", "unknown": "Not sure"}
AGE_WORDS = {"juvenile": "Young of the year", "young_adult": "Young adult",
             "mature_adult": "Adult", "old": "Old", "unknown": "Not sure"}

# The morning card asks about a SHOT for this many nights, then lets it be.
ASK_NIGHTS = 7
# The season the export covers starts on this day (1 April to 31 March).
SEASON_START = (4, 1)
# A phone's clock a little ahead is not a harvest in the future.
CLOCK_SLACK = timedelta(minutes=10)
EARLIEST = datetime(2000, 1, 1, tzinfo=UTC)

VIEWERS_LOOK = "Viewers can’t log a harvest."
NOT_YOURS = "That harvest is another hunter’s. An admin can change it."


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.estate_timezone)


def season_of(at: datetime) -> int:
    """The season a moment belongs to, by the year it started (2026 = 2026-27)."""
    local = at.astimezone(_tz())
    return local.year if (local.month, local.day) >= SEASON_START else local.year - 1


def season_bounds(season: int) -> tuple[datetime, datetime]:
    """1 April of `season` to 1 April the year after, on the estate's clock."""
    start = date(season, *SEASON_START)
    return (datetime.combine(start, time(0), tzinfo=_tz()),
            datetime.combine(start.replace(year=season + 1), time(0), tzinfo=_tz()))


def season_label(season: int) -> str:
    return f"{season}–{str(season + 1)[-2:]}"


def _plain(value: str | None, limit: int, what: str, *, lines: bool = False) -> str | None:
    """Words as typed (one line of them unless `lines`), or None for nothing;
    refused in words."""
    if value is None:
        return None
    if any(unicodedata.category(ch) in {"Cc", "Cf", "Cs"} and ch not in "\n\t" for ch in value):
        raise ValueError(f"The {what} has hidden characters in it. Retype it.")
    value = value.strip() if lines else " ".join(value.split())
    if len(value) > limit:
        raise ValueError(f"The {what} is at most {limit} characters.")
    return value or None


class _Words(BaseModel):
    """The typed fields of a harvest, checked the same way for a new line and a change."""

    seal: str | None = None
    notes: str | None = None
    # An admin writes a guest's name, or the full name the return wants.
    hunter: str | None = None
    weight_kg: float | None = Field(default=None, gt=0, lt=1000, allow_inf_nan=False)

    @field_validator("seal")
    @classmethod
    def check_seal(cls, v: str | None) -> str | None:
        return _plain(v, 40, "seal number")

    @field_validator("notes")
    @classmethod
    def check_notes(cls, v: str | None) -> str | None:
        return _plain(v, 500, "note", lines=True)

    @field_validator("hunter")
    @classmethod
    def check_hunter(cls, v: str | None) -> str | None:
        return _plain(v, 60, "name")


class HarvestIn(_Words):
    # The phone names it, so saving again after hearing nothing back (a weak signal)
    # is the same line, not a second animal.
    id: uuid.UUID | None = None
    sit_id: uuid.UUID | None = None
    stand_id: uuid.UUID | None = None
    species_id: str
    sex: str = "unknown"
    age_class: str = "unknown"
    taken_at: datetime | None = None


class HarvestPatch(_Words):
    species_id: str | None = None
    sex: str | None = None
    age_class: str | None = None
    taken_at: datetime | None = None
    stand_id: uuid.UUID | None = None


def _can_write(user: User) -> None:
    if user.role not in ("admin", "member"):
        raise HTTPException(403, VIEWERS_LOOK)


def _mine(h: Harvest, user: User) -> bool:
    return user.role == "admin" or user.id in (h.user_id, h.created_by)


def _check_kind(species_id: str | None, sex: str | None, age: str | None) -> None:
    if species_id is not None and species_id not in ESTATE_KEYS:
        raise HTTPException(422, "Pick one of the animals on the list.")
    if sex is not None and sex not in SEXES:
        raise HTTPException(422, "Sex is male, female or not sure.")
    if age is not None and age not in AGES:
        raise HTTPException(422, "Pick an age from the list.")


def _when(at: datetime | None, now: datetime) -> datetime | None:
    if at is None:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=_tz())
    if at > now + CLOCK_SLACK:
        raise HTTPException(422, "That time is still to come. Check the date.")
    if at < EARLIEST:
        raise HTTPException(422, "That date is too long ago. Check the year.")
    return at


def _stand(db: Session, stand_id: uuid.UUID | None) -> Stand | None:
    if stand_id is None:
        return None
    stand = db.get(Stand, stand_id)
    if stand is None:
        raise HTTPException(404, "That stand isn’t on the app.")
    return stand


def _out(db: Session, h: Harvest, user: User, names: dict | None = None,
         stands: dict | None = None) -> dict:
    """A line as the app shows it. `names` and `stands` save a query per line in a list."""
    names = names if names is not None else _species_names(db)
    if stands is None:
        stand = db.get(Stand, h.stand_id) if h.stand_id else None
    else:
        stand = stands.get(h.stand_id)
    return {
        "id": str(h.id),
        "sit_id": str(h.sit_id) if h.sit_id else None,
        "stand_id": str(h.stand_id) if h.stand_id else None,
        "stand": stand.name if stand else None,
        "hunter": h.hunter,
        "yours": h.user_id == user.id,
        "species_id": h.species_id,
        "species": names.get(h.species_id) or default_name(h.species_id),
        "sex": h.sex,
        "age_class": h.age_class,
        "seal": h.seal,
        "weight_kg": h.weight_kg,
        "notes": h.notes,
        "taken_at": h.taken_at,
        "created_at": h.created_at,
        "can_edit": _mine(h, user),
    }


def _species_names(db: Session) -> dict[str, str]:
    return {k: sentence_case(n) for k, n in db.execute(select(Species.id, Species.common_name))}


@router.get("/harvests")
def list_harvests(user: CurrentUser, db: DB, season: int | None = None) -> dict:
    """A season's harvest, newest first: everyone's for an admin, your own otherwise.

    `seasons` lists the seasons with a line in them (and the current one), newest
    first, for the picker; the export takes the same `season`.
    """
    now = datetime.now(UTC)
    current = season_of(now)
    season = current if season is None else season
    if not 2000 <= season <= current + 1:
        raise HTTPException(422, "Pick a season from the list.")
    start, end = season_bounds(season)
    q = select(Harvest).where(Harvest.taken_at >= start, Harvest.taken_at < end)
    seasons_q = select(func.min(Harvest.taken_at), func.max(Harvest.taken_at))
    if user.role != "admin":
        mine = or_(Harvest.user_id == user.id, Harvest.created_by == user.id)
        q = q.where(mine)
        seasons_q = seasons_q.where(mine)
    rows = db.scalars(q.order_by(Harvest.taken_at.desc(), Harvest.id.desc())).all()
    first, last = db.execute(seasons_q).one()
    seasons = {current}
    if first is not None:
        seasons.update(range(season_of(first), season_of(last) + 1))
    names = _species_names(db)
    stands = {s.id: s for s in db.scalars(select(Stand))}
    return {
        "season": season,
        "label": season_label(season),
        "from": start.date().isoformat(),
        "to": (end - timedelta(days=1)).date().isoformat(),
        "seasons": [{"season": s, "label": season_label(s)} for s in sorted(seasons, reverse=True)],
        "items": [_out(db, h, user, names, stands) for h in rows],
        "can_export": user.role == "admin",
    }


@router.get("/harvests/asks")
def harvest_asks(user: CurrentUser, db: DB) -> list[dict]:
    """Your SHOTs of the last ASK_NIGHTS nights with nothing logged yet: the morning
    card ("You shot at Puente last night. Log it?"). From the morning after (06:00),
    never on the night itself, and not once you said there was nothing to log."""
    if user.role not in ("admin", "member"):
        return []
    night = tonight()
    logged = exists().where(Harvest.sit_id == Sit.id)
    rows = db.execute(
        select(Sit, Stand.name)
        .join(Stand, Stand.id == Sit.stand_id)
        .where(
            Sit.user_id == user.id, Sit.outcome == "shot", Sit.no_harvest_at.is_(None),
            Sit.night < night, Sit.night >= night - timedelta(days=ASK_NIGHTS), ~logged,
        )
        .order_by(Sit.night.desc(), Sit.claimed_at.desc())
    ).all()
    return [{
        "sit_id": str(s.id),
        "stand_id": str(s.stand_id),
        "stand": name,
        "night": s.night.isoformat(),
        # When SHOT was tapped, for the form's time.
        "shot_at": s.reported_at or s.ended_at or s.started_at,
    } for s, name in rows]


def _sit_for(db: Session, sit_id: uuid.UUID, user: User) -> Sit:
    sit = db.get(Sit, sit_id)
    if sit is None:
        raise HTTPException(404, "That sit isn’t on the app.")
    if sit.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "That sit is another hunter’s.")
    return sit


@router.post("/harvests", status_code=201)
def log_harvest(body: HarvestIn, user: CurrentUser, db: DB, response: Response) -> dict:
    """Log an animal taken. From a sit (the morning card): only a sit reported as a
    SHOT, yours (or anyone's, for an admin), and the line is its hunter's. Without
    one: yours, or for an admin whoever `hunter` names.

    A second save with the same `id` is the same line (200, not a second animal)."""
    _can_write(user)
    _check_kind(body.species_id, body.sex, body.age_class)
    now = datetime.now(UTC)
    taken = _when(body.taken_at, now)
    if body.id is not None:
        same = db.get(Harvest, body.id)
        if same is not None:
            if not _mine(same, user):
                raise HTTPException(409, "That harvest couldn’t be saved. Close it and try again.")
            response.status_code = 200
            return _out(db, same, user)

    hunter_user: User | None = user
    stand = _stand(db, body.stand_id)
    sit = None
    if body.sit_id is not None:
        sit = _sit_for(db, body.sit_id, user)
        if sit.outcome != "shot":
            raise HTTPException(409, "That sit isn’t reported as a shot. Say what happened first.")
        stand = db.get(Stand, sit.stand_id)
        hunter_user = db.get(User, sit.user_id) if sit.user_id else None
        taken = taken or sit.reported_at or sit.ended_at or sit.started_at
    # A removed hunter's sit carries no name: the line says "Hunter" until an admin
    # writes one.
    hunter = body.hunter if user.role == "admin" and body.hunter else name_for(hunter_user)
    _ensure_species(db, body.species_id, default_name(body.species_id))
    harvest_id = body.id or uuid.uuid4()
    fresh = db.execute(
        pg_insert(Harvest).values(
            id=harvest_id, sit_id=sit.id if sit else None, stand_id=stand.id if stand else None,
            user_id=hunter_user.id if hunter_user else None, hunter=hunter,
            species_id=body.species_id, sex=body.sex, age_class=body.age_class, seal=body.seal,
            weight_kg=body.weight_kg, notes=body.notes, taken_at=taken or now,
            created_by=user.id,
        ).on_conflict_do_nothing(index_elements=[Harvest.id]).returning(Harvest.id)
    ).first() is not None
    db.commit()
    h = db.get(Harvest, harvest_id)
    if h is None or not _mine(h, user):
        raise HTTPException(409, "That harvest couldn’t be saved. Close it and try again.")
    if not fresh:
        response.status_code = 200
    return _out(db, h, user)


def _own_harvest(db: Session, harvest_id: uuid.UUID, user: User) -> Harvest:
    _can_write(user)
    h = db.get(Harvest, harvest_id)
    if h is None:
        raise HTTPException(404, "That harvest isn’t in the book any more.")
    if not _mine(h, user):
        raise HTTPException(403, NOT_YOURS)
    return h


@router.patch("/harvests/{harvest_id}")
def change_harvest(harvest_id: uuid.UUID, body: HarvestPatch, user: CurrentUser, db: DB) -> dict:
    """Put a line right: the hunter who logged it or whose it is, or an admin. Only
    the fields sent change; an empty seal, weight or note (null) clears it. Only an
    admin changes the name on it."""
    h = _own_harvest(db, harvest_id, user)
    sent = body.model_fields_set
    _check_kind(body.species_id, body.sex, body.age_class)
    if "species_id" in sent:
        if body.species_id is None:
            raise HTTPException(422, "Pick one of the animals on the list.")
        _ensure_species(db, body.species_id, default_name(body.species_id))
        h.species_id = body.species_id
    for field in ("sex", "age_class"):
        if field in sent and getattr(body, field) is not None:
            setattr(h, field, getattr(body, field))
    for field in ("seal", "weight_kg", "notes"):
        if field in sent:
            setattr(h, field, getattr(body, field))
    if "taken_at" in sent and body.taken_at is not None:
        h.taken_at = _when(body.taken_at, datetime.now(UTC))
    if "hunter" in sent and body.hunter:
        if user.role != "admin":
            raise HTTPException(403, "Only an admin changes the name on a harvest.")
        h.hunter = body.hunter
    if "stand_id" in sent and h.sit_id is None:
        stand = _stand(db, body.stand_id)
        h.stand_id = stand.id if stand else None
    db.commit()
    return _out(db, h, user)


@router.delete("/harvests/{harvest_id}")
def delete_harvest(harvest_id: uuid.UUID, user: CurrentUser, db: DB) -> dict:
    """Take a line out of the book (logged by mistake). The sit it came from asks
    again the next morning while it is recent."""
    h = _own_harvest(db, harvest_id, user)
    db.delete(h)
    db.commit()
    return {"status": "deleted", "id": str(harvest_id)}


class NothingIn(BaseModel):
    # False takes it back (the card's Undo).
    nothing: bool = True


@router.post("/sits/{sit_id}/no-harvest")
def nothing_to_log(sit_id: uuid.UUID, user: CurrentUser, db: DB,
                   body: NothingIn | None = None) -> dict:
    """The SHOT left nothing to log (a miss, or an animal not found): the morning
    card stops asking. The sit's report stays a shot; the book has no line for it."""
    _can_write(user)
    sit = _sit_for(db, sit_id, user)
    nothing = body.nothing if body is not None else True
    if nothing and sit.no_harvest_at is None:
        sit.no_harvest_at = datetime.now(UTC)
    elif not nothing:
        sit.no_harvest_at = None
    db.commit()
    return {"sit_id": str(sit.id), "nothing_to_log": sit.no_harvest_at is not None}


# ── the season's export ─────────────────────────────────────────────────────

COLUMNS = ["Date", "Time", "Species", "Sex", "Age", "Seal number", "Weight (kg)", "Hunter",
           "Stand", "Notes"]


def _cell(value) -> str:
    """A cell as text. One that starts like a formula (=, +, -, @) is written with a
    ' in front, so a note typed as "=HYPERLINK(...)" can't run in a spreadsheet."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/harvests/export.csv")
def export_season(
    admin: Annotated[User, Depends(get_current_admin)],
    db: DB,
    season: Annotated[int | None, Query(description="The year the season started")] = None,
) -> Response:
    """The season's harvest as a CSV for the annual return (admins), oldest first, on
    the estate's clock. Opens as it is in a spreadsheet: UTF-8 with a byte-order mark,
    so "García" and "Añojo" come out right in Excel."""
    current = season_of(datetime.now(UTC))
    season = current if season is None else season
    if not 2000 <= season <= current + 1:
        raise HTTPException(422, "Pick a season from the list.")
    start, end = season_bounds(season)
    rows = db.scalars(
        select(Harvest).where(Harvest.taken_at >= start, Harvest.taken_at < end)
        .order_by(Harvest.taken_at, Harvest.id)
    ).all()
    names = _species_names(db)
    stands = {s.id: s.name for s in db.scalars(select(Stand))}
    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(COLUMNS)
    for h in rows:
        local = h.taken_at.astimezone(_tz())
        weight = None if h.weight_kg is None else f"{h.weight_kg:g}"
        out.writerow([_cell(v) for v in (
            local.strftime("%Y-%m-%d"), local.strftime("%H:%M"),
            names.get(h.species_id) or default_name(h.species_id),
            SEX_WORDS.get(h.sex, h.sex), AGE_WORDS.get(h.age_class, h.age_class),
            h.seal, weight, h.hunter, stands.get(h.stand_id), h.notes,
        )])
    name = f"harvest-{season}-{str(season + 1)[-2:]}.csv"
    return Response(
        content="﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"',
                 "Cache-Control": "no-store"},
    )
