"""Tonight's plan on the lock screen: one push a day, about two hours before sunset.

The redesign's one fixed-schedule notification (docs/redesign/03 §11, audit J-20):
the whole plan in the banner, "▲ Charca · wind right · sunset 19:56", so on most
nights a hunter can decide without opening the app. It goes every day to whoever
turned it on in Settings, quiet nights included: a plan that only speaks up on good
nights teaches that silence means broken.

Task Scheduler can't start a job at sunset, and sunset at Alatoz moves by three
hours over the season, so `pipeline.py notify` runs every 15 minutes and this sends
once it is PLAN_LEAD before tonight's sunset, never after sunset, and once per
person per night: each send is a row per person and night, written under a per-night
lock before anything is pushed, so two runs at once can't both send it. A send that
reached no phone (the server's internet down for a moment, or the phone's copy lost
and not yet put back by the app) is tried again by the next run until sunset, on
the same row.

What it says is the plan on record for tonight: the claim `plan` writes
(scoring.persist_tonight), the same one that is scored tomorrow. From late October
the push is due before the 17:00 `plan` run, and then the plan is worked out as
Tonight works it out, without writing a claim. The wind is judged at the stand for
the top camera, for the sit time, as Tonight judges it (conditions.wind_verdict).

Someone already sitting, or inside their quiet hours, isn't sent it: by the time
either is over the plan is old news. The record says so.
"""
from __future__ import annotations

import uuid
import zlib
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.forecasting.conditions import clock, sunset_of
from app.forecasting.exposure import current_night
from app.forecasting.model import sentence_case
from app.i18n import DEFAULT, species_name, t, use
from app.models import Camera, Forecast, ModelRun, Notification, NotificationPref, Species
from app.notifications import hold, push

log = get_logger(__name__)

PLAN_LEAD = timedelta(hours=2)
PLAN_URL = "/"
# Verdicts by shape and word, as Tonight writes them.
VERDICTS = {
    "BEST_ODDS": ("▲", "verdict.best_odds"),
    "WORTH_A_LOOK": ("◐", "verdict.worth_a_look"),
    "QUIET": ("○", "verdict.quiet"),
    "NO_DATA": ("▨", "verdict.no_data"),
}
# The wind in two or three words. A stand that can't be judged (not on the map, no
# bedding drawn) leaves the wind out rather than guess.
WIND = {
    "clean": "plan.wind.clean",
    "scent_carries": "plan.wind.wrong",
    "too_light": "plan.wind.too_light",
    "no_wind_data": "plan.wind.no_forecast",
}
_LOCK = zlib.crc32(b"gamesense.notify.plan") & 0x7FFFFFFF


def due(now: datetime) -> tuple[date, datetime] | None:
    """(tonight, its sunset) from PLAN_LEAD before sunset until sunset, else None."""
    night = current_night(now)
    sunset = sunset_of(night)
    if sunset is None or not (sunset - PLAN_LEAD <= now < sunset):
        return None
    return night, sunset


def _hhmm(t) -> str | None:
    if isinstance(t, time):
        return t.strftime("%H:%M")
    return t or None


def recorded_plan(db: Session, night: date) -> dict | None:
    """Tonight's top camera from the claim on record, or None when none is written."""
    run = db.scalar(
        select(ModelRun)
        .where(ModelRun.kind == "forecast",
               ModelRun.metrics["target_date"].astext == night.isoformat())
        .order_by(ModelRun.started_at.desc())
        .limit(1)
    )
    if run is None:
        return None
    rows = db.execute(
        select(Forecast, Camera.name, Species.common_name)
        .join(Camera, Camera.id == Forecast.camera_id)
        .outerjoin(Species, Species.id == Forecast.species_id)
        .where(Forecast.model_run_id == run.id)
    ).all()
    if not rows:
        return {"verdict": "NO_DATA", "source": "claim"}

    def rank(row) -> tuple:
        f = row[0]
        verdict = (f.factors or {}).get("verdict")
        # As model._rank_key: a camera that can be judged first, then its odds.
        return (verdict not in (None, "NO_DATA"), f.probability,
                (f.factors or {}).get("active_nights") or 0)

    f, camera, species = max(rows, key=rank)
    return {
        "verdict": (f.factors or {}).get("verdict") or "NO_DATA",
        "camera": camera, "camera_id": f.camera_id,
        "species": sentence_case(species) if species else None,
        "species_id": f.species_id,
        "start": _hhmm(f.best_window_start), "end": _hhmm(f.best_window_end),
        "source": "claim",
    }


def live_plan(db: Session) -> dict:
    """Tonight's plan worked out now, as Tonight shows it (no claim written)."""
    from app.forecasting.model import forecast_tonight

    f = forecast_tonight(db)
    rec = f.get("recommended")
    if not rec:
        return {"verdict": "NO_DATA", "source": "live"}
    w = rec.get("best_window") or {}
    return {
        "verdict": f.get("verdict") or "NO_DATA",
        "camera": rec.get("camera"), "camera_id": rec.get("camera_id"),
        "species": rec.get("species"), "species_id": rec.get("species_id"),
        "start": w.get("start"), "end": w.get("end"),
        "wind": f.get("wind"), "source": "live",
    }


