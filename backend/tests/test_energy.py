"""Server-Stromverbrauch (routers/energy.py + models.PowerReading)."""
from datetime import datetime, timedelta

from app import models
from app.database import SessionLocal
from app.routers.energy import _kwh, energy_summary


def test_kwh_trapezoidal():
    t0 = datetime(2027, 1, 1, 0, 0)
    # 2 h konstant 100 W = 0,2 kWh
    rows = [(t0, 100.0), (t0 + timedelta(hours=2), 100.0)]
    assert abs(_kwh(rows) - 0.2) < 1e-6
    # Rampe 0 -> 200 W über 1 h = Mittel 100 W = 0,1 kWh
    rows = [(t0, 0.0), (t0 + timedelta(hours=1), 200.0)]
    assert abs(_kwh(rows) - 0.1) < 1e-6


def test_kwh_ignores_large_gaps():
    t0 = datetime(2027, 1, 1, 0, 0)
    rows = [(t0, 100.0), (t0 + timedelta(hours=5), 100.0)]  # Lücke > 1 h
    assert _kwh(rows) == 0.0


def test_summary_no_data():
    db = SessionLocal()
    try:
        out = energy_summary(db)
        assert out["has_data"] is False and "price_eur_kwh" in out
    finally:
        db.close()


def test_summary_with_samples():
    db = SessionLocal()
    try:
        from app import auth
        s = auth.get_or_create_settings(db)
        s.homeassistant_electricity_price = 0.40
        db.commit()
        now = datetime.utcnow()
        for i in range(9):  # 2 h à 15 min, konstant 120 W
            db.add(models.PowerReading(ts=now - timedelta(minutes=15 * i), watts=120.0))
        db.commit()
        out = energy_summary(db)
        assert out["has_data"] is True
        assert out["current_w"] == 120.0
        assert out["today_kwh"] > 0
        assert abs(out["today_eur"] - out["today_kwh"] * 0.40) < 0.01
        assert len(out["points"]) == 14
    finally:
        db.close()
