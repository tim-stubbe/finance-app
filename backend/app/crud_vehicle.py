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
