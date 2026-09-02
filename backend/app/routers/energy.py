"""Server-Stromverbrauch (siehe models.PowerReading, _scheduled_power_sample).

Rechnet aus den Watt-Samples per Trapezregel kWh und multipliziert mit
Settings.homeassistant_electricity_price. Alles read-only.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import auth, models
from ..database import get_db

energy_router = APIRouter(prefix="/api/energy")

_MAX_GAP_S = 3600  # Lücken > 1 h nicht integrieren (Sampler war aus)


def _kwh(rows) -> float:
    """Trapez-Integration einer nach ts sortierten [(ts, watts)]-Liste -> kWh."""
    total_wh = 0.0
    for (t0, w0), (t1, w1) in zip(rows, rows[1:]):
        dt = (t1 - t0).total_seconds()
        if 0 < dt <= _MAX_GAP_S:
            total_wh += (w0 + w1) / 2.0 * dt / 3600.0
    return total_wh / 1000.0


@energy_router.get("/summary")
def energy_summary(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    price = float(s.homeassistant_electricity_price or 0.35)
    now = datetime.utcnow()
    since = now - timedelta(days=35)
    rows = [(r.ts, r.watts) for r in
            db.query(models.PowerReading)
            .filter(models.PowerReading.ts >= since)
            .order_by(models.PowerReading.ts).all()]

    configured = bool((getattr(s, "homeassistant_power_entity", None) or "").strip())
    if not rows:
        return {"configured": configured, "has_data": False, "price_eur_kwh": price}

    def window(a, b=None):
        seg = [x for x in rows if x[0] >= a and (b is None or x[0] < b)]
        return _kwh(seg)

    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month0 = today0.replace(day=1)
    week0 = today0 - timedelta(days=today0.weekday())
    prev_week0 = week0 - timedelta(days=7)

    today_kwh = window(today0)
    month_kwh = window(month0)
    week_kwh = window(week0)
    prev_week_kwh = window(prev_week0, week0)

    points = []
    for i in range(13, -1, -1):
        d0 = today0 - timedelta(days=i)
        points.append({"date": d0.date().isoformat(), "kwh": round(window(d0, d0 + timedelta(days=1)), 3)})

    return {
        "configured": configured,
        "has_data": True,
        "price_eur_kwh": price,
        "current_w": round(rows[-1][1], 1),
        "current_ts": rows[-1][0].isoformat(),
        "today_kwh": round(today_kwh, 3),
        "today_eur": round(today_kwh * price, 2),
        "month_kwh": round(month_kwh, 2),
        "month_eur": round(month_kwh * price, 2),
        "week_kwh": round(week_kwh, 2),
        "prev_week_kwh": round(prev_week_kwh, 2),
        "points": points,
    }
