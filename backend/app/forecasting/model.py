"""Tonight forecast — an honest, data-grounded recommendation per camera/species.

With ~1 season of data this is deliberately a transparent statistical model
(historical presence rate + recency + darkness), not a fragile ML net. It says
how sure it is and why, and never claims certainty. The factors feed the card's
"why" expander. A calibrated GBT can replace this once many more nights exist.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, cast, extract, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.enrichment.astro import moon_phase, solar
from app.enrichment.weather import weather_at
from app.models import Camera, Detection, Image, Species

_TZ = settings.estate_timezone


def _local_hour(col):
    return cast(extract("hour", func.timezone(_TZ, col)), Integer)


def _best_window(by_hour: dict[int, int]) -> dict:
    total = sum(by_hour.values()) or 1
    best_start, best_sum = 0, -1
    for start in range(24):
        block = sum(by_hour.get((start + d) % 24, 0) for d in range(3))
        if block > best_sum:
            best_start, best_sum = start, block
    return {"start_hour": best_start, "end_hour": (best_start + 3) % 24,
            "share_pct": round(best_sum / total * 100)}


def _verdict(prob: float) -> str:
    if prob >= 0.5:
        return "GO"
    if prob >= 0.2:
        return "MARGINAL"
    return "SKIP"


def _is_nocturnal(window: dict) -> bool:
    h = window["start_hour"]
    return h >= 20 or h <= 5


def _camera_forecast(db: Session, cam: Camera, total_nights: int, now: datetime) -> dict | None:
    rows = db.execute(
        select(
            Detection.species_id,
            Species.common_name,
            func.count(Detection.id),
            func.count(func.distinct(func.date(func.timezone(_TZ, Image.captured_at)))),
        )
        .join(Image, Image.id == Detection.image_id)
        .join(Species, Species.id == Detection.species_id)
        .where(Image.camera_id == cam.id)
        .group_by(Detection.species_id, Species.common_name)
        .order_by(func.count(Detection.id).desc())
    ).all()
    if not rows:
        return None

    species_id, sp_name, count, nights_present = rows[0][0], rows[0][1], int(rows[0][2]), int(rows[0][3])
    runner_up = rows[1][1] if len(rows) > 1 else None
    presence = min(1.0, nights_present / total_nights)

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

    # Probability tonight: base presence rate, nudged by recent activity.
    prob = presence
    if recent_nights >= 4:
        prob = min(0.97, prob + 0.1)
    elif recent_nights == 0:
        prob = max(0.02, prob - 0.15)

    confidence = round(min(90, 30 + nights_present * 2))  # capped — never certain
    return {
        "camera": cam.name, "camera_id": str(cam.id),
        "species": sp_name, "species_id": species_id, "runner_up": runner_up,
        "probability": round(prob, 2), "presence": round(presence, 2),
        "nights_present": nights_present, "recent_nights": recent_nights,
        "best_window": window, "confidence": confidence,
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


def _expectations(db: Session, forecasts: list[dict]) -> list[dict]:
    """Per forecasted camera: which classes (stag/hind/sow+piglets/…) to expect there."""
    out = []
    for f in forecasts:
        rows = db.execute(
            select(
                Detection.species_id, Species.common_name, Detection.sex,
                Detection.group_type, func.count(Detection.id),
            )
            .join(Image, Image.id == Detection.image_id)
            .join(Species, Species.id == Detection.species_id)
            .where(Image.camera_id == f["camera_id"])
            .group_by(Detection.species_id, Species.common_name, Detection.sex, Detection.group_type)
        ).all()
        agg: dict[str, int] = {}
        for sp, cn, sex, gt, c in rows:
            agg[class_label(sp, cn, sex, gt)] = agg.get(class_label(sp, cn, sex, gt), 0) + int(c)
        classes = sorted(agg.items(), key=lambda kv: -kv[1])[:4]
        out.append({
            "camera": f["camera"], "camera_id": f["camera_id"],
            "verdict": _verdict(f["probability"]), "probability": f["probability"],
            "best_window": f["best_window"],
            "classes": [{"label": lbl, "count": n} for lbl, n in classes],
        })
    return out


def _tonight_conditions(now: datetime) -> dict:
    phase, illum = moon_phase(now)
    s = solar(settings.estate_lat, settings.estate_lon, now.date())
    wind_dir = wind_speed = temp = pressure = cloud = rain = None
    try:
        # `now` is UTC and containers set no TZ, so .astimezone() was a no-op: this
        # sampled 22:00 UTC, which is midnight the following day in Madrid. Anchor
        # explicitly to the estate's timezone instead of the process's.
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
    if top["recent_nights"] > 0:
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


def forecast_tonight(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    total_nights = db.scalar(
        select(func.count(func.distinct(func.date(func.timezone(_TZ, Image.captured_at)))))
    ) or 1

    cams = db.scalars(select(Camera).order_by(Camera.name)).all()
    forecasts = [f for f in (_camera_forecast(db, c, total_nights, now) for c in cams) if f]
    forecasts.sort(key=lambda f: f["probability"], reverse=True)

    cond = _tonight_conditions(now)
    if not forecasts:
        return {"verdict": "SKIP", "reason": "No animal data yet.", "nights_of_data": total_nights,
                "conditions": cond, "alternates": []}

    # Feed tonight's actual conditions back through the learned weather/moon drivers,
    # so the verdict reflects tonight — not just historical presence. Per species where
    # we have enough data, else the estate-wide drivers. Conservative + capped.
    from app.forecasting.patterns import driver_map, tonight_multiplier

    feats = {
        "moon_illum": cond.get("moon_illum"), "darkness": cond.get("darkness_minutes"),
        "temp": cond.get("temp_c"), "wind": cond.get("wind_speed_kmh"),
        "pressure": cond.get("pressure_hpa"), "cloud": cond.get("cloud_cover_pct"),
        "rain": cond.get("rain_mm"),
    }
    try:
        dmap = driver_map(db)
    except Exception:
        dmap = {}
    for f in forecasts:
        drivers = dmap.get(f["species_id"]) or dmap.get("all") or []
        mult, reasons = tonight_multiplier(drivers, feats)
        f["base_probability"] = f["probability"]
        f["probability"] = round(max(0.02, min(0.97, f["probability"] * mult)), 2)
        f["tonight_mult"] = round(mult, 2)
        f["condition_reasons"] = reasons
    forecasts.sort(key=lambda f: f["probability"], reverse=True)

    top = forecasts[0]
    where = _expectations(db, forecasts)
    top_classes = where[0]["classes"] if where else []
    return {
        "verdict": _verdict(top["probability"]),
        "confidence": top["confidence"],
        "recommended": {
            "camera": top["camera"], "species": top["species"], "runner_up": top["runner_up"],
            "probability": top["probability"], "best_window": top["best_window"],
            "expect": top_classes[0]["label"] if top_classes else top["species"],
            "classes": top_classes,
            "reason": f"{top['species']} seen {top['nights_present']} of {total_nights} nights here.",
        },
        "conditions": cond,
        "factors": _factors(top, cond) + top.get("condition_reasons", []),
        "where": where,
        "alternates": [
            {"camera": f["camera"], "species": f["species"], "verdict": _verdict(f["probability"]),
             "probability": f["probability"]}
            for f in forecasts[1:3]
        ],
        "nights_of_data": total_nights,
    }
