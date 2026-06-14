"""Individual re-identification — experimental, human-in-the-loop.

Honest scope, measured on this estate's data (374 night-IR detections): a DINOv2
species backbone embeds "wild boar, at night, in IR" far more strongly than "this
particular boar." A threshold sweep showed every loose setting collapses most of a
species into one giant blob (e.g. 187/192 boar as a single cluster — a false
"individual"), while only a very tight cosine threshold (~0.94) avoids that, at
which point it groups *only near-duplicate frames* (burst shots of one animal
moment). Reliable cross-night re-ID is therefore beyond this model on this data.

So we use the embeddings for what they can honestly support — collapsing
near-duplicate sightings into candidate individuals — and lean on human curation
(merge / confirm) to build real individual histories. Nothing is auto-asserted as
an identity, per the spec's "never claim certainty" rule.

Recompute respects curation: any individual with ≥1 user-confirmed sighting is
preserved untouched and fresh detections may attach to it; only the unconfirmed
candidates are regenerated.
"""
from __future__ import annotations

import uuid

from sqlalchemy import delete, distinct, select, update
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import (
    Detection,
    DetectionIndividual,
    Estate,
    Image,
    Individual,
    Species,
)

log = get_logger(__name__)

# Cosine; tight by design. Below ~0.94 a species collapses into one false blob, so
# we only auto-group near-duplicate frames and let the user merge upward from there.
DEFAULT_THRESHOLD = 0.94


def embed_detections(db: Session, *, limit: int = 5000) -> int:
    """Compute + store the 1024-dim embedding for detections that lack one."""
    from app.ai.classifier import embed_crop

    rows = db.execute(
        select(Detection.id, Image.original_path, Detection.bbox)
        .join(Image, Detection.image_id == Image.id)
        .where(Detection.embedding.is_(None), Image.original_path.isnot(None))
        .limit(limit)
    ).all()
    done = 0
    for det_id, path, bbox in rows:
        try:
            xyxy = bbox.get("xyxy") if isinstance(bbox, dict) else None
            emb = embed_crop(path, xyxy)
            db.execute(update(Detection).where(Detection.id == det_id).values(embedding=emb))
            done += 1
            if done % 25 == 0:
                db.commit()
                log.info("reid.embed_progress", done=done, total=len(rows))
        except Exception as e:  # missing file / decode error — skip, keep going
            log.warning("reid.embed_failed", detection=str(det_id), error=str(e))
    db.commit()
    log.info("reid.embedded", count=done)
    return done


def _estate_id(db: Session) -> uuid.UUID | None:
    return db.scalar(select(Estate.id).limit(1))


