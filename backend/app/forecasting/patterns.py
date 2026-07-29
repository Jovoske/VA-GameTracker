"""Behaviour-pattern analysis — activity vs weather & moon, estate-wide and per species.

Builds a per-night series over the WHOLE data range (every night, including quiet ones),
backtracks that night's overnight weather from Open-Meteo in one bulk call, pairs it with
the moon and the night's sightings, then reports the environmental drivers that move
activity — each with its sample size and a confidence that grows as more nights accumulate.

It's a running calculation: every recompute uses all data to date (cached per day so the
page stays fast), so the patterns sharpen over the season. Nothing is asserted beyond what
the sample supports — weak/!small-sample signals are filtered out, and confidence is shown.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.enrichment.astro import moon_phase, solar
from app.models import Detection, Image

log = get_logger(__name__)
_TZ = settings.estate_timezone
_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
_FORECAST = "https://api.open-meteo.com/v1/forecast"
_HOURLY = "temperature_2m,surface_pressure,wind_speed_10m,precipitation,cloud_cover"
_WCACHE: dict = {}

MIN_NIGHTS = 10          # don't call a pattern below this many usable nights
MIN_EFFECT = 15.0        # %; ignore drivers weaker than this
SCOPES = [("all", "All animals"), ("wild_boar", "Wild boar"), ("red_deer", "Red deer")]

# key, label, description-when-high, description-when-low
_VARS = [
    ("moon_illum", "Moonlight", "bright, moonlit nights", "dark nights"),
    ("pressure", "Pressure", "high pressure (settled)", "low pressure (unsettled)"),
    ("pressure_trend", "Pressure trend", "rising pressure", "falling pressure"),
    ("temp", "Temperature", "warmer nights", "cooler nights"),
    ("wind", "Wind", "windier nights", "calm nights"),
    ("rain", "Rain", "wetter nights", "drier nights"),
    ("cloud", "Cloud cover", "overcast skies", "clear skies"),
    ("darkness", "Dark hours", "longer-dark nights", "shorter-dark nights"),
]


def _at(h: dict, field: str, i: int):
    arr = h.get(field) or []
    return arr[i] if i < len(arr) else None


def _overnight_weather(lat: float, lon: float, start: date, end: date) -> dict[str, dict]:
    """{iso_date: {temp,pressure,wind,rain,cloud}} overnight (18:00–06:00) means, one/two calls."""
    key = (round(lat, 3), round(lon, 3), start.isoformat(), end.isoformat())
    if key in _WCACHE:
        return _WCACHE[key]
    hours: dict[str, dict] = {}
    today = datetime.now(timezone.utc).date()
    segments = []
    arch_end = min(end, today - timedelta(days=5))
    if start <= arch_end:
        segments.append((_ARCHIVE, start, arch_end))
    fc_start = max(start, today - timedelta(days=6))
    if fc_start <= end:
        segments.append((_FORECAST, fc_start, end))
    for url, s, e in segments:
        try:
            r = httpx.get(url, params={
                "latitude": lat, "longitude": lon, "hourly": _HOURLY, "timezone": _TZ,
                "start_date": s.isoformat(), "end_date": e.isoformat(),
            }, timeout=30)
            r.raise_for_status()
            h = r.json().get("hourly", {})
        except Exception as ex:
            log.warning("patterns.weather_failed", error=str(ex))
            continue
        for i, t in enumerate(h.get("time", [])):
            hours[t] = {
                "temp": _at(h, "temperature_2m", i), "pressure": _at(h, "surface_pressure", i),
                "wind": _at(h, "wind_speed_10m", i), "rain": _at(h, "precipitation", i),
                "cloud": _at(h, "cloud_cover", i),
            }
    nights: dict[str, dict] = {}
    cur = start
    while cur <= end:
        acc = {"temp": [], "pressure": [], "wind": [], "rain": [], "cloud": []}
        for hh in list(range(18, 24)) + list(range(0, 7)):
            d = cur if hh >= 18 else cur + timedelta(days=1)
            rec = hours.get(f"{d.isoformat()}T{hh:02d}:00")
            if rec:
                for k in acc:
                    if rec[k] is not None:
                        acc[k].append(rec[k])
        night = {k: (sum(v) / len(v) if v else None) for k, v in acc.items()}
        if acc["rain"]:
            night["rain"] = round(sum(acc["rain"]), 2)  # rain accumulates, not averages
        nights[cur.isoformat()] = night
        cur += timedelta(days=1)
    if len(_WCACHE) > 64:
        _WCACHE.clear()
    _WCACHE[key] = nights
    return nights


def _nightly_activity(db: Session) -> tuple[list[str], dict]:
    # A "night" runs 18:00 -> 06:00, and _overnight_weather keys it by the EVENING
    # date. Bucketing detections by calendar date instead put everything after
    # midnight -- the bulk of nocturnal activity -- against the *following* night's
    # weather. Shifting back 6h before taking the date puts both on the same key.
    night = func.date(func.timezone(_TZ, Image.captured_at) - text("interval '6 hours'"))
    lo, hi = db.execute(select(func.min(night), func.max(night))).one()
    if lo is None:
        return [], {}
    rows = db.execute(
        select(night, Detection.species_id, func.count(Detection.id))
        .join(Image, Image.id == Detection.image_id)
        .group_by(night, Detection.species_id)
    ).all()
    counts: dict[str, dict[str, int]] = {}
    for d, sp, c in rows:
        ds = d.isoformat()
        bucket = counts.setdefault(ds, {})
        bucket["all"] = bucket.get("all", 0) + int(c)
        if sp:
            bucket[sp] = bucket.get(sp, 0) + int(c)
    dates, cur = [], lo
    while cur <= hi:
        dates.append(cur.isoformat())
        cur += timedelta(days=1)
    return dates, counts


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return 0.0
    return sxy / math.sqrt(sxx * syy)


def _mean(v: list[float]) -> float:
    return sum(v) / len(v) if v else 0.0


def _driver(key: str, label: str, hi_desc: str, lo_desc: str, pairs: list[tuple[float, float]]) -> dict | None:
    """pairs = [(variable_value, sightings_that_night)] over usable nights."""
    if len(pairs) < MIN_NIGHTS:
        return None
    pairs = sorted(pairs, key=lambda p: p[0])
    n = len(pairs)
    k = max(1, n // 3)
    lo_rate = _mean([c for _, c in pairs[:k]])
    mid_rate = _mean([c for _, c in pairs[k:n - k]]) if n - 2 * k > 0 else _mean([c for _, c in pairs[k:n - k or None]])
    hi_rate = _mean([c for _, c in pairs[-k:]])
    overall = _mean([c for _, c in pairs]) or 1.0
    r = _pearson([v for v, _ in pairs], [c for _, c in pairs])
    if hi_rate >= lo_rate:
        desc, base, peak = hi_desc, lo_rate, hi_rate
    else:
        desc, base, peak = lo_desc, hi_rate, lo_rate
    effect = (peak - base) / overall * 100.0
    if effect < MIN_EFFECT:
        return None
    confidence = round(min(0.85, min(1.0, n / 45) * min(1.0, abs(r) * 1.6)), 2)
    if confidence < 0.15:
        return None
    return {
        "factor": label,
        "statement": f"~{round(effect)}% more activity on {desc}.",
        "effect_pct": round(effect),
        "favours": desc,
        "sample_nights": n,
        "confidence": confidence,
        "buckets": [
            {"label": "low", "rate": round(lo_rate, 1)},
            {"label": "mid", "rate": round(mid_rate, 1)},
            {"label": "high", "rate": round(hi_rate, 1)},
        ],
        "correlation": round(r, 2),
        # for feeding tonight's conditions back into the forecast:
        "key": key,
        "favours_high": hi_rate >= lo_rate,
        "split": round(pairs[n // 2][0], 2),
    }


def _scope_drivers(dates: list[str], counts: dict, weather: dict, moon: dict, scope: str) -> dict:
    # assemble per-night feature rows
    series = []
    prev_pressure = None
    for ds in dates:
        w = weather.get(ds, {})
        m = moon.get(ds, {})
        pressure = w.get("pressure")
        trend = (pressure - prev_pressure) if (pressure is not None and prev_pressure is not None) else None
        prev_pressure = pressure if pressure is not None else prev_pressure
        series.append({
            "count": counts.get(ds, {}).get(scope, 0),
            "moon_illum": m.get("illum"), "darkness": m.get("darkness"),
            "temp": w.get("temp"), "pressure": pressure, "pressure_trend": trend,
            "wind": w.get("wind"), "rain": w.get("rain"), "cloud": w.get("cloud"),
        })
    drivers = []
    for key, label, hi_desc, lo_desc in _VARS:
        pairs = [(row[key], row["count"]) for row in series if row.get(key) is not None]
        d = _driver(key, label, hi_desc, lo_desc, pairs)
        if d:
            drivers.append(d)
    drivers.sort(key=lambda d: d["effect_pct"] * d["confidence"], reverse=True)
    active = sum(1 for row in series if row["count"] > 0)
    total_sightings = sum(row["count"] for row in series)
    return {
        "drivers": drivers[:6],
        "active_nights": active,
        "total_nights": len(series),
        "avg_per_night": round(total_sightings / len(series), 1) if series else 0,
        "sightings": total_sightings,
    }


def compute_patterns(db: Session) -> dict:
    dates, counts = _nightly_activity(db)
    if not dates:
        return {"scopes": [], "nights": 0}
    start, end = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    weather = _overnight_weather(settings.estate_lat, settings.estate_lon, start, end)
    moon: dict[str, dict] = {}
    for ds in dates:
        d = date.fromisoformat(ds)
        night_dt = datetime(d.year, d.month, d.day, 23, tzinfo=timezone.utc)
        _, illum = moon_phase(night_dt)
        moon[ds] = {"illum": illum, "darkness": solar(settings.estate_lat, settings.estate_lon, d).get("darkness_minutes")}

    scopes = []
    for key, label in SCOPES:
        s = _scope_drivers(dates, counts, weather, moon, key)
        s["key"], s["label"] = key, label
        if s["sightings"] >= MIN_NIGHTS:  # only show a scope with enough sightings to mean anything
            scopes.append(s)
    log.info("patterns.computed", nights=len(dates), scopes=len(scopes))
    return {"scopes": scopes, "nights": len(dates), "range": [dates[0], dates[-1]]}


def driver_map(db: Session) -> dict[str, list]:
    """{scope_key: drivers} — for feeding tonight's conditions back into the forecast."""
    return {s["key"]: s["drivers"] for s in compute_patterns(db).get("scopes", [])}


def tonight_multiplier(drivers: list[dict], feats: dict) -> tuple[float, list[dict]]:
    """How tonight's actual conditions nudge activity, per the learned drivers.

    Deliberately conservative: each driver moves the odds by only half its historical
    effect, further scaled by its confidence, and the total is clamped — conditions
    tilt the verdict, they don't dominate it.
    """
    mult = 1.0
    reasons: list[dict] = []
    for d in drivers:
        if d.get("confidence", 0) < 0.25 or d.get("key") not in feats:
            continue
        val = feats.get(d["key"])
        if val is None:
            continue
        favourable = (val >= d["split"]) == d["favours_high"]
        weight = (d["effect_pct"] / 100.0) * d["confidence"] * 0.5
        if favourable:
            mult *= 1 + weight
            reasons.append({"text": f"Tonight favours it — {d['favours']}", "impact": "++" if weight > 0.12 else "+"})
        else:
            mult *= 1 - weight
            reasons.append({"text": f"Tonight's {d['factor'].lower()} works against it", "impact": "-"})
        if len(reasons) >= 4:
            break
    return max(0.6, min(1.5, mult)), reasons
