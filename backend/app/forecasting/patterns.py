"""Behaviour-pattern analysis — activity vs weather & moon, estate-wide and per species.

The series is built from the nights the cameras were demonstrably watching (the
exposure table: CONFIRMED or PRESUMED_UP), one number per night: visits per watching
camera. A night no camera could vouch for (flat battery, out of photo credits, photos
not checked yet) is left out, never counted as a quiet night, and the count is of
visits, not photos, of species nobody hid. That night's overnight weather comes from
Open-Meteo in one bulk call, paired with the moon.

Then the honest part. Splitting the nights into thirds by each of eight conditions
and comparing the busiest third with the quietest finds a "pattern" in almost every
season of pure noise (86-99% of simulated runs, audit G-04). So nothing is stated as
a finding unless it beats a shuffle test: the same nights' counts reshuffled in
week-long blocks SHUFFLES times, the biggest difference any condition in any scope
shows each time noted, and a condition only "stands out" when its real difference
is bigger than 95% of those. What is tested is a condition's high end against its
low end, never its middle bar, on each night's count less the level of the moon
cycle around it, so a season that drifts (the boar building up on the acorns while
the nights lengthen and cool) is not a finding either. That keeps the chance of one
false finding on the page near 1 in 20, not near certain. The bars are always there
behind the fold, marked for what they are.
"""
from __future__ import annotations

import math
import random
import threading
import time
from bisect import bisect_left, bisect_right
from datetime import UTC, date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.enrichment.astro import moon_phase, solar
from app.forecasting.exposure import current_night, night_key_start, visits_by_night
from app.models import Camera, CameraNight

log = get_logger(__name__)
_TZ = settings.estate_timezone
_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
_FORECAST = "https://api.open-meteo.com/v1/forecast"
_HOURLY = "temperature_2m,surface_pressure,wind_speed_10m,precipitation,cloud_cover"
_WCACHE: dict = {}   # (lat, lon, first, last night) -> (nights, ask again after | None)
_KNOWN: dict = {}    # (lat, lon) -> {night: weather}: every night a fetch brought back
_REFRESHING: set = set()
_LOCK = threading.Lock()
# A weather fetch that failed is asked again after this, not after the next night of
# data arrives (audit G-20).
FAILED_WEATHER_TTL = timedelta(minutes=10)
# The longest a page waits on Open-Meteo, both calls together. A service that hangs
# rather than refusing held Insights for a minute, past the page's own 30 s.
WEATHER_BUDGET_S = 6.0
# A refresh nobody is waiting for may take as long as the service needs.
BACKGROUND_BUDGET_S = 60.0
_clock = time.monotonic

MIN_NIGHTS = 10          # don't compare below this many usable nights
MIN_SIDE = 5             # nights on each side of a dry-against-wet comparison
HISTORY_NIGHTS = 365     # the season, not every photo ever taken
SHUFFLES = 200           # how many reshuffled seasons the real one is compared with
SHUFFLE_BLOCK = 7        # nights moved together, so a busy week stays a busy week
CHANCE_LEVEL = 0.95      # a finding beats this share of the reshuffled seasons
LEVEL_DAYS = 14          # the level: nights this close either side, a moon cycle in all
SCOPES = [("all", "All animals"), ("wild_boar", "Wild boar"), ("red_deer", "Red deer")]
WATCHED = ("CONFIRMED", "PRESUMED_UP")

# key, label, description-when-high, description-when-low
_VARS = [
    ("moon_illum", "Moonlight", "a bright moon", "a dark moon"),
    ("pressure", "Pressure", "high pressure", "low pressure"),
    ("pressure_trend", "Pressure trend", "rising pressure", "falling pressure"),
    ("temp", "Temperature", "warm weather", "cool weather"),
    ("wind", "Wind", "wind", "still air"),
    ("rain", "Rain", "rain", "dry weather"),
    ("cloud", "Cloud cover", "cloud", "clear skies"),
    ("darkness", "Dark hours", "a long night", "a short night"),
]
_WEATHER_VARS = {"pressure", "pressure_trend", "temp", "wind", "rain", "cloud"}


def _at(h: dict, field: str, i: int):
    arr = h.get(field) or []
    return arr[i] if i < len(arr) else None


def _no_weather() -> dict:
    return {"temp": None, "pressure": None, "wind": None, "rain": None, "cloud": None}


def _has_weather(night: dict) -> bool:
    return any(v is not None for v in night.values())


