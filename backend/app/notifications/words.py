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

from app import i18n

# Everything here is written in the language being written in (app.i18n): a push is
# composed inside `i18n.use(<its recipient's language>)`.


def join(names: list[str]) -> str:
    return i18n.join(names)


def visits(n: int) -> str:
    return i18n.t("count.visits", n=n)


def name(species_id: str | None, tally: dict) -> str:
    """What a tally is about, in the language: its species' name there, or the name
    an admin gave it. A tally keeps the English one (dispatch.group_by_species)."""
    return i18n.species_name(species_id, tally.get("name")) if species_id else (
        tally.get("name") or i18n.t("class.animal"))


def names(tallies: list[tuple[str | None, dict]]) -> list[str]:
    """Several tallies' names for one list, most first: the first as it starts the
    sentence, the rest as words inside it (i18n.species_inside: "Villisika,
    saksanhirvi ja 2 muuta")."""
    return [i18n.species_inside(sid, tally.get("name")) if i and sid else name(sid, tally)
            for i, (sid, tally) in enumerate(tallies)]


def said_at(at: datetime | None, tz: ZoneInfo, now: datetime | None = None, *,
            since: bool = False) -> str:
    """"22:14", "23:50 last night" or "23:50 on Thu 24 Sep", on the estate's clock.

    `since`: the time after "since" (push.update), which some languages write
    differently from the time alone ("desde las 02:04", not "desde a las 02:04").

    An alert about last night read the next morning used to say only "23:50", which
    reads as tonight (audit D-21). The day goes by the night, as every screen counts
    them (exposure.current_night, 06:00 to 06:00), not by the calendar: a boar at
    23:50 told of at 00:30 is tonight's and says only "23:50". A photo from the night
    before is "last night" (or "yesterday" for one taken in daylight), anything older
    has its date. Without `now`, the time alone.
    """
    from app.forecasting.exposure import current_night

    if at is None:
        return i18n.t("push.just_now")
    local = at.astimezone(tz)
    hhmm = i18n.clock(local)
    bare = "push.since_time" if since else "push.time"
    if now is None:
        return i18n.t(bare, time=hhmm)
    seen, tonight = current_night(at), current_night(now)
    if seen >= tonight:
        return i18n.t(bare, time=hhmm)
    if seen == tonight - timedelta(days=1):
        dark = local.hour >= 18 or local.hour < 6
        return i18n.t("push.last_night" if dark else "push.yesterday", time=hhmm)
    return i18n.t("push.on_day", time=hhmm, day=i18n.weekday_day_month(local))


def where_title(name: str, cameras: Counter) -> str:
    """"Wild boar at PL19", or "Wild boar on 2 cameras"."""
    cams = [c for c, _ in cameras.most_common()]
    if len(cams) == 1:
        return i18n.t("push.at_camera", name=name, camera=cams[0])
    return i18n.t("push.on_cameras", name=name, n=len(cams))


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
