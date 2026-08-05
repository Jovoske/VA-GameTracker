"""Tonight forecast — an honest, data-grounded recommendation per camera/species.

With ~1 season of data this is deliberately a transparent statistical model
(historical presence rate + recency + darkness), not a fragile ML net. It says
how sure it is and why, and never claims certainty. The factors feed the card's
"why" expander. A calibrated GBT can replace this once many more nights exist.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, cast, extract, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.enrichment.astro import moon_phase, solar
from app.enrichment.weather import weather_at
from app.forecasting.changes import whats_changed
from app.forecasting.exposure import excluded_nights
from app.forecasting.scoring import calibration
from app.forecasting.wind import assess
from app.models import Camera, Detection, Image, Species, Stand

log = get_logger(__name__)

_TZ = settings.estate_timezone


def _local_hour(col):
    return cast(extract("hour", func.timezone(_TZ, col)), Integer)


# Hours a person can realistically sit an evening stand. Searching all 24 returned
# windows like 03:00-06:00: genuinely where camera activity peaked, and genuinely
# useless as a recommendation, because nobody is sitting then. The constraint is
# what a hunter can do, not what the sensor saw.
SITTABLE_HOURS = tuple(range(16, 24)) + (0, 1)


def _best_window(by_hour: dict[int, int], *, sittable_only: bool = True) -> dict:
    """Best 3-hour block, restricted to hours somebody could actually be there."""
    total = sum(by_hour.values()) or 1
    starts = SITTABLE_HOURS if sittable_only else tuple(range(24))
    best_start, best_sum = starts[0], -1
    for start in starts:
        block = sum(by_hour.get((start + d) % 24, 0) for d in range(3))
        if block > best_sum:
            best_start, best_sum = start, block
    return {"start_hour": best_start, "end_hour": (best_start + 3) % 24,
            "share_pct": round(best_sum / total * 100)}


MIN_NIGHTS_TO_JUDGE = 15


def _verdict(prob: float, active_nights: int | None = None) -> str:
    """Describe the ground, don't instruct the hunter.

    GO/MARGINAL/SKIP read as commands, which turns every blank evening into a broken
    promise and hands the hunter someone to blame. These labels state what the camera
    has seen and leave the decision where it belongs.

    NO_DATA is a distinct state, not a bad one: a camera with too few watched nights
    is a hardware report, and calling that "QUIET" claims knowledge of the ground we
    do not have. Note this keys on nights WATCHED, so a camera that is merely out of
    photo credits keeps its historical ranking rather than disappearing.
    """
    if active_nights is not None and active_nights < MIN_NIGHTS_TO_JUDGE:
        return "NO_DATA"
    if prob >= 0.5:
        return "BEST_ODDS"
    if prob >= 0.2:
        return "WORTH_A_LOOK"
    return "QUIET"


def _is_nocturnal(window: dict) -> bool:
    h = window["start_hour"]
    return h >= 20 or h <= 5


def _camera_forecast(
    db: Session, cam: Camera, now: datetime, *, producing: bool = True,
    species_ids: list[str] | None = None,
) -> dict | None:
    """Best huntable species at this camera tonight.

    `species_ids` narrows it to what the hunter is actually after: asking for boar
    should rank the ground by boar, not by whatever happens to be commonest there.
    """
    q = (
        select(
            Detection.species_id,
            Species.common_name,
            func.count(Detection.id),
            func.count(func.distinct(func.date(func.timezone(_TZ, Image.captured_at)))),
        )
        .join(Image, Image.id == Detection.image_id)
        .join(Species, Species.id == Detection.species_id)
        .where(Image.camera_id == cam.id, Species.huntable.is_(True))
    )
    if species_ids:
        q = q.where(Detection.species_id.in_(species_ids))
    rows = db.execute(
        q.group_by(Detection.species_id, Species.common_name)
        .order_by(func.count(Detection.id).desc())
    ).all()
    if not rows:
        return None

    species_id, sp_name, count, nights_present = rows[0][0], rows[0][1], int(rows[0][2]), int(rows[0][3])
    runner_up = rows[1][1] if len(rows) > 1 else None
    # Denominator is the nights THIS camera was actually watching — not the whole estate's
    # date range — so a recently-installed or briefly-active camera isn't scored near zero.
    active_nights = db.scalar(
        select(func.count(func.distinct(func.date(func.timezone(_TZ, Image.captured_at)))))
        .where(Image.camera_id == cam.id)
    ) or nights_present or 1
    presence = min(1.0, nights_present / active_nights)

    recent_nights = db.scalar(
        select(func.count(func.distinct(func.date(func.timezone(_TZ, Image.captured_at)))))
        .select_from(Detection)
        .join(Image, Image.id == Detection.image_id)
        .where(
            Image.camera_id == cam.id,
            Detection.species_id == species_id,
            Image.captured_at > now - timedelta(days=7),
        )
    ) or 0

    hour_expr = _local_hour(Image.captured_at).label("h")
    hour_rows = db.execute(
        select(hour_expr, func.count())
        .select_from(Detection)
        .join(Image, Image.id == Detection.image_id)
        .where(Image.camera_id == cam.id, Detection.species_id == species_id)
        .group_by(hour_expr)
    ).all()
    by_hour = {int(h): int(c) for h, c in hour_rows}
    window = _best_window(by_hour)

    # Probability tonight: base presence rate, nudged by recent activity — but only when the
    # camera is actually producing. A camera that's out of credits / offline has no fresh
    # photos, so we must NOT read that silence as absence; keep it on historical presence.
    prob = presence
    if producing:
        if recent_nights >= 4:
            prob = min(0.97, prob + 0.1)
        elif recent_nights == 0:
            prob = max(0.02, prob - 0.15)

    return {
        "camera": cam.name, "camera_id": str(cam.id),
        "species": sp_name, "species_id": species_id, "runner_up": runner_up,
        "probability": round(prob, 2), "presence": round(presence, 2),
        "nights_present": nights_present, "recent_nights": recent_nights,
        "active_nights": active_nights, "producing": producing,
        "best_window": window,
        "nocturnal": _is_nocturnal(window),
    }


def class_label(species_id: str | None, common_name: str | None, sex: str | None, group_type: str | None) -> str:
    """Human class from species + sex + group composition (mirrors the gallery chip)."""
    if species_id == "red_deer":
        if group_type == "hind_with_calf":
            return "Hind + calf"
        if sex == "male":
            return "Stag"
        if sex == "female":
            return "Hind"
        return "Red deer (herd)" if group_type == "herd" else "Red deer"
    if species_id == "wild_boar":
        if group_type == "sow_with_piglets":
            return "Sow + piglets"
        if sex == "male":
            return "Boar"
        if sex == "female":
            return "Sow"
        return "Sounder" if group_type == "sounder" else "Wild boar"
    return common_name or (species_id or "Animal")


def _expectations(
    db: Session, forecasts: list[dict], species_ids: list[str] | None = None
) -> list[dict]:
    """Per forecasted camera: which classes (stag/hind/sow+piglets/…) to expect there."""
    out = []
    for f in forecasts:
        q = (
            select(
                Detection.species_id, Species.common_name, Detection.sex,
                Detection.group_type, func.count(Detection.id),
            )
            .join(Image, Image.id == Detection.image_id)
            .join(Species, Species.id == Detection.species_id)
            .where(Image.camera_id == f["camera_id"], Species.huntable.is_(True))
        )
        if species_ids:
            # Asked for boar, be shown boar: listing every class at the stand would
            # bury the thing the hunter came for.
            q = q.where(Detection.species_id.in_(species_ids))
        rows = db.execute(
            q.group_by(
                Detection.species_id, Species.common_name, Detection.sex, Detection.group_type
            )
        ).all()
        agg: dict[str, int] = {}
        for sp, cn, sex, gt, c in rows:
            agg[class_label(sp, cn, sex, gt)] = agg.get(class_label(sp, cn, sex, gt), 0) + int(c)
        classes = sorted(agg.items(), key=lambda kv: -kv[1])[:4]
        out.append({
            "camera": f["camera"], "camera_id": f["camera_id"],
            "species_id": f["species_id"],  # needed to score the claim later
            "verdict": _verdict(f["probability"], f["active_nights"]),
            "probability": f["probability"],
            "nights_present": f["nights_present"], "active_nights": f["active_nights"],
            "best_window": f["best_window"],
            "classes": [{"label": lbl, "count": n} for lbl, n in classes],
        })
    return out


def _tonight_conditions(now: datetime) -> dict:
    phase, illum = moon_phase(now)
    s = solar(settings.estate_lat, settings.estate_lon, now.date())
    wind_dir = wind_speed = temp = pressure = cloud = rain = None
    try:
        # `now` is UTC and the service sets no TZ, so .astimezone() was a no-op:
        # this sampled 22:00 UTC, which is midnight the following day in Madrid.
        local_22 = now.astimezone(ZoneInfo(_TZ)).replace(
            hour=22, minute=0, second=0, microsecond=0
        )
        w = weather_at(settings.estate_lat, settings.estate_lon, local_22, tz=_TZ)
        wind_dir, wind_speed, temp = w.get("wind_dir_deg"), w.get("wind_speed_kmh"), w.get("temp_c")
        pressure, cloud, rain = w.get("pressure_hpa"), w.get("cloud_cover_pct"), w.get("rain_mm")
    except Exception:
        pass
    return {
        "moon_phase": phase, "moon_illum": illum,
        "darkness_minutes": s.get("darkness_minutes"),
        "wind_dir_deg": wind_dir, "wind_speed_kmh": wind_speed, "temp_c": temp,
        "pressure_hpa": pressure, "cloud_cover_pct": cloud, "rain_mm": rain,
    }


def _factors(top: dict, cond: dict) -> list[dict]:
    out = []
    if not top.get("producing", True):
        out.append({
            "text": f"Camera not sending fresh photos — going on {top['nights_present']} nights of history",
            "impact": "•",
        })
    elif top["recent_nights"] > 0:
        out.append({
            "text": f"{top['species']} seen {top['recent_nights']} of the last 7 nights here",
            "impact": "+++" if top["recent_nights"] >= 4 else "++",
        })
    else:
        out.append({"text": f"No {top['species']} here in the last 7 nights", "impact": "--"})
    # Moon/weather are handled by the data-driven tonight drivers (condition_reasons),
    # so they're not hardcoded here — keeps the "why" consistent with the learned patterns.
    w = top["best_window"]
    out.append({"text": f"Peak window {w['start_hour']:02d}:00–{w['end_hour']:02d}:00", "impact": "++"})
    return out


def forecast_tonight(db: Session, species_ids: list[str] | None = None) -> dict:
    now = datetime.now(timezone.utc)
    total_nights = db.scalar(
        select(func.count(func.distinct(func.date(func.timezone(_TZ, Image.captured_at)))))
    ) or 1

    # A camera that isn't producing data (dead battery / no check-in / out of photo credits)
    # must not have its silence scored as "no animals". We keep it in the ranking on its
    # HISTORICAL presence (skipping the recent-activity penalty) and also surface it as an
    # alert — so a strong spot whose camera is merely capped isn't hidden or downgraded.
    from app.health import camera_health

    cams = db.scalars(select(Camera).order_by(Camera.name)).all()
    health = {c.id: camera_health(c, now) for c in cams}
    alerts = [
        {"camera": c.name, "status": health[c.id]["status"], "detail": health[c.id]["detail"]}
        for c in cams if not health[c.id]["producing"]
    ]
    forecasts = [
        f for f in (
            _camera_forecast(db, c, now, producing=health[c.id]["producing"],
                             species_ids=species_ids)
            for c in cams
        ) if f
    ]
    forecasts.sort(key=lambda f: f["probability"], reverse=True)

    cond = _tonight_conditions(now)
    if not forecasts:
        if species_ids:
            reason = "None of the selected species has been recorded on a reporting camera."
        else:
            reason = "No animal data from reporting cameras." if alerts else "No animal data yet."
        # NO_DATA, not SKIP: we have nothing to say about the ground, which is not the
        # same as telling somebody their evening isn't worth having.
        return {"verdict": "NO_DATA", "reason": reason, "nights_of_data": total_nights,
                "conditions": cond, "alternates": [], "alerts": alerts}

    # The learned weather/moon "drivers" used to be multiplied into this number.
    # They were removed after a null simulation run against the real _driver() code:
    # on counts generated to be independent of every covariate, it still found at
    # least one "driver" in 97.8-99.8% of runs, at a median reported effect of
    # 46-108% against an advertised MIN_EFFECT floor of 15. Those coefficients were
    # moving the headline verdict. Tonight's conditions are still shown as facts;
    # they no longer silently move the ranking.
    forecasts.sort(key=lambda f: f["probability"], reverse=True)

    top = forecasts[0]
    where = _expectations(db, forecasts, species_ids)
    top_classes = where[0]["classes"] if where else []

    # One line of news beats a wall of unchanged numbers. A hunter who opened the app
    # yesterday needs to know what moved, not to re-read what didn't.
    try:
        changed = whats_changed(db)
    except Exception as e:  # never let the extra line break the verdict
        log.warning("changed.failed", error=str(e))
        changed = {"kind": "none", "camera": None, "text": ""}

    # Wind is deterministic geometry against the stand linked to the top camera — not a
    # fitted coefficient. It states its own competence boundary rather than producing a
    # confident bearing on a calm night that a single weather grid point cannot see.
    stand = db.scalar(select(Stand).where(Stand.camera_id == uuid.UUID(top["camera_id"])))
    alt = forecasts[1]["camera"] if len(forecasts) > 1 else None
    wind_verdict = assess(
        stand_name=stand.name if stand else top["camera"],
        wind_dir_deg=cond.get("wind_dir_deg"),
        wind_speed_kmh=cond.get("wind_speed_kmh"),
        approach_dirs_deg=stand.approach_dirs_deg if stand else None,
        alternative_stand=alt,
    )

    # The honest replacement for the deleted confidence figure: not how much data went
    # in, but how often this model has actually been right when it was checked.
    try:
        track_record = calibration(db)
    except Exception as e:
        log.warning("calibration.failed", error=str(e))
        track_record = {"available": False, "n_evaluated": 0}

    # Nights deliberately not counted — camera down, out of credits, or frames the
    # classifier has not reached. The whole point of the exposure table is that these
    # are excluded rather than silently averaged in as "no animals", and an exclusion
    # nobody is told about is indistinguishable from the bug it replaced.
    try:
        skipped = excluded_nights(db)
    except Exception as e:
        log.warning("exposure.count_failed", error=str(e))
        skipped = 0

    return {
        "exposure": {
            "excluded_nights": skipped,
            "note": (
                f"{skipped} night{'s' if skipped != 1 else ''} left out — the cameras "
                "could not vouch for them, so they are not counted either way."
            ) if skipped else "",
        },
        "verdict": _verdict(top["probability"], top["active_nights"]),
        "changed": changed,
        "calibration": track_record,
        "wind": {
            "status": wind_verdict.status,
            "text": wind_verdict.text,
            "is_advice": wind_verdict.is_advice,
        },
        "recommended": {
            "camera": top["camera"], "species": top["species"], "runner_up": top["runner_up"],
            "probability": top["probability"], "best_window": top["best_window"],
            "expect": top_classes[0]["label"] if top_classes else top["species"],
            "classes": top_classes,
            "nights_present": top["nights_present"], "active_nights": top["active_nights"],
            "reason": (
                f"{top['species']} seen on {top['nights_present']} of "
                f"{top['active_nights']} nights this camera was watching."
            ),
            # The reference class belongs in the sentence, not a footnote: a bare
            # percentage reads as "my chance of a shot tonight", which is not what
            # was measured.
            "caveat": (
                "That is what the camera sees over a whole night. You'll be there "
                "for part of it, and the wind is yours to solve."
            ),
        },
        "conditions": cond,
        "factors": _factors(top, cond),
        "where": where,
        "alternates": [
            {"camera": f["camera"], "species": f["species"],
             "verdict": _verdict(f["probability"], f["active_nights"]),
             "nights_present": f["nights_present"], "active_nights": f["active_nights"]}
            for f in forecasts[1:3]
        ],
        "alerts": alerts,
        "nights_of_data": total_nights,
    }
