"""Auto-Tab (2026-08-28, Tim-Wunsch) - Fahrzeug (inkl. 3D-Modell-Upload),
Tanklog, eigenständige Auto-Ziele-Liste. Eigener Router analog zu den
übrigen fachlichen Modulen (siehe routers/goals.py-Docstring)."""

import os
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models, schemas, crud, auth
from ..database import get_db

vehicle_router = APIRouter(prefix="/api")

DATA_DIR = os.environ.get("DATA_DIR", "/data")
VEHICLE_MODEL_DIR = os.path.join(DATA_DIR, "uploads", "vehicle-models")
os.makedirs(VEHICLE_MODEL_DIR, exist_ok=True)
# Nur echte 3D-Modell-Formate - glTF-Binär (.glb, ein einzelnes File) und das
# JSON-Textformat (.gltf, das aber i.d.R. externe .bin/-Texturen referenziert
# und deshalb hier bewusst NICHT unterstützt wird, um kein Multi-Datei-Upload
# bauen zu müssen). Three.js liest beide Formate mit demselben GLTFLoader.
VEHICLE_MODEL_ALLOWED_EXTENSIONS = {".glb"}


def _get_vehicle(db: Session, space_id: int) -> models.Vehicle:
    return crud.get_or_create_vehicle(db, space_id)


