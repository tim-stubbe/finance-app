"""Auto-Tab (2026-08-28, Tim-Wunsch) - eigenes Modul analog zu den bereits
modularisierten crud_*.py-Dateien (siehe ROADMAP.md), statt crud.py weiter
wachsen zu lassen. Deckt drei Teile ab: das Fahrzeug selbst (inkl.
3D-Modell-Dateiname), das Tanklog (Verbrauch/Kosten) und eine eigenständige
Auto-Ziele-Liste (bewusst NICHT das normale Ziele-System, auf Tim-Wunsch
getrennt).

crud.py importiert alle hier definierten Namen zurück, damit main.py/
routers/*.py sie unter dem gewohnten `crud.`-Aufrufstil nutzen können."""

from sqlalchemy.orm import Session

from . import models, schemas


# ---------------- Fahrzeug (ein Singleton pro Bereich, wie Settings) ----------------
def get_or_create_vehicle(db: Session, space_id: int) -> models.Vehicle:
    vehicle = db.query(models.Vehicle).filter_by(space_id=space_id).first()
    if not vehicle:
        vehicle = models.Vehicle(space_id=space_id, name="Mein Auto")
        db.add(vehicle)
        db.commit()
        db.refresh(vehicle)
    return vehicle


def vehicle_out(vehicle: models.Vehicle) -> schemas.VehicleOut:
    return schemas.VehicleOut(
        id=vehicle.id, name=vehicle.name,
        model_3d_url=f"/api/vehicle/model/{vehicle.model_3d_filename}" if vehicle.model_3d_filename else None,
    )


def update_vehicle(db: Session, vehicle: models.Vehicle, data: schemas.VehicleUpdate) -> models.Vehicle:
    vehicle.name = data.name.strip() or "Mein Auto"
    db.commit()
    return vehicle


def set_vehicle_model_3d(db: Session, vehicle: models.Vehicle, filename: str | None) -> models.Vehicle:
    vehicle.model_3d_filename = filename
    db.commit()
    return vehicle


# ---------------- Tanklog ----------------
def _enrich_fuel_entries(entries: list[models.VehicleFuelEntry]) -> list[schemas.VehicleFuelEntryOut]:
    """Verbrauch/Kosten pro km werden erst hier beim Ausliefern berechnet
    (nicht gespeichert) - reine Ableitung aus der Kilometerstand-Differenz
    zum VORHERIGEN VOLLEN Tankvorgang (Standard-Methode: nur zwischen zwei
    vollen Tanks lässt sich der tatsächliche Verbrauch in dieser Zeitspanne
    bestimmen, ein Zwischen-Teiltank würde die Rechnung verfälschen)."""
    sorted_entries = sorted(entries, key=lambda e: (e.date, e.id))
    out: list[schemas.VehicleFuelEntryOut] = []
    last_full: models.VehicleFuelEntry | None = None
    for e in sorted_entries:
        consumption = None
        cost_per_km = None
        if last_full and e.odometer_km > last_full.odometer_km:
            km_diff = e.odometer_km - last_full.odometer_km
            if e.full_tank and e.liters:
                consumption = round(e.liters / km_diff * 100, 2)
            cost_per_km = round(e.total_cost / km_diff, 3)
        out.append(schemas.VehicleFuelEntryOut(
            id=e.id, date=e.date, odometer_km=e.odometer_km, liters=e.liters,
            total_cost=e.total_cost, full_tank=e.full_tank, notes=e.notes,
            consumption_l_per_100km=consumption, cost_per_km=cost_per_km,
        ))
        if e.full_tank:
            last_full = e
    out.reverse()  # neueste zuerst fuers Frontend
    return out


def get_fuel_entries(db: Session, vehicle_id: int) -> list[schemas.VehicleFuelEntryOut]:
    entries = db.query(models.VehicleFuelEntry).filter_by(vehicle_id=vehicle_id).all()
    return _enrich_fuel_entries(entries)


