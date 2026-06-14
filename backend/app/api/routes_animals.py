"""Animals — candidate individuals from re-ID clustering (experimental, HITL).

Read endpoints are open to any user; curation (rename / merge / confirm / delete /
recompute) is admin-gated. Re-ID is honest about its limits: these are visual
clusters, not asserted identities.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, distinct, func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.db import get_db
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
        .where(DetectionIndividual.individual_id.in_(ids))
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
        .group_by(Individual.id, Species.common_name)
        .order_by(func.count(DetectionIndividual.detection_id).desc())
    ).all()
    thumbs = _thumb_map(db, [r.id for r in rows])
    return [
        {
            "id": str(r.id),
            "label": r.label,
            "species": r.common_name or r.species_id,
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
    if ind is None:
        raise HTTPException(404, "Individual not found")
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
        .where(DetectionIndividual.individual_id == individual_id)
        .order_by(Image.captured_at.desc())
    ).all()
    sp = db.get(Species, ind.species_id) if ind.species_id else None
    return {
        "id": str(ind.id),
        "label": ind.label,
        "status": ind.status,
        "species": sp.common_name if sp else ind.species_id,
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


@router.patch("/{individual_id}")
def patch_animal(
    individual_id: uuid.UUID,
    body: PatchBody,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    ind = db.get(Individual, individual_id)
    if ind is None:
        raise HTTPException(404, "Individual not found")
    if body.label is not None:
        ind.label = body.label.strip() or ind.label
    if body.status is not None:
        if body.status not in _STATUSES:
            raise HTTPException(422, f"status must be one of {_STATUSES}")
        ind.status = body.status
    if body.notes is not None:
        ind.notes = body.notes
    db.commit()
    return {"ok": True}


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


@router.post("/merge")
def merge_animals(
    body: MergeBody,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Fold source individuals into the target — a user assertion they're the same animal."""
    target = db.get(Individual, body.target_id)
    if target is None:
        raise HTTPException(404, "Target individual not found")
    moved = 0
    for sid in body.source_ids:
        if sid == body.target_id:
            continue
        res = db.execute(
            update(DetectionIndividual)
            .where(DetectionIndividual.individual_id == sid)
            .values(individual_id=body.target_id, confirmed_by_user=True)
        )
        moved += res.rowcount or 0
        db.execute(delete(Individual).where(Individual.id == sid))
    # The merge itself is a confirmation of the whole group.
    db.execute(
        update(DetectionIndividual)
        .where(DetectionIndividual.individual_id == body.target_id)
        .values(confirmed_by_user=True)
    )
    _refresh_range(db, target)
    db.commit()
    return {"ok": True, "merged": moved}


@router.post("/{individual_id}/confirm")
def confirm_animal(
    individual_id: uuid.UUID,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    ind = db.get(Individual, individual_id)
    if ind is None:
        raise HTTPException(404, "Individual not found")
    db.execute(
        update(DetectionIndividual)
        .where(DetectionIndividual.individual_id == individual_id)
        .values(confirmed_by_user=True)
    )
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


@router.post("/recompute")
def recompute_animals(
    _: User = Depends(get_current_admin), db: Session = Depends(get_db)
) -> dict:
    """Embed any new detections and regenerate candidate individuals.

    Confirmed individuals are preserved; only unconfirmed candidates change. Runs
    synchronously — fast once embeddings exist (the first pass embeds every crop).
    """
    from app.ai.reid import recompute

    return recompute(db)