@vehicle_router.get("/vehicle", response_model=schemas.VehicleOut)
def get_vehicle(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.vehicle_out(_get_vehicle(db, space_id))


@vehicle_router.put("/vehicle", response_model=schemas.VehicleOut)
def update_vehicle(data: schemas.VehicleUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    vehicle = crud.update_vehicle(db, _get_vehicle(db, space_id), data)
    return crud.vehicle_out(vehicle)


@vehicle_router.post("/vehicle/model", response_model=schemas.VehicleOut)
def upload_vehicle_model(file: UploadFile = File(...), db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in VEHICLE_MODEL_ALLOWED_EXTENSIONS:
        raise HTTPException(400, "Nicht unterstütztes Format. Bitte als .glb hochladen (glTF-Binär).")
    vehicle = _get_vehicle(db, space_id)
    # Eigens erzeugter Dateiname (kein roher Original-Name im Pfad) - gleiches
    # Path-Injection-Schutzmuster wie beim Beleg-Upload (siehe main.py:
    # upload_receipt).
    safe_name = f"{vehicle.id}_{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(VEHICLE_MODEL_DIR, safe_name)
    with open(dest_path, "wb") as buffer:
        import shutil
        shutil.copyfileobj(file.file, buffer)

    old_filename = vehicle.model_3d_filename
    vehicle = crud.set_vehicle_model_3d(db, vehicle, safe_name)
    if old_filename:
        old_path = os.path.join(VEHICLE_MODEL_DIR, old_filename)
        if os.path.exists(old_path):
            os.remove(old_path)
    return crud.vehicle_out(vehicle)


@vehicle_router.delete("/vehicle/model", response_model=schemas.VehicleOut)
def delete_vehicle_model(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    vehicle = _get_vehicle(db, space_id)
    if vehicle.model_3d_filename:
        old_path = os.path.join(VEHICLE_MODEL_DIR, vehicle.model_3d_filename)
        if os.path.exists(old_path):
            os.remove(old_path)
        vehicle = crud.set_vehicle_model_3d(db, vehicle, None)
    return crud.vehicle_out(vehicle)


@vehicle_router.get("/vehicle/model/{filename}")
def get_vehicle_model_file(filename: str):
    # Gleiches zweistufiges Absicherungsmuster wie routers/analytics.py:
    # get_receipt (os.path.basename() + Prüfung, dass der aufgelöste Pfad
    # wirklich innerhalb von VEHICLE_MODEL_DIR liegt).
    safe_name = os.path.basename(filename)
    path = os.path.realpath(os.path.join(VEHICLE_MODEL_DIR, safe_name))
    if not path.startswith(os.path.realpath(VEHICLE_MODEL_DIR) + os.sep):
        raise HTTPException(404, "3D-Modell nicht gefunden")
    if not os.path.exists(path):
        raise HTTPException(404, "3D-Modell nicht gefunden")
    return FileResponse(path, media_type="model/gltf-binary")


# ---------------- Tanklog ----------------
@vehicle_router.get("/vehicle/fuel-entries", response_model=List[schemas.VehicleFuelEntryOut])
def list_fuel_entries(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    vehicle = _get_vehicle(db, space_id)
    return crud.get_fuel_entries(db, vehicle.id)


@vehicle_router.get("/vehicle/fuel-summary")
def get_fuel_summary(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    vehicle = _get_vehicle(db, space_id)
    return crud.fuel_summary(db, vehicle.id)


@vehicle_router.post("/vehicle/fuel-entries", response_model=schemas.VehicleFuelEntryOut)
def create_fuel_entry(data: schemas.VehicleFuelEntryCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    vehicle = _get_vehicle(db, space_id)
    entry = crud.create_fuel_entry(db, vehicle.id, data)
    return crud.get_fuel_entries(db, vehicle.id)[0] if entry else None  # neu berechnete Verbrauchswerte statt roher Zeile


@vehicle_router.put("/vehicle/fuel-entries/{entry_id}", response_model=schemas.VehicleFuelEntryOut)
def update_fuel_entry(entry_id: int, data: schemas.VehicleFuelEntryUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    vehicle = _get_vehicle(db, space_id)
    entry = crud.get_fuel_entry(db, entry_id, vehicle.id)
    if not entry:
        raise HTTPException(404, "Tankeintrag nicht gefunden")
    crud.update_fuel_entry(db, entry, data)
    return next(e for e in crud.get_fuel_entries(db, vehicle.id) if e.id == entry_id)


@vehicle_router.delete("/vehicle/fuel-entries/{entry_id}")
def delete_fuel_entry(entry_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    vehicle = _get_vehicle(db, space_id)
    entry = crud.get_fuel_entry(db, entry_id, vehicle.id)
    if not entry:
        raise HTTPException(404, "Tankeintrag nicht gefunden")
    crud.delete_fuel_entry(db, entry)
    return {"ok": True}


# ---------------- Auto-Ziele ----------------
@vehicle_router.get("/vehicle/goals", response_model=List[schemas.VehicleGoalOut])
def list_vehicle_goals(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    vehicle = _get_vehicle(db, space_id)
    return crud.get_vehicle_goals(db, vehicle.id)


@vehicle_router.post("/vehicle/goals", response_model=schemas.VehicleGoalOut)
def create_vehicle_goal(data: schemas.VehicleGoalCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    vehicle = _get_vehicle(db, space_id)
    return crud.create_vehicle_goal(db, vehicle.id, data)


@vehicle_router.put("/vehicle/goals/{goal_id}", response_model=schemas.VehicleGoalOut)
def update_vehicle_goal(goal_id: int, data: schemas.VehicleGoalUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    vehicle = _get_vehicle(db, space_id)
    goal = crud.get_vehicle_goal(db, goal_id, vehicle.id)
    if not goal:
        raise HTTPException(404, "Auto-Ziel nicht gefunden")
    return crud.update_vehicle_goal(db, goal, data)


@vehicle_router.delete("/vehicle/goals/{goal_id}")
def delete_vehicle_goal(goal_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    vehicle = _get_vehicle(db, space_id)
    goal = crud.get_vehicle_goal(db, goal_id, vehicle.id)
    if not goal:
        raise HTTPException(404, "Auto-Ziel nicht gefunden")
    crud.delete_vehicle_goal(db, goal)
    return {"ok": True}


# ---------------- Fahrtenbuch (models.VehicleTrip) ----------------
@vehicle_router.get("/vehicle/trips")
def list_vehicle_trips(
    purpose: str = None, source_vehicle: str = None, year: int = None, month: int = None,
    db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id),
):
    v = _get_vehicle(db, space_id)
    return crud.get_vehicle_trips(db, v.id, purpose=purpose, source_vehicle=source_vehicle,
                                  year=year, month=month)


@vehicle_router.get("/vehicle/trips/summary")
def vehicle_trips_summary(source_vehicle: str = None, db: Session = Depends(get_db),
                          space_id: int = Depends(auth.get_active_space_id)):
    v = _get_vehicle(db, space_id)
    return crud.vehicle_trip_summary(db, v.id, source_vehicle=source_vehicle)


@vehicle_router.patch("/vehicle/trips/{trip_id}")
def patch_vehicle_trip(trip_id: int, data: schemas.VehicleTripUpdate, db: Session = Depends(get_db),
                       space_id: int = Depends(auth.get_active_space_id)):
    v = _get_vehicle(db, space_id)
    out = crud.set_vehicle_trip(db, trip_id, v.id, purpose=data.purpose, note=data.note)
    if not out:
        raise HTTPException(404, "Fahrt nicht gefunden")
    return out


@vehicle_router.delete("/vehicle/trips/{trip_id}")
def remove_vehicle_trip(trip_id: int, db: Session = Depends(get_db),
                        space_id: int = Depends(auth.get_active_space_id)):
    v = _get_vehicle(db, space_id)
    if not crud.delete_vehicle_trip(db, trip_id, v.id):
        raise HTTPException(404, "Fahrt nicht gefunden")
    return {"ok": True}


@vehicle_router.get("/vehicle/trips/{trip_id}/track")
def vehicle_trip_track(trip_id: int, db: Session = Depends(get_db),
                       space_id: int = Depends(auth.get_active_space_id)):
    v = _get_vehicle(db, space_id)
    path = crud.get_vehicle_trip_track_path(db, trip_id, v.id)
    if not path:
        raise HTTPException(404, "Kein Track hinterlegt")
    return FileResponse(path, filename=os.path.basename(path))


@vehicle_router.post("/vehicle/trips/import")
async def import_vehicle_trips_file(
    file: UploadFile = File(...), db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    """Speedometer-Backup (.speedometer / JSON) hochladen und Fahrten anlegen.
    Duplikate (gleiche Fahrt-ID) werden übersprungen."""
    import json
    from .. import speedometer
    raw = await file.read()
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        raise HTTPException(400, "Datei ist kein gültiges JSON (Speedometer-Backup).")
    if speedometer.looks_like_speedometer_backup(payload):
        trips = speedometer.parse_speedometer_backup(payload)
    elif isinstance(payload, dict) and isinstance(payload.get("trips"), list):
        trips = payload["trips"]
    elif isinstance(payload, list):
        trips = payload
    else:
        raise HTTPException(400, "Kein erkanntes Fahrten-Format.")
    result = crud.import_vehicle_trips(db, space_id, trips, source="upload")
    return {"ok": True, **result}
