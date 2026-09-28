"""Tonight forecast — what the ground has been doing, and where to sit."""
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.forecasting.model import forecast_tonight
from app.i18n import t
from app.models import Stand, User

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/tonight")
def tonight(
    species: str | None = Query(
        None,
        description="Comma-separated species ids to rank by (e.g. wild_boar,red_deer). "
                    "Omit for every huntable species.",
    ),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ids = [s.strip() for s in species.split(",") if s.strip()] if species else None
    plan = forecast_tonight(db, species_ids=ids)
    # When it was worked out. A copy replayed with no signal still carries this, so
    # the phone can say "Plan from 14 h ago" instead of "just now" (audit J-05).
    return {**plan, "generated_at": datetime.now(UTC).isoformat()}


@router.get("/wind-week")
def wind_week(
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    stand: uuid.UUID | None = None,
) -> dict:
    """Each stand's wind hour by hour, 17:00 to 24:00, tonight and the next six
    evenings, and the one line a hunter reads first: "Right wind for Charca: tonight
    19–21 h, Thu, Sat" (forecasting/wind_week.py, feature 22).

    Each stand also carries `tonight`, its wind verdict at tonight's sit, as the map,
    Stands and Sit mode give it: Stands reads both from this one call. That one is
    worked out on every call, as theirs are; the week is kept for the hour.
    """
    from app.forecasting import wind_week as week_mod
    from app.forecasting.conditions import release, wind_verdict
    from app.forecasting.model import _tonight_conditions

    if stand is not None and db.get(Stand, stand) is None:
        raise HTTPException(404, t("stands.gone"))
    now = datetime.now(UTC)
    week = week_mod.week(db, stand_id=stand, now=now)
    release(db)
    try:
        cond = _tonight_conditions(now)
    except Exception:
        cond = {}
    by_id = {str(s.id): s for s in db.scalars(select(Stand)).all()}
    return {
        **week,
        # Copies: the week's rows are the hour's cached answer, shared by every caller.
        "stands": [{**row, "tonight": wind_verdict(db, by_id[row["stand_id"]], cond, now=now)}
                   for row in week["stands"] if row["stand_id"] in by_id],
        "sunset_local": cond.get("sunset_local"),
        "generated_at": now.isoformat(),
    }