def _overnight_weather(lat: float, lon: float, start: date, end: date) -> dict[str, dict]:
    """{iso_date: {temp,pressure,wind,rain,cloud}} overnight (18:00–06:00) means.

    Never a long wait: with any of these nights fetched before, they are served at
    once and the rest is asked for in the background, for the next visit. Only a
    visit with nothing known waits, for WEATHER_BUDGET_S at most, and what didn't
    come in that time is then asked for in the background too."""
    key = (round(lat, 3), round(lon, 3), start.isoformat(), end.isoformat())
    now = datetime.now(timezone.utc)
    hit = _WCACHE.get(key)
    if hit is not None and (hit[1] is None or now < hit[1]):
        return hit[0]
    known = _KNOWN.get(key[:2], {})
    nights = {ds: known.get(ds) or _no_weather() for ds in _dates(start, end)}
    if any(_has_weather(n) for n in nights.values()):
        _refresh_later(key, lat, lon, start, end)
        return nights
    nights = _fetch_weather(key, lat, lon, start, end, budget=WEATHER_BUDGET_S)
    if _WCACHE[key][1] is not None:
        # Not all of it came in time (a slow year of archive, say): the rest is
        # fetched behind this visit, without the rush, for the next.
        _refresh_later(key, lat, lon, start, end)
    return nights


