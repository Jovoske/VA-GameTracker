"""Diagnostics that try to falsify the app's own claims, using data already stored.

**Detection radius vs temperature.** A PIR sensor fires on the thermal contrast
between an animal and the air around it. On a 28-30 degree Iberian night that
contrast collapses and the effective detection radius shrinks, so the camera sees
*less far*, not the animals move *less*. A naive correlation reads that as
"cooler nights have more activity" and sells sensor physics as ecology.

This is testable for free. `Detection.bbox` is populated and apparent bounding-box
area is a proxy for how close the animal was. If animals are detected
systematically *closer* on warm nights, the sampled area shrank and any
temperature-driven "activity" finding is refuted by the estate's own data.

The test is deliberately blunt — a warm/cool tercile split on median bbox area,
plus Spearman's rho — because a subtle method would imply more confidence than one
season supports. It reports "not enough data" freely rather than guessing.
"""
from __future__ import annotations

import math

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Detection, EnvSnapshot, Image

MIN_PAIRS = 40


def _bbox_area(bbox: dict | None) -> float | None:
    """Fractional area of the frame, from the stored {'xyxy': [...]} box."""
    if not bbox:
        return None
    xy = bbox.get("xyxy") if isinstance(bbox, dict) else None
    if not xy or len(xy) != 4:
        return None
    x1, y1, x2, y2 = xy
    w, h = max(0.0, x2 - x1), max(0.0, y2 - y1)
    area = w * h
    return area if area > 0 else None


def _spearman(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0

    def rank(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


def detection_radius_vs_temperature(db: Session) -> dict:
    rows = db.execute(
        select(Detection.bbox, EnvSnapshot.temp_c)
        .join(Image, Image.id == Detection.image_id)
        .join(
            EnvSnapshot,
            (EnvSnapshot.camera_id == Image.camera_id)
            & (EnvSnapshot.observed_at == Image.captured_at),
        )
        .where(Detection.bbox.isnot(None), EnvSnapshot.temp_c.isnot(None))
    ).all()

    pairs = [(float(t), a) for b, t in rows if (a := _bbox_area(b)) is not None]
    if len(pairs) < MIN_PAIRS:
        return {
            "status": "insufficient_data",
            "pairs": len(pairs),
            "needed": MIN_PAIRS,
            "statement": (
                f"Only {len(pairs)} detections have both a bounding box and a matching "
                f"temperature; {MIN_PAIRS} are needed before this says anything."
            ),
        }

    pairs.sort(key=lambda p: p[0])
    k = max(1, len(pairs) // 3)
    cool = [a for _, a in pairs[:k]]
    warm = [a for _, a in pairs[-k:]]

    def median(v: list[float]) -> float:
        s = sorted(v)
        m = len(s) // 2
        return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2

    cool_med, warm_med = median(cool), median(warm)
    rho = _spearman([t for t, _ in pairs], [a for _, a in pairs])
    shrunk = warm_med > cool_med * 1.15  # bigger boxes on warm nights = closer animals

    if shrunk:
        statement = (
            f"On the warmest third of nights animals are detected {warm_med / cool_med:.1f}x "
            "closer to the camera than on the coolest third. The sampled area shrinks as it "
            "warms, so any 'cooler nights are busier' finding is a property of the sensor, "
            "not of the animals. Temperature must not be used as an activity driver."
        )
    else:
        statement = (
            "Apparent detection distance does not change materially with temperature in this "
            "data, so the PIR-range explanation is not supported here. That does not make a "
            "temperature effect real — it only fails to refute one."
        )

    return {
        "status": "ok",
        "pairs": len(pairs),
        "cool_median_area": round(cool_med, 5),
        "warm_median_area": round(warm_med, 5),
        "ratio_warm_over_cool": round(warm_med / cool_med, 3) if cool_med else None,
        "spearman_rho": round(rho, 3),
        "detection_radius_shrinks_when_warm": shrunk,
        "statement": statement,
    }