def cluster(db: Session, *, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Greedy cosine clustering per species → candidate individuals.

    Preserves user-confirmed individuals and lets new detections attach to them.
    """
    import numpy as np

    estate_id = _estate_id(db)

    # Individuals the user has touched (≥1 confirmed sighting) are ground truth — keep them.
    confirmed_ids = set(
        db.scalars(
            select(distinct(DetectionIndividual.individual_id)).where(
                DetectionIndividual.confirmed_by_user.is_(True)
            )
        ).all()
    )

    # Drop every unconfirmed candidate + its links; we rebuild those from scratch.
    if confirmed_ids:
        db.execute(
            delete(DetectionIndividual).where(
                DetectionIndividual.individual_id.notin_(confirmed_ids)
            )
        )
        db.execute(delete(Individual).where(Individual.id.notin_(confirmed_ids)))
    else:
        db.execute(delete(DetectionIndividual))
        db.execute(delete(Individual))
    db.flush()

    # Detections already locked into a confirmed individual are excluded from re-clustering.
    locked = set(db.scalars(select(DetectionIndividual.detection_id)).all())

    # Seed centroids from confirmed individuals so new sightings can join a known animal.
    seeds: dict[str, list[dict]] = {}
    for ind_id in confirmed_ids:
        ind = db.get(Individual, ind_id)
        embs = db.scalars(
            select(Detection.embedding)
            .join(DetectionIndividual, DetectionIndividual.detection_id == Detection.id)
            .where(
                DetectionIndividual.individual_id == ind_id,
                Detection.embedding.isnot(None),
            )
        ).all()
        if not embs:
            continue
        vecs = np.asarray([list(e) for e in embs], dtype=np.float32)
        seeds.setdefault(ind.species_id, []).append(
            {"sum": vecs.sum(axis=0), "members": [], "individual_id": ind_id}
        )

    # All embeddable detections not already locked, ordered for stable "first seen".
    rows = db.execute(
        select(
            Detection.id,
            Detection.species_id,
            Detection.species_conf,
            Detection.embedding,
            Image.captured_at,
        )
        .join(Image, Detection.image_id == Image.id)
        .where(Detection.embedding.isnot(None))
        .order_by(Detection.species_id, Image.captured_at)
    ).all()

    by_species: dict[str, list] = {}
    for r in rows:
        if r.id in locked or r.species_id is None:
            continue
        by_species.setdefault(r.species_id, []).append(r)

    new_individuals = 0
    attached_to_confirmed = 0
    for species_id, items in by_species.items():
        clusters = [dict(s) for s in seeds.get(species_id, [])]  # start from confirmed centroids
        n_seeds = len(clusters)
        for r in items:
            v = np.asarray(list(r.embedding), dtype=np.float32)
            best_i, best_s = -1, -1.0
            for ci, c in enumerate(clusters):
                centroid = c["sum"] / (np.linalg.norm(c["sum"]) + 1e-8)
                s = float(centroid @ v)
                if s > best_s:
                    best_s, best_i = s, ci
            if best_i >= 0 and best_s >= threshold:
                clusters[best_i]["sum"] = clusters[best_i]["sum"] + v
                clusters[best_i]["members"].append((r, best_s))
            else:
                clusters.append({"sum": v.copy(), "members": [(r, 1.0)], "individual_id": None})

        sp = db.get(Species, species_id)
        sp_name = sp.common_name if sp else species_id
        # Number the *new* candidate clusters by size (largest = #1) for readable labels.
        fresh = sorted(
            (c for c in clusters if c["individual_id"] is None and c["members"]),
            key=lambda c: len(c["members"]),
            reverse=True,
        )
        for n, c in enumerate(fresh, 1):
            times = [m[0].captured_at for m in c["members"]]
            ind = Individual(
                estate_id=estate_id,
                label=f"{sp_name} #{n}",
                species_id=species_id,
                first_seen=min(times),
                last_seen=max(times),
                status="active",
            )
            db.add(ind)
            db.flush()
            for row, sim in c["members"]:
                db.add(
                    DetectionIndividual(
                        detection_id=row.id,
                        individual_id=ind.id,
                        match_conf=round(float(sim), 4),
                        confirmed_by_user=False,
                    )
                )
            new_individuals += 1

        # New sightings that joined a confirmed (seed) individual.
        for c in clusters[:n_seeds]:
            for row, sim in c["members"]:
                db.add(
                    DetectionIndividual(
                        detection_id=row.id,
                        individual_id=c["individual_id"],
                        match_conf=round(float(sim), 4),
                        confirmed_by_user=False,
                    )
                )
                attached_to_confirmed += 1
        db.commit()

    result = {
        "individuals": new_individuals + len(confirmed_ids),
        "new_candidates": new_individuals,
        "confirmed_kept": len(confirmed_ids),
        "attached_to_confirmed": attached_to_confirmed,
        "threshold": threshold,
    }
    log.info("reid.clustered", **result)
    return result


def recompute(db: Session, *, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Full re-ID pass: embed any new detections, then (re)cluster into individuals."""
    embedded = embed_detections(db)
    out = cluster(db, threshold=threshold)
    out["embedded"] = embedded
    return out
