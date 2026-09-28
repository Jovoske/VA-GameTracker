"""Animals — candidate individuals from re-ID clustering (experimental, HITL).

Read endpoints are open to any user; curation (rename / merge / confirm / delete /
recompute) is admin-gated. Re-ID is honest about its limits: these are visual
clusters, not asserted identities.
"""
from __future__ import annotations

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, distinct, func, or_, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.api.visibility import NO_PEOPLE
from app.core.db import get_db
from app.i18n import DEFAULT, current, localize, renamed, species_name, t
from app.models import (
    Camera,
    Detection,
    DetectionIndividual,
    Image,
    Individual,
    Species,
    User,
)

router = APIRouter(prefix="/animals", tags=["animals"])

_STATUSES = ("active", "missing", "archived")


def _thumb_map(db: Session, ids: list[uuid.UUID]) -> dict:
    """individual_id → image_id of its clearest sighting (highest species_conf)."""
    if not ids:
        return {}
    ranked = (
        select(
            DetectionIndividual.individual_id.label("ind"),
            Image.id.label("image_id"),
            func.row_number()
            .over(
                partition_by=DetectionIndividual.individual_id,
                order_by=Detection.species_conf.desc().nullslast(),
            )
            .label("rn"),
        )
        .join(Detection, DetectionIndividual.detection_id == Detection.id)
        .join(Image, Detection.image_id == Image.id)
        # A frame with a person or a vehicle in it is an admin's (visibility.PEOPLE),
        # and one marked "nothing in it" is nobody's picture of the animal.
        .where(DetectionIndividual.individual_id.in_(ids), NO_PEOPLE,
               Image.is_empty_frame.isnot(True))
        .subquery()
    )
    rows = db.execute(select(ranked.c.ind, ranked.c.image_id).where(ranked.c.rn == 1)).all()
    return {r.ind: r.image_id for r in rows}


@router.get("")
def list_animals(
    _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict]:
    rows = db.execute(
        select(
            Individual.id,
            Individual.label,
            Individual.species_id,
            Individual.status,
            Species.common_name,
            func.count(DetectionIndividual.detection_id).label("sightings"),
            func.min(Image.captured_at).label("first_seen"),
            func.max(Image.captured_at).label("last_seen"),
            func.count(distinct(Camera.id)).label("n_cameras"),
            func.bool_or(DetectionIndividual.confirmed_by_user).label("confirmed"),
        )
        .outerjoin(Species, Individual.species_id == Species.id)
        .join(DetectionIndividual, DetectionIndividual.individual_id == Individual.id)
        .join(Detection, DetectionIndividual.detection_id == Detection.id)
        .join(Image, Detection.image_id == Image.id)
        .join(Camera, Image.camera_id == Camera.id)
        # A hidden species (rabbits) is out of the app, its animals too; and a photo
        # marked "nothing in it" is not a sighting of anybody.
        .where(or_(Individual.species_id.is_(None), Species.hidden.is_(False)),
               Image.is_empty_frame.isnot(True), NO_PEOPLE)
        .group_by(Individual.id, Species.common_name)
        .order_by(func.count(DetectionIndividual.detection_id).desc())
    ).all()
    thumbs = _thumb_map(db, [r.id for r in rows])
    return [
        {
            "id": str(r.id),
            "label": said_label(r.label, r.species_id),
            "species": species_name(r.species_id, r.common_name),
            "species_id": r.species_id,
            "status": r.status,
            "sightings": r.sightings,
            "first_seen": r.first_seen,
            "last_seen": r.last_seen,
            "cameras": r.n_cameras,
            "confirmed": bool(r.confirmed),
            "thumb_image_id": str(thumbs[r.id]) if r.id in thumbs else None,
        }
        for r in rows
    ]


