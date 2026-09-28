"""One night on every screen (plan item 9, final review FBE-1).

The statistics' night runs 18:00 to 06:00 local time, keyed by its evening. The
Changed line, Tonight's ranking and classes, Insights and the weather patterns read
only frames inside it, the same stretch the track record grades, so a roe deer at
07:30 or a fox at noon is never filed under the evening after it. The map's night
(18:00-08:00) agrees on everything from 18:00 to 06:00.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.api.routes_map import last_night_visits
from app.forecasting.changes import _Nights
from app.forecasting.exposure import night_key_start, visits_by_night
from app.forecasting.scoring import _detected
from app.forecasting.visits import class_visits, visit_rows
from app.models import Camera, Detection, Estate, Image, Species

from .conftest import requires_db

TZ = ZoneInfo("Europe/Madrid")
D = date(2026, 9, 20)


def _frame(db, cam, when, species):
    img = Image(camera_id=cam.id, captured_at=when, original_path="x.jpg",
                is_empty_frame=False, animal_conf=0.9, processed_at=when, reviewed=False)
    db.add(img)
    db.flush()
    db.add(Detection(image_id=img.id, species_id=species, species_conf=0.9, sex="unknown",
                     sex_attempts=0, age_class="unknown", group_size=1))


def _camera(db):
    e = Estate(name="E", timezone="Europe/Madrid", lat=39.09, lon=-1.36)
    db.add(e)
    db.add_all([Species(id="wild_boar", common_name="Wild boar", huntable=True),
                Species(id="roe_deer", common_name="Roe deer", huntable=True)])
    db.commit()
    cam = Camera(estate_id=e.id, name="Charca", lat=39.09, lon=-1.36)
    db.add(cam)
    db.commit()
    return cam


@requires_db
def test_last_night_is_the_same_night_on_the_sheet_the_changed_line_and_tonight(db_session):
    db = db_session
    cam = _camera(db)
    # The dawn after the night before (06:17) and mid-morning (09:30) on D, then the
    # evening of D and the small hours after it.
    _frame(db, cam, datetime(2026, 9, 20, 6, 17, tzinfo=TZ), "roe_deer")
    _frame(db, cam, datetime(2026, 9, 20, 9, 30, tzinfo=TZ), "roe_deer")
    _frame(db, cam, datetime(2026, 9, 20, 20, 41, tzinfo=TZ), "wild_boar")
    _frame(db, cam, datetime(2026, 9, 21, 4, 43, tzinfo=TZ), "wild_boar")
    db.commit()

    sheet = sum(r["visits"] for r in last_night_visits(db, [cam.id], D).get(cam.id, []))
    changed = _Nights(db, D).per_night.get((cam.id, D), 0)
    start, end = night_key_start(D - timedelta(days=1)), night_key_start(D + timedelta(days=1))
    tonight = db.execute(
        visit_rows(start=start, end=end, camera_ids=[cam.id], nights=True).select()
    ).all()
    classes = class_visits(db, start=start, end=end, camera_ids=[cam.id])
    assert sheet == changed == 2
    assert sorted((r.species_id, r.night) for r in tonight) == [
        ("wild_boar", D), ("wild_boar", D)]
    assert sum(r["visits"] for r in classes if r["night"] == D) == 2
    assert not [r for r in classes if r["species_id"] == "roe_deer"]


@requires_db
def test_a_morning_only_visitor_is_no_night_on_tonight_nor_on_the_track_record(db_session):
    db = db_session
    cam = _camera(db)
    # Roe deer at 07:30 every morning (after the night, before 08:00), and a boar at
    # 22:10 on the last evening.
    for d in range(5):
        _frame(db, cam, datetime(2026, 9, 16 + d, 7, 30, tzinfo=TZ), "roe_deer")
    _frame(db, cam, datetime(2026, 9, 20, 22, 10, tzinfo=TZ), "wild_boar")
    db.commit()

    counted = visits_by_night(db, start=night_key_start(date(2026, 9, 15)))
    tonight_nights = {(n, s) for (n, _c, s) in counted}
    graded = {(date(2026, 9, 15 + d), s) for d in range(6) for s in ("roe_deer", "wild_boar")
              if _detected(db, cam.id, s, date(2026, 9, 15 + d))}
    assert tonight_nights == graded == {(D, "wild_boar")}