def create_fuel_entry(db: Session, vehicle_id: int, data: schemas.VehicleFuelEntryCreate) -> models.VehicleFuelEntry:
    entry = models.VehicleFuelEntry(vehicle_id=vehicle_id, **data.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def get_fuel_entry(db: Session, entry_id: int, vehicle_id: int) -> models.VehicleFuelEntry | None:
    return db.query(models.VehicleFuelEntry).filter_by(id=entry_id, vehicle_id=vehicle_id).first()


def update_fuel_entry(db: Session, entry: models.VehicleFuelEntry, data: schemas.VehicleFuelEntryUpdate) -> models.VehicleFuelEntry:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(entry, key, value)
    db.commit()
    return entry


def delete_fuel_entry(db: Session, entry: models.VehicleFuelEntry) -> None:
    db.delete(entry)
    db.commit()


def fuel_summary(db: Session, vehicle_id: int) -> dict:
    """Kennzahlen für die vier Ecken um das 3D-Modell im Auto-Tab - letzter
    Kilometerstand, Ø-Verbrauch, Kosten pro km, Gesamtkosten seit Beginn."""
    entries = get_fuel_entries(db, vehicle_id)  # bereits neueste zuerst
    if not entries:
        return {
            "last_odometer_km": None, "avg_consumption_l_per_100km": None,
            "avg_cost_per_km": None, "total_cost": 0.0, "entry_count": 0,
        }
    consumptions = [e.consumption_l_per_100km for e in entries if e.consumption_l_per_100km is not None]
    cost_per_kms = [e.cost_per_km for e in entries if e.cost_per_km is not None]
    return {
        "last_odometer_km": entries[0].odometer_km,
        "avg_consumption_l_per_100km": round(sum(consumptions) / len(consumptions), 2) if consumptions else None,
        "avg_cost_per_km": round(sum(cost_per_kms) / len(cost_per_kms), 3) if cost_per_kms else None,
        "total_cost": round(sum(e.total_cost for e in entries), 2),
        "entry_count": len(entries),
    }


# ---------------- Auto-Ziele (eigenständig, siehe models.VehicleGoal) ----------------
def get_vehicle_goals(db: Session, vehicle_id: int) -> list[models.VehicleGoal]:
    return (
        db.query(models.VehicleGoal)
        .filter_by(vehicle_id=vehicle_id)
        .order_by(models.VehicleGoal.done, models.VehicleGoal.created_at.desc())
        .all()
    )


def create_vehicle_goal(db: Session, vehicle_id: int, data: schemas.VehicleGoalCreate) -> models.VehicleGoal:
    goal = models.VehicleGoal(vehicle_id=vehicle_id, **data.model_dump())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def get_vehicle_goal(db: Session, goal_id: int, vehicle_id: int) -> models.VehicleGoal | None:
    return db.query(models.VehicleGoal).filter_by(id=goal_id, vehicle_id=vehicle_id).first()


def update_vehicle_goal(db: Session, goal: models.VehicleGoal, data: schemas.VehicleGoalUpdate) -> models.VehicleGoal:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(goal, key, value)
    db.commit()
    return goal


def delete_vehicle_goal(db: Session, goal: models.VehicleGoal) -> None:
    db.delete(goal)
    db.commit()


# ---------------- Fahrtenbuch (models.VehicleTrip, Import z.B. aus Speedometer) ----
import hashlib as _hashlib
import os as _os
import re as _re
from datetime import date as _date, datetime as _dt

_TRIP_DIR = _os.path.join(_os.environ.get("DATA_DIR", "/data"), "uploads", "vehicle-tracks")

_PURPOSES = ("geschaeftlich", "privat", "unbekannt")


def _safe_track_path(track_filename: str) -> str | None:
    """Absoluter Pfad einer Track-Datei - NUR wenn er wirklich innerhalb von
    _TRIP_DIR liegt (Schutz gegen vergiftete track_filename-Werte / Path
    Traversal). Sonst None."""
    if not track_filename or "/" in track_filename or "\\" in track_filename or track_filename in (".", ".."):
        return None
    base = _os.path.realpath(_TRIP_DIR)
    full = _os.path.realpath(_os.path.join(base, track_filename))
    if full == base or not full.startswith(base + _os.sep):
        return None
    return full


def _trip_out(t: models.VehicleTrip) -> dict:
    return {
        "id": t.id, "external_id": t.external_id, "source": t.source,
        "source_vehicle": t.source_vehicle,
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "ended_at": t.ended_at.isoformat() if t.ended_at else None,
        "distance_km": round(t.distance_km or 0.0, 2),
        "duration_s": t.duration_s,
        "avg_speed_kmh": t.avg_speed_kmh, "max_speed_kmh": t.max_speed_kmh,
        "elevation_gain_m": t.elevation_gain_m,
        "start_location": t.start_location, "end_location": t.end_location,
        "odometer_start_km": t.odometer_start_km, "odometer_end_km": t.odometer_end_km,
        "purpose": t.purpose or "unbekannt", "note": t.note,
        "has_track": bool(t.track_filename),
    }


def get_vehicle_trips(db: Session, vehicle_id: int, *, purpose=None, source_vehicle=None,
                      year=None, month=None, limit: int = 2000) -> list[dict]:
    q = db.query(models.VehicleTrip).filter_by(vehicle_id=vehicle_id)
    if purpose in _PURPOSES:
        q = q.filter(models.VehicleTrip.purpose == purpose)
    if source_vehicle:
        q = q.filter(models.VehicleTrip.source_vehicle == source_vehicle)
    if year:
        start = _dt(int(year), int(month or 1), 1)
        end = _dt(int(year) + (1 if not month else 0), (int(month) + 1) if month and int(month) < 12 else 1, 1) \
            if month else _dt(int(year) + 1, 1, 1)
        q = q.filter(models.VehicleTrip.started_at >= start, models.VehicleTrip.started_at < end)
    rows = q.order_by(models.VehicleTrip.started_at.desc()).limit(limit).all()
    return [_trip_out(t) for t in rows]


def vehicle_trip_summary(db: Session, vehicle_id: int, *, source_vehicle=None) -> dict:
    q = db.query(models.VehicleTrip).filter_by(vehicle_id=vehicle_id)
    if source_vehicle:
        q = q.filter(models.VehicleTrip.source_vehicle == source_vehicle)
    rows = q.all()
    if not rows:
        return {"trip_count": 0, "total_km": 0.0, "business_km": 0.0, "private_km": 0.0,
                "unknown_km": 0.0, "this_month_km": 0.0, "vehicles": [], "first_date": None, "last_date": None}
    today = _date.today()
    by_purpose = {"geschaeftlich": 0.0, "privat": 0.0, "unbekannt": 0.0}
    this_month = 0.0
    for t in rows:
        km = t.distance_km or 0.0
        by_purpose[t.purpose if t.purpose in by_purpose else "unbekannt"] += km
        if t.started_at and t.started_at.year == today.year and t.started_at.month == today.month:
            this_month += km
    dates = [t.started_at for t in rows if t.started_at]
    return {
        "trip_count": len(rows),
        "total_km": round(sum(t.distance_km or 0.0 for t in rows), 1),
        "business_km": round(by_purpose["geschaeftlich"], 1),
        "private_km": round(by_purpose["privat"], 1),
        "unknown_km": round(by_purpose["unbekannt"], 1),
        "this_month_km": round(this_month, 1),
        "vehicles": sorted({t.source_vehicle for t in rows if t.source_vehicle}),
        "first_date": min(dates).date().isoformat() if dates else None,
        "last_date": max(dates).date().isoformat() if dates else None,
    }


def set_vehicle_trip(db: Session, trip_id: int, vehicle_id: int, *, purpose=None, note=None):
    t = db.query(models.VehicleTrip).filter_by(id=trip_id, vehicle_id=vehicle_id).first()
    if not t:
        return None
    if purpose is not None and purpose in _PURPOSES:
        t.purpose = purpose
    if note is not None:
        t.note = note.strip() or None
    db.commit()
    return _trip_out(t)


def delete_vehicle_trip(db: Session, trip_id: int, vehicle_id: int) -> bool:
    t = db.query(models.VehicleTrip).filter_by(id=trip_id, vehicle_id=vehicle_id).first()
    if not t:
        return False
    p = _safe_track_path(t.track_filename)
    if p:
        try:
            _os.remove(p)
        except OSError:
            pass
    db.delete(t)
    db.commit()
    return True


def get_vehicle_trip_track_path(db: Session, trip_id: int, vehicle_id: int):
    t = db.query(models.VehicleTrip).filter_by(id=trip_id, vehicle_id=vehicle_id).first()
    if not t or not t.track_filename:
        return None
    p = _safe_track_path(t.track_filename)
    return p if (p and _os.path.exists(p)) else None


def import_vehicle_trips(db: Session, space_id: int, trips: list[dict], *, source: str = "webhook") -> dict:
    """Neutrale Fahrten-Dicts (siehe speedometer.parse_speedometer_backup)
    -> models.VehicleTrip. Dedup über (vehicle_id, external_id); vorhandene
    Fahrten werden NICHT überschrieben (die geschäftlich/privat-Einordnung des
    Nutzers bleibt). Rückgabe: {imported, skipped}."""
    vehicle = get_or_create_vehicle(db, space_id)
    _os.makedirs(_TRIP_DIR, exist_ok=True)
    existing = {
        e for (e,) in db.query(models.VehicleTrip.external_id)
        .filter(models.VehicleTrip.vehicle_id == vehicle.id,
                models.VehicleTrip.external_id.isnot(None)).all()
    }
    imported = skipped = 0
    for raw in trips or []:
        ext = raw.get("external_id")
        started = raw.get("started_at")
        if isinstance(started, str):
            try:
                started = _dt.fromisoformat(started)
            except ValueError:
                started = None
        if started is None:
            skipped += 1
            continue
        if ext and ext in existing:
            skipped += 1
            continue
        track_name = None
        tb = raw.get("track_bytes")
        if tb:
            # Dateinamen IMMER serverseitig ableiten - nie aus dem Manifest
            # (Path Traversal). Hash über external_id bzw. Startzeit+Distanz.
            safe_ext = _re.sub(r"[^a-z0-9]", "", str(raw.get("track_ext", "bin")).lower())[:8] or "bin"
            seed = str(ext) if ext else f"{started.isoformat()}|{raw.get('distance_km')}"
            digest = _hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
            candidate = f"{digest}.{safe_ext}"
            full = _safe_track_path(candidate)
            if full:
                try:
                    with open(full, "wb") as fh:
                        fh.write(tb)
                    track_name = candidate
                except OSError:
                    track_name = None
        ended = raw.get("ended_at")
        if isinstance(ended, str):
            try:
                ended = _dt.fromisoformat(ended)
            except ValueError:
                ended = None
        purpose = raw.get("purpose")
        db.add(models.VehicleTrip(
            vehicle_id=vehicle.id, external_id=ext,
            source=raw.get("source") or source,
            source_vehicle=raw.get("source_vehicle"),
            started_at=started, ended_at=ended,
            distance_km=float(raw.get("distance_km") or 0.0),
            duration_s=raw.get("duration_s"),
            avg_speed_kmh=raw.get("avg_speed_kmh"), max_speed_kmh=raw.get("max_speed_kmh"),
            elevation_gain_m=raw.get("elevation_gain_m"),
            start_location=raw.get("start_location"), end_location=raw.get("end_location"),
            start_lat=raw.get("start_lat"), start_lon=raw.get("start_lon"),
            end_lat=raw.get("end_lat"), end_lon=raw.get("end_lon"),
            odometer_start_km=raw.get("odometer_start_km"), odometer_end_km=raw.get("odometer_end_km"),
            purpose=purpose if purpose in _PURPOSES else "unbekannt",
            note=raw.get("note"), track_filename=track_name,
        ))
        if ext:
            existing.add(ext)
        imported += 1
    db.commit()
    return {"imported": imported, "skipped": skipped}