def _dates(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def _refresh_later(key: tuple, lat: float, lon: float, start: date, end: date) -> None:
    """Fetch the weather for the next visit, once at a time, without holding this one."""
    with _LOCK:
        if key in _REFRESHING:
            return
        _REFRESHING.add(key)

    def run():
        try:
            _fetch_weather(key, lat, lon, start, end, budget=BACKGROUND_BUDGET_S)
        except Exception as ex:  # a refresh nobody waits for must not take the server down
            log.warning("patterns.weather_refresh_failed", error=str(ex))
        finally:
            with _LOCK:
                _REFRESHING.discard(key)

    _start_thread(run)


def _start_thread(fn) -> None:
    threading.Thread(target=fn, name="weather-refresh", daemon=True).start()


def _fetch_weather(key: tuple, lat: float, lon: float, start: date, end: date, *,
                   budget: float) -> dict[str, dict]:
    """Ask Open-Meteo (one or two calls), within `budget` seconds in all, and keep
    what it answered: in the cache for this range, and night by night for the next."""
    now = datetime.now(UTC)
    deadline = _clock() + budget
    hours: dict[str, dict] = {}
    failed = False
    today = now.date()
    segments = []
    arch_end = min(end, today - timedelta(days=5))
    if start <= arch_end:
        segments.append((_ARCHIVE, start, arch_end))
    fc_start = max(start, today - timedelta(days=6))
    if fc_start <= end:
        segments.append((_FORECAST, fc_start, end))
    for url, s, e in segments:
        left = deadline - _clock()
        if left < 1:
            log.warning("patterns.weather_skipped", reason="out of time", url=url)
            failed = True
            continue
        try:
            r = httpx.get(url, params={
                "latitude": lat, "longitude": lon, "hourly": _HOURLY, "timezone": _TZ,
                "start_date": s.isoformat(), "end_date": e.isoformat(),
            }, timeout=min(30.0, left))
            r.raise_for_status()
            h = r.json().get("hourly", {})
        except Exception as ex:
            log.warning("patterns.weather_failed", error=str(ex))
            failed = True
            continue
        for i, t in enumerate(h.get("time", [])):
            hours[t] = {
                "temp": _at(h, "temperature_2m", i), "pressure": _at(h, "surface_pressure", i),
                "wind": _at(h, "wind_speed_10m", i), "rain": _at(h, "precipitation", i),
                "cloud": _at(h, "cloud_cover", i),
            }
    known = _KNOWN.setdefault(key[:2], {})
    nights: dict[str, dict] = {}
    for ds in _dates(start, end):
        cur = date.fromisoformat(ds)
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
        if _has_weather(night):
            known[ds] = night
        # A call that failed leaves the nights an earlier one brought.
        nights[ds] = night if _has_weather(night) else known.get(ds) or night
    if len(_WCACHE) > 64:
        _WCACHE.clear()
    # Kept until the range changes when every call worked; a failure only briefly,
    # so the next visit asks again rather than showing no weather all day.
    _WCACHE[key] = (nights, now + FAILED_WEATHER_TTL if failed else None)
    return nights


def _nightly_activity(db: Session) -> tuple[list[str], dict]:
    """(nights, {night: {scope: visits per watching camera, "cameras": n}}).

    Only nights at least one camera nobody retired was demonstrably watching, and on
    each only the cameras that were: two cameras watching and four visits is two a
    camera, the same as one camera and two visits. A night runs 18:00 -> 06:00 and
    _overnight_weather keys it by the EVENING date, as the exposure night key does,
    so post-midnight activity sits against its own night's weather."""
    tonight = current_night()
    first = tonight - timedelta(days=HISTORY_NIGHTS)
    cams = set(db.scalars(select(Camera.id).where(Camera.retired_at.is_(None))).all())
    watching: dict[date, set] = {}
    for cam_id, night in db.execute(
        select(CameraNight.camera_id, CameraNight.night).where(
            CameraNight.night >= first, CameraNight.night < tonight,
            CameraNight.exposure_state.in_(WATCHED),
        )
    ).all():
        if cam_id in cams:
            watching.setdefault(night, set()).add(cam_id)
    if not watching:
        return [], {}
    # Hidden species and photos marked "nothing in it" are not visits (visit_rows).
    visits = visits_by_night(db, start=night_key_start(first - timedelta(days=1)),
                             end=night_key_start(tonight))
    counts: dict[str, dict] = {}
    for night, cams_on in watching.items():
        counts[night.isoformat()] = {"cameras": len(cams_on)}
    for (night, cam_id, species_id), row in visits.items():
        if cam_id not in watching.get(night, ()):
            continue
        bucket = counts[night.isoformat()]
        bucket["all"] = bucket.get("all", 0) + row["visits"]
        if species_id:
            bucket[species_id] = bucket.get(species_id, 0) + row["visits"]
    for bucket in counts.values():
        n = bucket["cameras"]
        for k in list(bucket):
            if k != "cameras":
                bucket[k] = bucket[k] / n
    return sorted(counts), counts


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


def _split(pairs: list[tuple[float, float]]) -> tuple[tuple[list, int, int] | None, str]:
    """The nights sorted by the condition, and how many make its low and its high end;
    with why not, when they can't be had.

    The low third against the high third. When the thirds tie (a dry autumn: rain on
    one night in eight, so two thirds of the nights read 0 mm), the nights at the
    common reading against all the others instead, dry against wet, when each side
    has MIN_SIDE nights. Status "insufficient" below MIN_NIGHTS; "no_spread" when
    there are nights enough but too few of them differ (a flat reading, or three wet
    nights in ninety)."""
    if len(pairs) < MIN_NIGHTS:
        return None, "insufficient"
    pairs = sorted(pairs, key=lambda p: p[0])
    n = len(pairs)
    k = max(1, n // 3)
    if pairs[k - 1][0] < pairs[n - k][0]:
        return (pairs, k, k), "ok"
    if pairs[0][0] == pairs[-1][0]:
        return None, "no_spread"
    at_low = sum(1 for v, _ in pairs if v == pairs[0][0])
    at_high = sum(1 for v, _ in pairs if v == pairs[-1][0])
    lo_n, hi_n = (at_low, n - at_low) if at_low >= at_high else (n - at_high, at_high)
    if min(lo_n, hi_n) < MIN_SIDE:
        return None, "no_spread"
    return (pairs, lo_n, hi_n), "ok"


def _contrast(values: list[float], lo_n: int, hi_n: int, scale: float) -> float:
    """How far apart the high and the low end are, as a share of the average night."""
    return abs(_mean(values[-hi_n:]) - _mean(values[:lo_n])) / (scale or 1.0)


def _driver(key: str, label: str, hi_desc: str, lo_desc: str, pairs: list[tuple[float, float]]) -> dict | None:
    """pairs = [(variable_value, visits_per_camera_that_night)] over watched nights.

    The bars for one condition: its low end, the nights in between and its high end
    (_split), and the average of each. Two bars, not three, when the ends are the
    nights at a common reading and the rest (dry and wet). Whether the difference
    between the ends could be chance is for the shuffle test (_shuffle_test), not for
    this; the middle bar is never tested."""
    split, _ = _split(pairs)
    if split is None:
        return None
    pairs, lo_n, hi_n = split
    n = len(pairs)
    lo_rate = _mean([c for _, c in pairs[:lo_n]])
    hi_rate = _mean([c for _, c in pairs[-hi_n:]])
    overall = _mean([c for _, c in pairs]) or 1.0
    r = _pearson([v for v, _ in pairs], [c for _, c in pairs])
    if hi_rate >= lo_rate:
        desc, base, peak = hi_desc, lo_rate, hi_rate
    else:
        desc, base, peak = lo_desc, hi_rate, lo_rate
    effect = (peak - base) / overall * 100.0
    # effect_pct is a normalized contrast. Its denominator is the overall mean, NOT
    # the low group. It must never be presented as a percent increase or a ratio
    # between groups.
    statement = (
        f"About {hi_rate:.1f} visits a night with {hi_desc}, "
        f"about {lo_rate:.1f} with {lo_desc}."
    )
    buckets = [{"label": "low", "rate": round(lo_rate, 1), "days": lo_n,
                "min": pairs[0][0], "max": pairs[lo_n - 1][0]}]
    if n - lo_n - hi_n > 0:
        mid = [c for _, c in pairs[lo_n:n - hi_n]]
        buckets.append({"label": "mid", "rate": round(_mean(mid), 1), "days": len(mid),
                        "min": pairs[lo_n][0], "max": pairs[n - hi_n - 1][0]})
    buckets.append({"label": "high", "rate": round(hi_rate, 1), "days": hi_n,
                    "min": pairs[n - hi_n][0], "max": pairs[-1][0]})
    return {
        "factor": label,
        "statement": statement,
        "effect_pct": round(effect),
        "favours": desc,
        "sample_nights": n,
        "buckets": buckets,
        "correlation": round(r, 2),
        "key": key,
        # Which end had more visits: the one direction a finding may state.
        "favours_high": hi_rate >= lo_rate,
        "status": "ok",
        "beats_chance": False,
    }


def _detrended(series: list[dict]) -> list[float]:
    """Each night's count less the season's level around it.

    A season drifts: acorns fall and the boar build up, a sounder moves to another
    feeder for a fortnight. Night length and the temperature follow the calendar
    too, so on raw counts that drift read as "more wild boar on long nights" in as
    many as one season of pure chance in four. Against the level only a
    night-to-night difference counts.

    The level is the average count over a whole moon cycle of dates around the night
    (LEVEL_DAYS either side), the window moved inwards at the start and the end of
    the season rather than cut short: over a whole cycle the moon's own swing
    averages out, so a real moon pattern is not taken out with the season."""
    days = [date.fromisoformat(row["night"]).toordinal() for row in series]
    counts = [row["count"] for row in series]
    if not days:
        return []
    first, last = days[0], days[-1]
    sums = [0.0]
    for c in counts:
        sums.append(sums[-1] + c)
    out = []
    for day, count in zip(days, counts, strict=True):
        lo, hi = day - LEVEL_DAYS, day + LEVEL_DAYS
        if lo < first:
            lo, hi = first, min(last, hi + first - lo)
        if hi > last:
            lo, hi = max(first, lo - (hi - last)), last
        a, b = bisect_left(days, lo), bisect_right(days, hi)
        out.append(count - (sums[b] - sums[a]) / (b - a))
    return out


def _series(dates: list[str], counts: dict, weather: dict, moon: dict, scope: str) -> list[dict]:
    """One row per watched night: the scope's visits per camera, and the conditions."""
    series = []
    prev_pressure = None
    prev_day = None
    for ds in dates:
        w = weather.get(ds, {})
        m = moon.get(ds, {})
        pressure = w.get("pressure")
        day = date.fromisoformat(ds)
        # A change since the night before, so only when that night is in the series.
        trend = (
            pressure - prev_pressure
            if pressure is not None and prev_pressure is not None
            and prev_day is not None and (day - prev_day).days == 1 else None
        )
        prev_pressure, prev_day = pressure, day
        series.append({
            "night": ds,
            "count": counts.get(ds, {}).get(scope, 0),
            "moon_illum": m.get("illum"), "darkness": m.get("darkness"),
            "temp": w.get("temp"), "pressure": pressure, "pressure_trend": trend,
            "wind": w.get("wind"), "rain": w.get("rain"), "cloud": w.get("cloud"),
        })
    return series


def _scope_drivers(dates: list[str], counts: dict, weather: dict, moon: dict, scope: str) -> dict:
    series = _series(dates, counts, weather, moon, scope)
    drivers = []
    status = {}
    for key, label, hi_desc, lo_desc in _VARS:
        pairs = [(row[key], row["count"]) for row in series if row.get(key) is not None]
        d = _driver(key, label, hi_desc, lo_desc, pairs)
        if d:
            drivers.append(d)
            status[key] = "ok"
        elif key in _WEATHER_VARS and not pairs and series:
            status[key] = "unavailable"  # the weather history could not be fetched
        else:
            # Too few nights, or nights enough that hardly differ (three wet ones).
            status[key] = _split(pairs)[1]
    active = sum(1 for row in series if row["count"] > 0)
    total = sum(row["count"] * counts.get(row["night"], {}).get("cameras", 1) for row in series)
    return {
        "drivers": drivers,
        "status": status,
        "series": series,
        "active_nights": active,
        "total_nights": len(series),
        "avg_per_night": round(_mean([row["count"] for row in series]), 1) if series else 0,
        "sightings": round(total),
    }


def _blocks(n: int) -> list[range]:
    return [range(i, min(i + SHUFFLE_BLOCK, n)) for i in range(0, n, SHUFFLE_BLOCK)]


def _shuffle_test(scopes: list[dict]) -> float | None:
    """Mark the conditions whose difference beats chance; return the bar they cleared.

    What is tested is the one thing a finding may say: the high end of a condition
    against its low end (never the middle bar), on each night's visits less the level
    of the nights around it (_detrended), so a season that drifts is not a finding.
    Each shuffle moves whole weeks of those to other weeks' conditions (so a busy
    week stays together, as busy weeks do), then notes the biggest difference between
    the ends that ANY condition in ANY scope shows. Doing that SHUFFLES times says how
    big a difference chance alone makes when eight conditions and three groups of
    animals are all looked at; a real one has to beat 95% of them, and point the same
    way as the bars. Seeded, so the page says the same thing on every visit."""
    tests = []  # (driver, order of its nights, low end, high end, values, scale)
    for s in scopes:
        series = s["series"]
        if not series:
            continue
        values = _detrended(series)
        scale = _mean([row["count"] for row in series])
        for d in s["drivers"]:
            idx = [i for i, row in enumerate(series) if row.get(d["key"]) is not None]
            order = sorted(idx, key=lambda i: series[i][d["key"]])
            lo_n = next(b["days"] for b in d["buckets"] if b["label"] == "low")
            hi_n = next(b["days"] for b in d["buckets"] if b["label"] == "high")
            tests.append((d, order, lo_n, hi_n, values, scale))
    if not tests:
        return None
    n = max(len(t[4]) for t in tests)
    blocks = _blocks(n)
    rng = random.Random(f"patterns:{n}:{len(tests)}")
    maxima = []
    for _ in range(SHUFFLES):
        shuffled_blocks = blocks[:]
        rng.shuffle(shuffled_blocks)
        perm = [i for b in shuffled_blocks for i in b]
        biggest = 0.0
        for _d, order, lo_n, hi_n, values, scale in tests:
            moved = [values[perm[i]] for i in order]
            biggest = max(biggest, _contrast(moved, lo_n, hi_n, scale))
        maxima.append(biggest)
    maxima.sort()
    bar = maxima[min(len(maxima) - 1, math.ceil(CHANCE_LEVEL * len(maxima)) - 1)]
    for d, order, lo_n, hi_n, values, scale in tests:
        ordered = [values[i] for i in order]
        rises = _mean(ordered[-hi_n:]) >= _mean(ordered[:lo_n])
        d["beats_chance"] = (_contrast(ordered, lo_n, hi_n, scale) > bar
                             and rises == d["favours_high"])
    return bar


def compute_patterns(db: Session) -> dict:
    dates, counts = _nightly_activity(db)
    if not dates:
        return {"scopes": [], "nights": 0, "tested": False}
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
        if s["sightings"] >= MIN_NIGHTS:  # only show a scope with enough visits to mean anything
            scopes.append(s)
    bar = _shuffle_test(scopes)
    for s in scopes:
        del s["series"]
        s["drivers"].sort(key=lambda d: (not d["beats_chance"], -d["effect_pct"]))
    log.info("patterns.computed", nights=len(dates), scopes=len(scopes),
             findings=sum(d["beats_chance"] for s in scopes for d in s["drivers"]))
    return {
        "scopes": scopes, "nights": len(dates), "range": [dates[0], dates[-1]],
        "tested": bar is not None, "shuffles": SHUFFLES,
        "chance_bar_pct": round(bar * 100) if bar is not None else None,
    }
