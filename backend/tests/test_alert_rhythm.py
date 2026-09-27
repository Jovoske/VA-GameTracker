"""Alerts that respect the hunter (plan item 15) and tonight's plan push (feature 19).

One buzz per animal per two hours, with quiet updates in between; nothing while
someone sits or inside their quiet hours, then one message after; phones that
failed a few times keep their alerts; the day in the text; the photo's time in the
link; and one plan push a day, about two hours before sunset.

Push delivery is replaced by a recorder, so no test talks to a push service.
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.notifications import dispatch, hold, plan, push, words
from app.notifications.dispatch import SpeciesDigest, compose, dispatch_new_sightings

from .conftest import requires_db

MADRID = ZoneInfo("Europe/Madrid")
# 00:55 on 16 Sep in Madrid (CEST): a sounder at the feeder in the small hours.
NIGHT = datetime(2026, 9, 15, 22, 55, tzinfo=UTC)


# ── words ──────────────────────────────────────────────────────────────────────


def test_an_alert_about_last_night_says_yesterday():
    at = datetime(2026, 9, 25, 21, 50, tzinfo=UTC)  # 23:50 on the 25th in Madrid
    morning = datetime(2026, 9, 26, 5, 30, tzinfo=UTC)  # 07:30 the next day
    assert words.said_at(at, MADRID, at + timedelta(minutes=5)) == "23:50"
    assert words.said_at(at, MADRID, morning) == "23:50 yesterday"
    assert words.said_at(at, MADRID, morning + timedelta(days=2)) == "23:50 on Fri 25 Sep"
    d = SpeciesDigest("wild_boar", "Wild boar")
    d.add("img", at, "PL19")
    assert compose(d, MADRID, morning) == ("Wild boar at PL19", "1 visit at 23:50 yesterday.")


def test_the_link_carries_the_photo_time():
    at = datetime(2026, 9, 25, 21, 50, 7, 123456, tzinfo=UTC)
    url = dispatch.sighting_url("wild_boar", "abc", at)
    assert url == "/photos?species=wild_boar&image=abc&at=2026-09-25T21%3A50%3A07.123Z"
    # A summary opens Photos on the animals it names, not on the last chips picked.
    assert dispatch.summary_url(["wild_boar", "red_deer"]) == "/photos?species=wild_boar%2Cred_deer"


def test_one_boar_across_two_checks_is_one_visit_when_added_up():
    def tally(start: datetime, minutes: list[int], cam="PL19") -> dict:
        d = SpeciesDigest("wild_boar", "Wild boar")
        for m in minutes:
            d.add(f"i{start.timestamp()}{m}", start + timedelta(minutes=m), cam)
        return d.tally()

    first = tally(NIGHT, [0, 5, 10])  # the check at 01:10 sees three frames
    second = tally(NIGHT, [20, 25])  # the next one, ten minutes after the last
    later = tally(NIGHT, [90])  # an hour later: back again
    merged = words.merge([second, first, later])  # any order
    assert merged["visits"] == 2 and merged["cameras"] == {"PL19": 2}
    assert merged["first_at"] == NIGHT.isoformat()
    other = tally(NIGHT, [22], cam="Charca")
    assert words.merge([first, other])["cameras"] == {"PL19": 1, "Charca": 1}


def test_quiet_hours_run_over_midnight():
    class Pref:
        quiet_start, quiet_end = time(23, 0), time(7, 0)

    def at(hh: int, mm: int = 0) -> datetime:
        return datetime(2026, 9, 16, hh, mm, tzinfo=MADRID)

    assert hold.quiet_now(Pref, at(23, 30)) and hold.quiet_now(Pref, at(3))
    assert not hold.quiet_now(Pref, at(7)) and not hold.quiet_now(Pref, at(20))
    Pref.quiet_start, Pref.quiet_end = time(13, 0), time(15, 0)
    assert hold.quiet_now(Pref, at(14)) and not hold.quiet_now(Pref, at(16))
    Pref.quiet_end = time(13, 0)  # the same time twice is no quiet hours
    assert not hold.quiet_now(Pref, at(13))


def test_the_plan_reads_like_the_lock_screen():
    sunset = datetime(2026, 9, 27, 17, 56, tzinfo=UTC)  # 19:56 in Madrid
    title, body = plan.compose_plan({
        "verdict": "BEST_ODDS", "camera": "Charca", "species": "Wild boar",
        "start": "20:40", "end": "22:10", "wind": {"status": "clean"},
    }, sunset)
    assert title == "▲ Charca · wind right · sunset 19:56"
    assert body == "Best odds. Wild boar, best 20:40 to 22:10."
    title, _ = plan.compose_plan({
        "verdict": "QUIET", "camera": "PL19", "species": "Red deer",
        "wind": {"status": "no_bedding"},
    }, sunset)
    assert title == "○ PL19 · sunset 19:56"  # a stand it can't judge: no wind word
    title, body = plan.compose_plan({"verdict": "NO_DATA"}, sunset)
    assert title == "▨ Not enough to say tonight · sunset 19:56"
    assert "Not enough watched nights" in body


def test_the_plan_is_due_from_two_hours_before_sunset_until_sunset():
    night = date(2026, 9, 27)
    sunset = plan.sunset_of(night)
    assert plan.due(sunset - timedelta(hours=2, minutes=1)) is None
    assert plan.due(sunset - timedelta(hours=2)) == (night, sunset)
    assert plan.due(sunset - timedelta(minutes=1)) == (night, sunset)
    assert plan.due(sunset) is None
    # After the clocks go back sunset is before 18:00: still two hours ahead of it.
    winter = date(2026, 12, 10)
    early = plan.sunset_of(winter)
    assert early.astimezone(MADRID).hour == 17
    assert plan.due(early - timedelta(hours=1, minutes=50)) == (winter, early)


# ── against the database ───────────────────────────────────────────────────────


class _Recorder:
    """Stands in for push.send_to_user: remembers what would have gone where."""

    def __init__(self, sent: int = 1, subscriptions: int = 1):
        self.calls: list[tuple] = []
        self.sent, self.subscriptions = sent, subscriptions

    def __call__(self, db, user_id, payload):
        self.calls.append((user_id, payload))
        return {"sent": self.sent, "failed": 0, "removed": 0, "subscriptions": self.subscriptions}

    def payloads(self, user_id=None) -> list[dict]:
        return [p for u, p in self.calls if user_id is None or u == user_id]


@pytest.fixture
def rec(monkeypatch):
    r = _Recorder()
    monkeypatch.setattr(push, "send_to_user", r)
    return r


def _world(db, **pref):
    from app.models import Camera, Estate, NotificationPref, Species, User

    estate = Estate(name="Piedras Lisas", timezone="Europe/Madrid")
    db.add(estate)
    db.flush()
    cams = {n: Camera(estate_id=estate.id, name=n) for n in ("PL19", "Charca")}
    db.add_all(cams.values())
    db.add_all([
        Species(id="wild_boar", common_name="Wild boar", is_priority=True),
        Species(id="red_deer", common_name="Red deer", is_priority=True),
    ])
    user = User(estate_id=estate.id, email="ana@x.test", password_hash="h", role="member")
    db.add(user)
    db.flush()
    db.add(NotificationPref(user_id=user.id, enabled=True,
                            species_ids=["wild_boar", "red_deer"], **pref))
    db.commit()
    return estate, cams, user


def _frame(db, cam, species_id: str, captured_at: datetime):
    from app.models import Detection, Image

    img = Image(camera_id=cam.id, captured_at=captured_at, original_path="x.jpg")
    db.add(img)
    db.flush()
    db.add(Detection(image_id=img.id, species_id=species_id, species_conf=0.9,
                     created_at=captured_at + timedelta(minutes=1)))
    db.commit()
    return img


def _checks(db, cam, species_id: str, start: datetime, every: timedelta, n: int):
    """A frame just before each of `n` checks `every` apart, and the check itself."""
    out = []
    for k in range(n):
        at = start + every * k
        _frame(db, cam, species_id, at - timedelta(minutes=2))
        out.append(dispatch_new_sightings(db, now=at))
    return out


def _alerts(db, user):
    from app.models import Notification

    return db.query(Notification).filter_by(user_id=user.id).order_by(Notification.created_at).all()


@requires_db
def test_a_sounder_all_night_buzzes_once_per_two_hours(db_session, rec):
    _, cams, user = _world(db_session)
    dispatch_new_sightings(db_session, now=NIGHT - timedelta(minutes=30))  # primes

    # One boar frame before every 15-minute sync from 00:55 to 03:40 (K-06: 12 buzzes).
    _checks(db_session, cams["PL19"], "wild_boar", NIGHT, timedelta(minutes=15), 12)

    pays = rec.payloads(user.id)
    assert len(pays) == 12  # nothing is hidden: every check updates the banner
    loud = [p for p in pays if p["renotify"]]
    assert len(loud) == 2  # 00:55 and 02:55, two hours on
    assert all(p["silent"] for p in pays if not p["renotify"])
    assert all(p["tag"] == "sighting-wild_boar" for p in pays)
    # A quiet update carries the running total since the buzz; frames 15 minutes
    # apart are one boar that stayed, so it is still one visit.
    assert pays[1]["body"] == "1 visit since 00:53, last one 01:08."
    rows = _alerts(db_session, user)
    assert [r.push_status for r in rows].count("sent") == 2
    assert [r.push_status for r in rows].count("updated") == 10


@requires_db
def test_a_second_visit_inside_the_cooldown_is_counted_quietly(db_session, rec):
    _, cams, user = _world(db_session)
    dispatch_new_sightings(db_session, now=NIGHT - timedelta(minutes=30))
    _checks(db_session, cams["PL19"], "wild_boar", NIGHT, timedelta(minutes=50), 2)
    # A red deer is another animal: it buzzes on its own.
    _frame(db_session, cams["Charca"], "red_deer", NIGHT + timedelta(minutes=58))
    dispatch_new_sightings(db_session, now=NIGHT + timedelta(minutes=60))

    boar, again, deer = rec.payloads(user.id)
    assert boar["renotify"] and not again["renotify"]
    assert again["body"] == "2 visits since 00:53, last one 01:43."
    assert deer["renotify"] and deer["title"] == "Red deer at Charca"


@requires_db
def test_quiet_hours_hold_everything_then_send_one_message(db_session, rec):
    from app.models import Notification

    _, cams, user = _world(db_session, quiet_start=time(0, 0), quiet_end=time(7, 0))
    dispatch_new_sightings(db_session, now=NIGHT - timedelta(minutes=30))
    _checks(db_session, cams["PL19"], "wild_boar", NIGHT, timedelta(hours=1), 3)
    _frame(db_session, cams["Charca"], "red_deer", NIGHT + timedelta(hours=3))
    dispatch_new_sightings(db_session, now=NIGHT + timedelta(hours=3, minutes=5))

    assert rec.calls == []  # nothing buzzed between 00:55 and 04:00
    held = [r for r in _alerts(db_session, user) if r.push_status == "held"]
    assert len(held) == 4 and all(r.detail["held"] == "quiet" for r in held)

    # 06:30: still quiet. 07:05: one message about all of it.
    assert hold.deliver_held(db_session, now=NIGHT + timedelta(hours=5, minutes=35)) == {
        "summaries": 0, "pushed": 0, "still_waiting": 1}
    out = hold.deliver_held(db_session, now=NIGHT + timedelta(hours=6, minutes=10))
    assert out["summaries"] == 1 and out["pushed"] == 1
    (_, msg), = rec.calls
    assert msg["title"] == "During your quiet hours" and msg["renotify"] is True
    assert msg["body"] == "Wild boar 3 visits and Red deer 1 visit, last one 03:55."
    assert msg["url"] == "/photos?species=wild_boar%2Cred_deer"
    assert db_session.query(Notification).filter_by(push_status="held").count() == 0
    assert db_session.query(Notification).filter_by(push_status="in_summary").count() == 4
    # Twice is still once.
    again = hold.deliver_held(db_session, now=NIGHT + timedelta(hours=6, minutes=25))
    assert again["summaries"] == 0


def _sit(db, user, started: datetime, ended: datetime | None = None):
    from app.api.routes_stands import tonight
    from app.models import Sit, Stand

    stand = Stand(name="Puente", estate_id=user.estate_id)
    db.add(stand)
    db.flush()
    sit = Sit(stand_id=stand.id, user_id=user.id, night=tonight(started), claimed_at=started,
              started_at=started, ended_at=ended)
    db.add(sit)
    db.commit()
    return sit


@requires_db
def test_nothing_buzzes_in_the_high_seat_and_end_sit_sends_one_message(
    db_session, rec, monkeypatch,
):
    """J-21: a sit started and not ended holds every push (sightings and team notes
    alike); END SIT sends one message about them."""
    from app.core import db as core_db
    from app.core.db import get_db
    from app.core.security import create_access_token
    from app.main import app
    from app.models import Notification
    from app.notes import deliver

    now = datetime.now(UTC)
    _, cams, user = _world(db_session)
    sit = _sit(db_session, user, now - timedelta(hours=1))
    dispatch_new_sightings(db_session, now=now - timedelta(minutes=58))
    _frame(db_session, cams["PL19"], "wild_boar", now - timedelta(minutes=55))
    dispatch_new_sightings(db_session, now=now - timedelta(minutes=50))
    _frame(db_session, cams["PL19"], "wild_boar", now - timedelta(minutes=12))
    dispatch_new_sightings(db_session, now=now - timedelta(minutes=5))
    note = Notification(user_id=user.id, kind="team_note", title="Worth a look: Wild boar",
                        body="Pedro: big one", url="/photos?image=x", created_at=now)
    db_session.add(note)
    db_session.commit()
    deliver(db_session, [note.id])
    assert rec.calls == []
    assert {r.push_status for r in _alerts(db_session, user)} == {"held"}

    monkeypatch.setattr(core_db, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            token = create_access_token(str(user.id))
            r = client.post(f"/api/sits/{sit.id}/end", json={},
                            headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()

    (_, msg), = rec.calls
    assert msg["title"] == "While you sat"
    assert msg["body"].startswith("Wild boar 2 visits and 1 photo marked Worth a look, last one ")
    db_session.expire_all()
    assert {r.push_status for r in _alerts(db_session, user)} == {"in_summary", "sent"}


@requires_db
def test_a_sit_nobody_ended_stops_holding_when_it_is_over(db_session, rec):
    _, cams, user = _world(db_session)
    started = datetime(2026, 9, 15, 17, 30, tzinfo=UTC)  # 19:30 Madrid
    _sit(db_session, user, started)
    dispatch_new_sightings(db_session, now=started)
    _frame(db_session, cams["PL19"], "wild_boar", started + timedelta(hours=2))
    dispatch_new_sightings(db_session, now=started + timedelta(hours=2, minutes=5))
    assert rec.calls == []
    # 05:00 Madrid: still the night, still on. 06:15: the night is over, so is the sit.
    assert hold.deliver_held(db_session, now=datetime(2026, 9, 16, 3, 0, tzinfo=UTC))[
        "still_waiting"] == 1
    assert hold.deliver_held(db_session, now=datetime(2026, 9, 16, 4, 15, tzinfo=UTC))[
        "summaries"] == 1


@requires_db
def test_alerts_turned_off_while_they_waited_are_never_sent(db_session, rec):
    from app.models import NotificationPref

    _, cams, user = _world(db_session, quiet_start=time(0, 0), quiet_end=time(7, 0))
    dispatch_new_sightings(db_session, now=NIGHT - timedelta(minutes=30))
    _checks(db_session, cams["PL19"], "wild_boar", NIGHT, timedelta(hours=1), 1)
    db_session.get(NotificationPref, user.id).enabled = False
    db_session.commit()
    hold.deliver_held(db_session, now=NIGHT + timedelta(hours=7))
    assert rec.calls == []
    assert [r.push_status for r in _alerts(db_session, user)] == ["skipped"]


# ── phones that failed a few times keep their alerts (D-04) ──────────────────


class _Blip(Exception):
    pass


def _subscribe(db, user, **kw):
    from app.models import PushSubscription

    s = PushSubscription(user_id=user.id, endpoint=f"https://push.example/{user.id}",
                         p256dh="k", auth="a", **kw)
    db.add(s)
    db.commit()
    return s


@requires_db
def test_a_night_of_network_errors_does_not_drop_the_phone(db_session, monkeypatch):
    import pywebpush

    from app.models import PushSubscription

    def down(**kw):
        raise _Blip("connection reset")

    monkeypatch.setattr(pywebpush, "webpush", down)
    _, _, user = _world(db_session)
    _subscribe(db_session, user, last_success_at=datetime.now(UTC) - timedelta(days=1))
    for _ in range(25):
        push.send_to_user(db_session, user.id, {"title": "t"})
    s = db_session.query(PushSubscription).one()
    assert s.failures == 25  # still there: it took a push yesterday

    # A phone that hasn't taken one in a fortnight, and keeps failing, is let go.
    s.last_success_at = datetime.now(UTC) - timedelta(days=15)
    db_session.commit()
    assert push.send_to_user(db_session, user.id, {"title": "t"})["removed"] == 1
    assert db_session.query(PushSubscription).count() == 0


@pytest.fixture
def api(db_session):
    from app.core.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _headers(user) -> dict:
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


@requires_db
def test_opening_the_app_puts_back_a_subscription_the_server_lost(db_session, api):
    from app.models import PushSubscription

    _, _, user = _world(db_session)
    body = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "k", "auth": "a"}}
    r = api.post("/api/notifications/subscriptions", json=body, headers=_headers(user))
    assert r.status_code == 200
    got = r.json()
    assert got["subscriptions"] == 1 and got["enabled"] is True and got["public_key"]
    db_session.query(PushSubscription).delete()
    db_session.commit()
    # The same phone opens the app again: its subscription is sent again, and is back.
    again = api.post("/api/notifications/subscriptions", json=body, headers=_headers(user))
    assert again.json()["subscriptions"] == 1


@requires_db
def test_quiet_hours_and_the_plan_push_are_saved_and_read_back(db_session, api):
    _, _, user = _world(db_session)
    h = _headers(user)
    before = api.get("/api/notifications/settings", headers=h).json()
    assert (before["quiet_start"], before["quiet_end"], before["plan_push"]) == (None, None, False)

    saved = api.put("/api/notifications/settings", headers=h, json={
        "quiet": True, "quiet_start": "23:30", "quiet_end": "07:00", "plan_push": True,
    }).json()
    assert (saved["quiet_start"], saved["quiet_end"]) == ("23:30", "07:00")
    assert saved["plan_push"] is True
    got = api.get("/api/notifications/settings", headers=h).json()
    assert (got["quiet_start"], got["quiet_end"], got["plan_push"]) == ("23:30", "07:00", True)

    assert api.put("/api/notifications/settings", headers=h, json={
        "quiet": True, "quiet_start": "07:00", "quiet_end": "07:00"}).status_code == 400
    assert api.put("/api/notifications/settings", headers=h, json={
        "quiet": True, "quiet_start": "07:00"}).status_code == 400
    off = api.put("/api/notifications/settings", headers=h, json={"quiet": False}).json()
    assert (off["quiet_start"], off["quiet_end"], off["plan_push"]) == (None, None, True)


# ── tonight's plan, once a day (feature 19) ───────────────────────────────────


def _claim(db, cams, night: date):
    """A plan written by `pipeline.py plan`: Charca best odds, PL19 quiet."""
    from app.models import Forecast, ModelRun

    run = ModelRun(kind="forecast", name="presence_baseline", started_at=datetime.now(UTC),
                   metrics={"target_date": night.isoformat(), "forecasts_written": 2})
    db.add(run)
    db.flush()
    for cam, sp, p, verdict, start, end in (
        ("PL19", "red_deer", 0.1, "QUIET", time(21, 0), time(0, 0)),
        ("Charca", "wild_boar", 0.7, "BEST_ODDS", time(20, 40), time(22, 10)),
    ):
        db.add(Forecast(camera_id=cams[cam].id, target_date=night, species_id=sp,
                        probability=p, best_window_start=start, best_window_end=end,
                        factors={"verdict": verdict, "active_nights": 30},
                        model_run_id=run.id))
    db.commit()


@requires_db
def test_the_plan_push_goes_once_before_sunset_from_the_plan_on_record(
    db_session, rec, monkeypatch,
):
    from app.models import Notification, NotificationPref, User

    night = date(2026, 9, 27)
    sunset = plan.sunset_of(night)
    estate, cams, user = _world(db_session, plan_push=True)
    later = User(estate_id=estate.id, email="off@x.test", password_hash="h", role="member")
    db_session.add(later)
    db_session.flush()
    db_session.add(NotificationPref(user_id=later.id, enabled=True, species_ids=[]))
    db_session.commit()
    _claim(db_session, cams, night)
    monkeypatch.setattr(plan, "_wind", lambda db, p, now: {"status": "clean"})
    monkeypatch.setattr(plan, "live_plan", lambda db: pytest.fail("the claim is on record"))

    early = plan.send_daily_plan(db_session, now=sunset - timedelta(hours=3))
    assert early == {"status": "not_due"}
    out = plan.send_daily_plan(db_session, now=sunset - timedelta(hours=1, minutes=55))
    assert out["status"] == "done" and out["people"] == 1 and out["source"] == "claim"
    (who, msg), = rec.calls
    assert who == user.id  # not the one who never turned it on
    local = sunset.astimezone(MADRID).strftime("%H:%M")
    assert msg["title"] == f"▲ Charca · wind right · sunset {local}"
    assert msg["body"] == "Best odds. Wild boar, best 20:40 to 22:10."
    assert msg["url"] == "/" and msg["tag"] == "plan"

    # The next run, and the one after: already sent tonight.
    for mins in (100, 85):
        again = plan.send_daily_plan(db_session, now=sunset - timedelta(minutes=mins))
        assert again["status"] == "nobody_waiting"
    assert len(rec.calls) == 1
    n = db_session.query(Notification).filter_by(kind="plan").one()
    assert n.detail["night"] == night.isoformat() and n.push_status == "sent"
    # After sunset nothing, even for someone who turns it on late.
    db_session.get(NotificationPref, later.id).plan_push = True
    db_session.commit()
    late = plan.send_daily_plan(db_session, now=sunset + timedelta(minutes=1))
    assert late["status"] == "not_due"


@requires_db
def test_the_plan_is_worked_out_when_the_17h_run_has_not_written_it(
    db_session, rec, monkeypatch,
):
    """From late October the push is due before the 17:00 plan run."""
    night = date(2026, 12, 10)
    sunset = plan.sunset_of(night)
    _world(db_session, plan_push=True)
    monkeypatch.setattr(plan, "live_plan", lambda db: {
        "verdict": "WORTH_A_LOOK", "camera": "PL19", "species": "Red deer",
        "start": "18:10", "end": "21:10", "wind": {"status": "scent_carries"},
        "source": "live"})
    out = plan.send_daily_plan(db_session, now=sunset - timedelta(hours=1, minutes=45))
    assert out["source"] == "live"
    (_, msg), = rec.calls
    assert msg["title"].startswith("◐ PL19 · wind wrong · sunset 17:")


@requires_db
def test_someone_already_sitting_is_not_sent_the_plan(db_session, rec, monkeypatch):
    from app.models import Notification

    night = date(2026, 9, 27)
    sunset = plan.sunset_of(night)
    _, cams, user = _world(db_session, plan_push=True)
    _claim(db_session, cams, night)
    monkeypatch.setattr(plan, "_wind", lambda db, p, now: {"status": "clean"})
    _sit(db_session, user, sunset - timedelta(hours=2, minutes=30))
    plan.send_daily_plan(db_session, now=sunset - timedelta(hours=1, minutes=50))
    assert rec.calls == []
    n = db_session.query(Notification).filter_by(kind="plan").one()
    assert n.push_status == "skipped" and n.detail["skipped"] == "sit"


# ── the notify run and the Tonight alerts ─────────────────────────────────────


def test_the_notify_run_never_waits_behind_the_photo_check(monkeypatch):
    import pipeline
    from app import jobs

    ran: list = []

    class _Null:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def rollback(self):
            pass

    monkeypatch.setattr(pipeline, "configure_logging", lambda **kw: None)
    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Null())
    monkeypatch.setattr("app.notifications.hold.deliver_held", lambda db: ran.append("held"))
    monkeypatch.setattr("app.notifications.plan.send_daily_plan", lambda db: ran.append("plan"))
    check = jobs.try_acquire("pipeline", "sync")  # an hour of photo checking
    try:
        assert pipeline.main(["notify"]) == 0
        assert ran == ["held", "plan"]
        # Two notify runs never overlap; the deploy waits for one.
        mine = jobs.try_acquire("notify", "notify")
        assert pipeline.main(["notify"]) == 0 and ran == ["held", "plan"]
        check.release()
        assert pipeline.main(["busy"]) == pipeline.BUSY_EXIT
        mine.release()
    finally:
        check.release()


def test_a_future_photo_time_never_reads_minus_minutes():
    from app.forecasting.alerts import _ago, _dur

    now = datetime(2026, 10, 26, 22, 0, tzinfo=UTC)
    # A camera still on summer time after the clocks went back: 40 minutes ahead.
    assert _ago(now + timedelta(minutes=40), now) == "just now"
    assert _dur(now + timedelta(minutes=40), now) == "0m"
    assert _ago(now - timedelta(minutes=5), now) == "5m ago"


def test_where_title_names_one_camera_or_counts_them():
    assert words.where_title("Fox", Counter({"PL19": 2})) == "Fox at PL19"
    assert words.where_title("Fox", Counter({"PL19": 2, "Charca": 1})) == "Fox on 2 cameras"