@router.get("/{individual_id}")
def get_animal(
    individual_id: uuid.UUID,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ind = db.get(Individual, individual_id)
    sp = db.get(Species, ind.species_id) if ind is not None and ind.species_id else None
    # An animal of a hidden species is out of the app, as it is out of the list.
    if ind is None or (sp is not None and sp.hidden):
        raise HTTPException(404, t("animals.not_found"))
    # The sightings the list counts: not a photo marked "nothing in it", nor one of a
    # hidden species (re-ID can put a mislabelled frame with the animal).
    sightings = db.execute(
        select(
            Image.id,
            Image.captured_at,
            Camera.name,
            Detection.species_conf,
            DetectionIndividual.match_conf,
            DetectionIndividual.confirmed_by_user,
        )
        .join(Detection, DetectionIndividual.detection_id == Detection.id)
        .join(Image, Detection.image_id == Image.id)
        .join(Camera, Image.camera_id == Camera.id)
        .outerjoin(Species, Species.id == Detection.species_id)
        .where(DetectionIndividual.individual_id == individual_id, NO_PEOPLE,
               Image.is_empty_frame.isnot(True),
               or_(Detection.species_id.is_(None), Species.hidden.is_(False)))
        .order_by(Image.captured_at.desc())
    ).all()
    return {
        "id": str(ind.id),
        "label": said_label(ind.label, ind.species_id),
        "status": ind.status,
        "species": species_name(ind.species_id, sp.common_name if sp else None),
        "notes": ind.notes,
        "first_seen": ind.first_seen,
        "last_seen": ind.last_seen,
        "sightings": [
            {
                "image_id": str(s.id),
                "captured_at": s.captured_at,
                "camera": s.name,
                "species_conf": s.species_conf,
                "match_conf": s.match_conf,
                "confirmed": s.confirmed_by_user,
            }
            for s in sightings
        ],
    }


class PatchBody(BaseModel):
    label: str | None = None
    status: str | None = None
    notes: str | None = None


# The name "Look for repeats" gives a new group: "Wild boar #3". Anything else is a
# name a hunter chose.
_AUTO_LABEL = re.compile(r".+ #\d+")


def is_auto_label(label: str | None) -> bool:
    return not label or bool(_AUTO_LABEL.fullmatch(label.strip()))


def said_label(label: str | None, species_id: str | None) -> str | None:
    """A group's name in the reader's language: "Villisika #3" for the "Wild boar #3"
    Look for repeats gave it. A name a hunter chose is theirs, as they wrote it."""
    m = re.fullmatch(r"(.+) #(\d+)", (label or "").strip())
    if m is None or not species_id or current() == DEFAULT or renamed(species_id, m.group(1)):
        return label
    return f"{species_name(species_id, None)} #{m.group(2)}"


def _confirm(db: Session, individual_id: uuid.UUID) -> None:
    """Every sighting of the animal is the hunter's word now: "Look for repeats" keeps
    an animal with a confirmed sighting as it is, and rebuilds the rest."""
    db.execute(
        update(DetectionIndividual)
        .where(DetectionIndividual.individual_id == individual_id)
        .values(confirmed_by_user=True)
    )


@router.patch("/{individual_id}")
def patch_animal(
    individual_id: uuid.UUID,
    body: PatchBody,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Name an animal, or note or mark it.

    Naming it says which animal it is, so it confirms its sightings: "Look for
    repeats" used to throw away every group nobody had confirmed, names and notes
    and all, and bring it back as "Wild boar #3".
    """
    ind = db.get(Individual, individual_id)
    if ind is None:
        raise HTTPException(404, t("animals.gone"))
    if body.label is not None:
        label = " ".join(body.label.split())
        if not label:
            raise HTTPException(422, t("animals.name_first"))
        if len(label) > 60:
            raise HTTPException(422, t("animals.name_long"))
        ind.label = label
    if body.status is not None:
        if body.status not in _STATUSES:
            raise HTTPException(422, t("animals.bad_status", statuses=_STATUSES))
        ind.status = body.status
    if body.notes is not None:
        ind.notes = body.notes.strip() or None
    if body.model_fields_set & {"label", "status", "notes"}:
        _confirm(db, individual_id)
    db.commit()
    return {"ok": True, "id": str(ind.id), "label": said_label(ind.label, ind.species_id),
            "status": ind.status,
            "notes": ind.notes, "confirmed": True}


def _refresh_range(db: Session, ind: Individual) -> None:
    rng = db.execute(
        select(func.min(Image.captured_at), func.max(Image.captured_at))
        .join(Detection, Detection.image_id == Image.id)
        .join(DetectionIndividual, DetectionIndividual.detection_id == Detection.id)
        .where(DetectionIndividual.individual_id == ind.id)
    ).one()
    ind.first_seen, ind.last_seen = rng[0], rng[1]


class MergeBody(BaseModel):
    source_ids: list[uuid.UUID]
    target_id: uuid.UUID
    # The name to keep, when more than one of them had been named (the app asks).
    label: str | None = None


@router.post("/merge")
def merge_animals(
    body: MergeBody,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Fold source individuals into the target — a user assertion they're the same animal.

    The merged animal keeps the name a hunter gave: the one asked for (`label`), or
    else the target's own if a hunter named it, or else the one name among the
    others. It used to keep whichever had the most sightings and drop the typed one.
    Notes from all of them are kept.
    """
    target = db.get(Individual, body.target_id)
    if target is None:
        raise HTTPException(404, t("animals.merge_target"))
    sources = [db.get(Individual, sid) for sid in dict.fromkeys(body.source_ids)
               if sid != body.target_id]
    sources = [ind for ind in sources if ind is not None]
    named = [ind.label for ind in sources if not is_auto_label(ind.label)]
    chosen = " ".join((body.label or "").split())
    if chosen:
        target.label = chosen[:60]
    elif is_auto_label(target.label) and len(set(named)) == 1:
        target.label = named[0]
    notes = [n for n in [target.notes, *(ind.notes for ind in sources)] if n and n.strip()]
    target.notes = "\n".join(dict.fromkeys(n.strip() for n in notes)) or None
    moved = 0
    for sid in (ind.id for ind in sources):
        res = db.execute(
            update(DetectionIndividual)
            .where(DetectionIndividual.individual_id == sid)
            .values(individual_id=body.target_id, confirmed_by_user=True)
        )
        moved += res.rowcount or 0
        db.execute(delete(Individual).where(Individual.id == sid))
    # The merge itself is a confirmation of the whole group.
    _confirm(db, body.target_id)
    _refresh_range(db, target)
    db.commit()
    return {"ok": True, "merged": moved, "label": said_label(target.label, target.species_id)}


@router.post("/{individual_id}/confirm")
def confirm_animal(
    individual_id: uuid.UUID,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    ind = db.get(Individual, individual_id)
    if ind is None:
        raise HTTPException(404, t("animals.not_found"))
    _confirm(db, individual_id)
    db.commit()
    return {"ok": True}


@router.delete("/{individual_id}")
def delete_animal(
    individual_id: uuid.UUID,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Remove the individual; its sightings become unassigned (detections are untouched)."""
    db.execute(
        delete(DetectionIndividual).where(DetectionIndividual.individual_id == individual_id)
    )
    db.execute(delete(Individual).where(Individual.id == individual_id))
    db.commit()
    return {"ok": True}


REID_STATUS = "reid_status"  # app_settings: what the last "Look for repeats" came to


@router.post("/recompute")
def recompute_animals(
    _: Annotated[User, Depends(get_current_admin)], db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Embed any new detections and regenerate candidate individuals.

    Confirmed individuals are preserved; only unconfirmed candidates change. It runs
    as a job of its own (`pipeline.py reid`, under the pipeline lock, waiting for a
    running fetch to finish): the first pass embeds every crop, which is minutes of
    work a phone request cannot wait through. Poll GET /animals/recompute/status.
    """
    from datetime import UTC, datetime

    from app import jobs

    if jobs.holder("reid") is not None:
        return {"status": "busy", "note": t("animals.reid_running")}
    if not jobs.spawn("reid"):
        raise HTTPException(503, t("cameras.start_failed"))
    jobs.note(db, REID_STATUS, state="queued", queued_at=datetime.now(UTC))
    return {"status": "started", "note": t("animals.reid_started")}


@router.get("/recompute/status")
def recompute_status(
    _: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Where the last "Look for repeats" is: queued, waiting (a photo fetch holds the
    server), running, done (with what it found) or failed."""
    from app import jobs

    note = jobs.read_note(db, REID_STATUS)
    state = note.get("state") or "never"
    marked = jobs.holder("reid") is not None
    if state in ("queued", "running") and not marked:
        # Its process is starting, or it died without saying: starting is short.
        from datetime import UTC, datetime, timedelta

        since = note.get("started_at") or note.get("queued_at")
        if since and datetime.now(UTC) - datetime.fromisoformat(since) > timedelta(minutes=2):
            state = "failed"
    elif state == "queued" and marked and jobs.holder("pipeline") is not None:
        state = "waiting"
    return {"state": state, "result": note.get("result"), "error": localize(note.get("error")),
            "finished_at": note.get("finished_at")}