def _wind(db: Session, plan: dict, now: datetime) -> dict | None:
    """The wind verdict for the top camera's stand, for tonight's sit time."""
    if plan.get("wind") is not None or not plan.get("camera_id"):
        return plan.get("wind")
    from app.forecasting.conditions import (
        no_stand_verdict,
        release,
        stand_for_camera,
        tonight_conditions,
        wind_verdict,
    )

    stand = stand_for_camera(db, uuid.UUID(str(plan["camera_id"])))
    release(db)  # no connection held while Open-Meteo answers
    try:
        cond = tonight_conditions(now)
    except Exception as e:  # the plan goes without the wind rather than not at all
        log.warning("plan_push.weather_failed", error=str(e)[:200])
        cond = {}
    if stand is None:
        return no_stand_verdict(plan["camera"], cond, now=now)
    return wind_verdict(db, stand, cond, now=now)


def compose_plan(plan: dict, sunset: datetime | None) -> tuple[str, str]:
    """(title, body): "▲ Charca · wind right · sunset 19:56" /
    "Best odds. Wild boar, best 20:40 to 22:10." The answer first; the rest after.
    In the language being written in: each recipient's (send_daily_plan)."""
    glyph, key = VERDICTS.get(plan.get("verdict") or "NO_DATA", VERDICTS["NO_DATA"])
    label = t(key)
    camera = plan.get("camera")
    bits = [f"{glyph} {camera}" if camera else f"{glyph} {t('plan.tonight', verdict=label)}"]
    wind = WIND.get(((plan.get("wind") or {}).get("status")) or "")
    if camera and wind:
        bits.append(t(wind))
    if sunset is not None:
        bits.append(t("plan.sunset", time=clock(sunset)))
    title = " · ".join(bits)

    if not camera:
        return title, t("plan.no_camera")
    body = f"{label}."
    if plan.get("species"):
        species = species_name(plan.get("species_id"), plan["species"])
        if plan.get("start") and plan.get("end"):
            body += " " + t("plan.species_hours", species=species, start=plan["start"],
                            end=plan["end"])
        else:
            body += f" {species}."
    return title, body


def _opted_in(db: Session) -> list[NotificationPref]:
    return list(db.scalars(
        select(NotificationPref).where(
            NotificationPref.enabled.is_(True), NotificationPref.plan_push.is_(True))
    ).all())


# How a send went that the next run tries again.
RETRY = ("failed", "no_subscription")


def _tonights(night: date):
    return select(Notification).where(
        Notification.kind == "plan", Notification.detail["night"].astext == night.isoformat())


def _sent_for(db: Session, night: date) -> set:
    """Who has had tonight's plan, or is being sent it now, or was skipped (sitting,
    quiet hours): everyone with a row for tonight but one to try again."""
    return set(db.scalars(
        _tonights(night).with_only_columns(Notification.user_id).where(
            Notification.push_status.is_(None) | Notification.push_status.notin_(RETRY))
    ).all())


def send_daily_plan(db: Session, now: datetime | None = None) -> dict:
    """Tonight's plan to everyone who asked for it and hasn't had it, once it is due."""
    now = now or datetime.now(UTC)
    when = due(now)
    if when is None:
        return {"status": "not_due"}
    night, sunset = when
    waiting = {p.user_id for p in _opted_in(db)} - _sent_for(db, night)
    if not waiting:
        return {"status": "nobody_waiting", "night": night.isoformat()}

    # Worked out before the lock: the weather lookup ends the transaction (and a
    # transaction's lock with it).
    plan = recorded_plan(db, night) or live_plan(db)
    plan["wind"] = _wind(db, plan, now)
    with use(DEFAULT):
        title, _ = compose_plan(plan, sunset)

    db.execute(text("SELECT pg_advisory_xact_lock(:ns, :night)"),
               {"ns": _LOCK, "night": night.toordinal()})
    done = _sent_for(db, night)
    prefs = [p for p in _opted_in(db) if p.user_id not in done]
    if not prefs:
        db.commit()
        return {"status": "nobody_waiting", "night": night.isoformat()}
    on = hold.sitting(db, now, [p.user_id for p in prefs])
    # Each in its recipient's language.
    langs = push.languages(db, [p.user_id for p in prefs])
    # A send that reached no phone earlier this evening is sent again on its own row.
    again = {n.user_id: n for n in db.scalars(
        _tonights(night).where(Notification.push_status.in_(RETRY))).all()}
    notes: list[Notification] = []
    for p in prefs:
        why = hold.reason(p, p.user_id, now, on)
        detail = {"night": night.isoformat(), "source": plan["source"]}
        n = again.get(p.user_id)
        if n is None:
            n = Notification(user_id=p.user_id, kind="plan", url=PLAN_URL)
            db.add(n)
        else:
            detail["tries"] = int((n.detail or {}).get("tries") or 1) + 1
        with use(langs.get(p.user_id)):
            n.title, n.body = compose_plan(plan, sunset)
        n.created_at = now
        n.detail = {**detail, "skipped": why} if why else detail
        # None while it is on its way: a run after this one finds the row and stops.
        n.push_status = "skipped" if why else None
        if not why:
            notes.append(n)
    db.commit()  # written before any push: a run after this one finds them and stops

    pushed = 0
    for n in notes:
        result = push.send_to_user(db, n.user_id, {
            "title": n.title, "body": n.body, "url": n.url, "tag": "plan",
            "renotify": True, "at": now.isoformat(),
        })
        n.push_status = push.delivery(result)
        pushed += result["sent"]
    db.commit()
    out = {"status": "done", "night": night.isoformat(), "people": len(prefs),
           "pushed": pushed, "source": plan["source"], "title": title}
    log.info("notify.plan", **out)
    return out
