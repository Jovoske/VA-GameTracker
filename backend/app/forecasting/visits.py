"""Individual visits: the unit every map view counts in.

A visit is an arrival. Frames of the same species at the same camera, each within
VISIT_GAP of the one before, are one visit, so a burst of three frames of one boar
is one visit and the same sounder back an hour later is a second. This module is the
one place that rule is written down: the camera sheet's "last night", the activity
map, the replay of a night and exposure.visits_by_night all read their visits from
`visit_rows`, so their numbers agree.

What counts is what the map shows: a photo the detector has checked and kept (or a
hunter marked as not empty) with something in it that is not a hidden species. A
kept photo nobody has named yet is an "Animal" visit (species_id None). A frame
still waiting for the detector is not a visit yet: most of them turn out empty.

The map's night runs 18:00 to 08:00 local time, the replay's timeline, so first
light (dawn, 03-08) belongs to the night before it. The statistics' night (Tonight,
the Changed line, Insights, the track record) runs 18:00 to 06:00 and is keyed by
exposure.night_expr: they read only frames inside it (`nights`), so a roe deer at
07:30 or a fox at noon is never filed under the evening after it. The two agree on
everything from 18:00 to 06:00. Each visit carries that key as `night`. The map reads
only frames inside its nights (list_visits), so the day between two nights ends every
visit: a badger that turned up at 17:40 and stayed past 18:00 is a visit at 18:05 on
the one night and on the week alike.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, literal, or_, select, text
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import Session

from app.api.visibility import VISIBLE_ANIMAL
from app.core.config import settings
from app.forecasting.exposure import VISIT_GAP, in_night, night_expr
from app.forecasting.model import class_label, class_label_sql, say_class, sql_class_key
from app.models import Camera, Detection, Image, Species

# A photo the detector has checked and kept, of something that is not a hidden species.
CHECKED_ANIMAL = and_(Image.is_empty_frame.is_(False), VISIBLE_ANIMAL)

# The map's night, and its parts by local hour: [from, to) wrapping past midnight.
MAP_NIGHT_START, MAP_NIGHT_END = time(18), time(8)
PARTS: dict[str, tuple[int, int]] = {
    "dusk": (18, 22),
    "night": (22, 3),
    "dawn": (3, 8),
    "all": (18, 8),
}


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.estate_timezone)


def map_night_window(night: date) -> tuple[datetime, datetime]:
    """18:00 on the evening of `night` to 08:00 the next morning, local time."""
    tz = _tz()
    return (
        datetime.combine(night, MAP_NIGHT_START, tzinfo=tz),
        datetime.combine(night + timedelta(days=1), MAP_NIGHT_END, tzinfo=tz),
    )


def map_night_of(at: datetime) -> date | None:
    """The evening a moment belongs to on the map, or None in the day (08:00-18:00)."""
    local = at.astimezone(_tz())
    if local.hour >= MAP_NIGHT_START.hour:
        return local.date()
    if local.hour < MAP_NIGHT_END.hour:
        return local.date() - timedelta(days=1)
    return None


def map_night_expr(col=Image.captured_at):
    """SQL: the evening a moment belongs to on the map (see map_night_of).

    Daytime moments get the evening before, so filter them out with in_map_night.
    """
    local = func.timezone(settings.estate_timezone, col)
    return func.date(local - text("interval '8 hours'"))


def in_map_night(col=Image.captured_at):
    """SQL: whether a moment is inside a map night (18:00-08:00 local)."""
    hour = func.extract("hour", func.timezone(settings.estate_timezone, col))
    return or_(hour >= MAP_NIGHT_START.hour, hour < MAP_NIGHT_END.hour)


def part_hours(part: str) -> list[int]:
    """The local hours a part of the night covers, in night order (18, 19, ... 7)."""
    first, stop = PARTS[part]
    hours, h = [], first
    while h != stop:
        hours.append(h)
        h = (h + 1) % 24
    return hours


def _visit_frames(*, start: datetime | None = None, end: datetime | None = None,
                  camera_ids: list | None = None, species_id: str | None = None,
                  map_nights: bool = False, species_ids=None, nights: bool = False):
    """One row per frame and species, numbered by the visit it belongs to (visit_no,
    per camera and species): the step visit_rows and class_visits share, so the two
    always cut a night into the same visits. A select, for the caller to make a
    subquery or a CTE of. See visit_rows for the arguments."""
    named = (
        select(Detection.image_id, Detection.species_id, Species.common_name, Detection.group_size)
        .join(Species, Species.id == Detection.species_id)
        .where(Species.hidden.is_(False))
        .subquery()
    )
    conditions = [CHECKED_ANIMAL]
    if start is not None:
        conditions.append(Image.captured_at >= start)
    if end is not None:
        conditions.append(Image.captured_at < end)
    if map_nights:
        conditions.append(in_map_night())
    if nights:
        conditions.append(in_night())
    if camera_ids is not None:
        conditions.append(Image.camera_id.in_(camera_ids))
    if species_id is not None:
        conditions.append(named.c.species_id == species_id)
    if species_ids is not None:
        conditions.append(named.c.species_id.in_(species_ids))
    # One row per photo and species: two boxes of the same boar are one frame.
    frames = (
        select(
            Image.id.label("image_id"), Image.camera_id, named.c.species_id,
            named.c.common_name, Image.captured_at,
            func.max(named.c.group_size).label("group_size"),
        )
        .select_from(Image)
        .outerjoin(named, named.c.image_id == Image.id)
        .where(*conditions)
        .group_by(
            Image.id, Image.camera_id, named.c.species_id, named.c.common_name, Image.captured_at,
        )
        .subquery()
    )
    by_visit = (frames.c.camera_id, frames.c.species_id)
    in_order = (frames.c.captured_at, frames.c.image_id)
    lagged = select(
        frames,
        func.lag(frames.c.captured_at)
        .over(partition_by=by_visit, order_by=in_order)
        .label("prev_at"),
    ).subquery()
    arrival = case(
        (or_(lagged.c.prev_at.is_(None), lagged.c.captured_at - lagged.c.prev_at > VISIT_GAP), 1),
        else_=0,
    )
    return select(
        lagged,
        func.sum(arrival).over(
            partition_by=(lagged.c.camera_id, lagged.c.species_id),
            order_by=(lagged.c.captured_at, lagged.c.image_id),
            rows=(None, 0),
        ).label("visit_no"),
    )


def visit_rows(*, start: datetime | None = None, end: datetime | None = None,
               camera_ids: list | None = None, species_id: str | None = None,
               map_nights: bool = False, species_ids=None, nights: bool = False):
    """One row per visit, as a subquery.

    Columns: camera_id, species_id, common_name, night (the app's night key of its
    first frame), first_at, last_at, frames, max_group (the largest group seen in
    it, 1 when nobody counted), image_id (its first frame).

    Only frames in [start, end) are read, so a visit that began before `start` is
    counted from its first frame inside the range. With `map_nights`, only frames
    inside the map's nights (18:00-08:00) are, so however many nights the range
    spans, each visit is what reading its own night alone would give. With `nights`,
    only frames inside the statistics' nights (exposure.in_night, 18:00-06:00) are,
    the same stretch the track record grades. A photo
    holding a hidden species and a visible one counts once, as the visible one.
    `species_ids` (a list, or a subquery of ids) keeps only those species' visits,
    read from their sightings rather than from every photo in the range: over a
    season that is what keeps Tonight quick.
    """
    numbered = _visit_frames(start=start, end=end, camera_ids=camera_ids,
                             species_id=species_id, map_nights=map_nights,
                             species_ids=species_ids, nights=nights).subquery()
    first_at = func.min(numbered.c.captured_at)
    return (
        select(
            numbered.c.camera_id,
            numbered.c.species_id,
            numbered.c.common_name,
            night_expr(first_at).label("night"),
            first_at.label("first_at"),
            func.max(numbered.c.captured_at).label("last_at"),
            func.count().label("frames"),
            func.coalesce(func.max(numbered.c.group_size), 1).label("max_group"),
            func.array_agg(
                aggregate_order_by(numbered.c.image_id, numbered.c.captured_at, numbered.c.image_id)
            )[1].label("image_id"),
        )
        .group_by(
            numbered.c.camera_id, numbered.c.species_id, numbered.c.common_name,
            numbered.c.visit_no,
        )
        .subquery()
    )


def list_visits(db: Session, *, start: datetime, end: datetime, camera_ids: list | None = None,
                species_id: str | None = None) -> list[dict]:
    """Every visit whose frames fall in [start, end) and inside the map's nights,
    earliest first.

    Each is {camera_id, species_id, label, night, first_at, last_at, frames,
    max_group, image_id}. The label is the species in the Photos tiles' words
    ("Wild boar"), or "Animal" for a kept photo nobody has named. Daytime frames
    are not read, so a visit never starts in the day: the activity map, the replay
    and its list of nights count the same visits whatever range they ask for.
    """
    v = visit_rows(start=start, end=end, camera_ids=camera_ids, species_id=species_id,
                   map_nights=True)
    rows = db.execute(select(v).order_by(v.c.first_at, v.c.camera_id, v.c.species_id)).all()
    return [
        {
            "camera_id": r.camera_id,
            "species_id": r.species_id,
            "label": class_label(r.species_id, r.common_name, None, None),
            "night": r.night,
            "first_at": r.first_at,
            "last_at": r.last_at,
            "frames": int(r.frames),
            "max_group": int(r.max_group),
            "image_id": r.image_id,
        }
        for r in rows
    ]


def class_visits(db: Session, *, start: datetime | None = None, end: datetime | None = None,
                 camera_ids: list | None = None, species_ids: list | None = None,
                 nights: bool = True) -> list[dict]:
    """Visits per camera, class ("Stag", "Sow + piglets", "Roe deer") and night,
    photos alongside.

    The species' own visits (visit_rows), each given one class: the most telling
    label among its frames, a sexed or grouped one ("Sow + piglets") over the plain
    species ("Wild boar"), then the label most of its frames carry. The sex and group
    pass looks at only some frames, so the frames of one arrival can carry two labels;
    counted per label, that arrival was a visit of each, and the classes added up to
    twice the visits Tonight, the map and Insights show. Split this way they always
    add up to the species' visits, and "Sow + piglets: 12 visits" still counts
    arrivals, not the forty frames of one family loitering at the feeder. A visit's
    photos are all its frames, so the photos add up too.

    Only named sightings of species that are not hidden, in photos the detector kept
    and nobody marked "nothing in it", from cameras nobody retired. Each row is
    {camera_id, species_id, label, key, night, visits, photos} (key: model.class_key,
    the class the same in every language); the night is the app's
    night key of the visit's first frame, so a caller can keep the nights it counts.
    Only frames inside the nights (exposure.in_night, 18:00-06:00) count, as
    everywhere a statistic is kept.
    """
    # Numbered once and read twice (the visits, and each frame's label): as a CTE
    # Postgres works the frames out one time instead of once per reading.
    n = _visit_frames(start=start, end=end, camera_ids=camera_ids, species_ids=species_ids,
                      nights=nights).cte("numbered")
    visit = (n.c.camera_id, n.c.species_id, n.c.visit_no)
    visits = (
        select(*visit, n.c.common_name,
               night_expr(func.min(n.c.captured_at)).label("night"),
               func.count().label("frames"))
        .where(n.c.species_id.isnot(None))
        .group_by(*visit, n.c.common_name)
        .subquery()
    )
    # The labels each frame carries: a frame with a stag and a hind in it is a frame
    # of each, and the visit takes the one that tells most.
    label = class_label_sql(Detection.species_id, Detection.sex, Detection.group_type,
                            n.c.common_name)
    frame_labels = (
        select(*visit, n.c.image_id, func.coalesce(label, literal("")).label("cls"))
        .select_from(n)
        .join(Detection, and_(Detection.image_id == n.c.image_id,
                              Detection.species_id == n.c.species_id))
        .distinct()
        .subquery()
    )
    fl = frame_labels.c
    per_label = (
        select(fl.camera_id, fl.species_id, fl.visit_no, fl.cls, func.count().label("frames"))
        .group_by(fl.camera_id, fl.species_id, fl.visit_no, fl.cls)
        .subquery()
    )
    pl = per_label.c
    plain = pl.cls == ""
    chosen = (
        select(pl.camera_id, pl.species_id, pl.visit_no, pl.cls)
        .distinct(pl.camera_id, pl.species_id, pl.visit_no)
        .order_by(pl.camera_id, pl.species_id, pl.visit_no, plain, pl.frames.desc(), pl.cls)
        .subquery()
    )
    v, c = visits.c, chosen.c
    rows = db.execute(
        select(v.camera_id, v.species_id, v.common_name, c.cls, v.night,
               func.count().label("visits"), func.sum(v.frames).label("photos"))
        .select_from(visits)
        .join(chosen, and_(c.camera_id == v.camera_id, c.species_id == v.species_id,
                           c.visit_no == v.visit_no))
        .join(Camera, Camera.id == v.camera_id)
        .where(Camera.retired_at.is_(None))
        .group_by(v.camera_id, v.species_id, v.common_name, c.cls, v.night)
    ).all()
    return [
        {
            "camera_id": r.camera_id,
            "species_id": r.species_id,
            "label": say_class(r.cls, r.species_id, r.common_name),
            "key": sql_class_key(r.cls, r.species_id),
            "night": r.night,
            "visits": int(r.visits),
            "photos": int(r.photos),
        }
        for r in rows
    ]
