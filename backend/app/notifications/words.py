"""How an alert says what the cameras saw: shared by the sighting alerts
(dispatch), the one message after a sit or quiet hours (hold) and tonight's plan.

A sighting alert keeps what it counted beside its words, as a tally:
{"name", "visits", "cameras": {camera: visits}, "spans": {camera: [first, last]},
"first_at", "latest_at"}. That is what lets a second sounder inside two hours update
the banner with the running total, and the message after a sit add up everything
that waited. The spans (each camera's first and last frame) are what keep one boar
that stayed across two checks one visit when the tallies are added up.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def join(names: list[str]) -> str:
    if len(names) <= 1:
        return names[0] if names else ""
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    if len(names) == 3:
        return f"{names[0]}, {names[1]} and {names[2]}"
    return f"{names[0]}, {names[1]} and {len(names) - 2} more"


def visits(n: int) -> str:
    return f"{n} visit{'' if n == 1 else 's'}"


def said_at(at: datetime | None, tz: ZoneInfo, now: datetime | None = None) -> str:
    """"22:14", "23:50 yesterday" or "23:50 on Thu 24 Sep", on the estate's clock.

    An alert about last night read the next morning used to say only "23:50", which
    reads as tonight (audit D-21). Without `now`, the time alone.
    """
    if at is None:
        return "just now"
    local = at.astimezone(tz)
    hhmm = local.strftime("%H:%M")
    if now is None:
        return hhmm
    today = now.astimezone(tz).date()
    if local.date() >= today:
        return hhmm
    if local.date() == today - timedelta(days=1):
        return f"{hhmm} yesterday"
    return f"{hhmm} on {local.strftime('%a')} {local.day} {local.strftime('%b')}"


def where_title(name: str, cameras: Counter) -> str:
    """"Wild boar at PL19", or "Wild boar on 2 cameras"."""
    cams = [c for c, _ in cameras.most_common()]
    if len(cams) == 1:
        return f"{name} at {cams[0]}"
    return f"{name} on {len(cams)} cameras"


def _at(raw) -> datetime | None:
    try:
        return datetime.fromisoformat(raw) if raw else None
    except (TypeError, ValueError):
        return None


def tallies_of(species_id: str | None, detail: dict | None) -> dict[str, dict]:
    """{species_id: tally} an alert counted: one species', or each of a summary's."""
    if not detail:
        return {}
    if species_id and "visits" in detail:
        return {species_id: detail}
    return dict(detail.get("species") or {})


def merge(tallies: list[dict], gap: timedelta | None = None) -> dict:
    """One tally from several of the same animal, in the order they were seen: visits
    and cameras added up, the first time and the last.

    A visit is frames less than `gap` (VISIT_GAP) apart, and a check runs every few
    minutes, so one boar that stayed across two checks is in both tallies: when a
    camera's frames in one start within `gap` of its last frame in the one before,
    that is the same visit, counted once.
    """
    from app.forecasting.exposure import VISIT_GAP

    gap = gap or VISIT_GAP
    cams: Counter = Counter()
    spans: dict[str, list] = {}
    first, last, name = None, None, None
    def seen(t: dict) -> float:
        at = _at(t.get("first_at"))
        return at.timestamp() if at else 0.0

    for t in sorted(tallies, key=seen):
        name = name or t.get("name")
        for cam, n in (t.get("cameras") or {}).items():
            span = (t.get("spans") or {}).get(cam) or [None, None]
            f, la = _at(span[0]), _at(span[1])
            had = spans.get(cam)
            n = int(n)
            if had and f and had[1] and f - had[1] <= gap and n > 0:
                n -= 1  # the visit the one before ended on goes on here
            cams[cam] += n
            if had is None:
                spans[cam] = [f, la]
            else:
                spans[cam] = [min(x for x in (had[0], f) if x) if (had[0] or f) else None,
                              max(x for x in (had[1], la) if x) if (had[1] or la) else None]
        f, la = _at(t.get("first_at")), _at(t.get("latest_at"))
        if f and (first is None or f < first):
            first = f
        if la and (last is None or la > last):
            last = la
    return {
        "name": name or "Animal", "visits": sum(cams.values()), "cameras": dict(cams),
        "spans": {c: [s.isoformat() if s else None for s in sp] for c, sp in spans.items()},
        "first_at": first.isoformat() if first else None,
        "latest_at": last.isoformat() if last else None,
    }


def latest(tally: dict) -> datetime | None:
    return _at(tally.get("latest_at"))


def first(tally: dict) -> datetime | None:
    return _at(tally.get("first_at"))
