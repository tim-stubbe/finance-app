"""Native Geräte-Verwaltung (P1 aus der Agent-v1-Roadmap, siehe
models.Device-Docstring). Pairing/Auflisten/Widerrufen läuft über
Web-Session-Auth (wie die restlichen Settings-Endpunkte) - das eigentliche
Gerät bekommt danach nur noch das einmalig ausgegebene Klartext-Token, nie
wieder die Session.

Ersetzt (noch) NICHT das bestehende X-Sync-Secret in sync.py - rein additiv,
siehe ROADMAP/Obsidian-Notiz für die geplante schrittweise Migration."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import crud
from ..database import get_db

devices_router = APIRouter(prefix="/api/devices")


class DeviceCreate(BaseModel):
    name: str


class DeviceOut(BaseModel):
    id: int
    name: str
    created_at: str
    last_seen_at: str | None = None
    revoked: bool


def _serialize(device) -> dict:
    return {
        "id": device.id,
        "name": device.name,
        "created_at": device.created_at.isoformat() if device.created_at else None,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "revoked": device.revoked_at is not None,
    }


@devices_router.get("")
def list_devices(db: Session = Depends(get_db)):
    return [_serialize(d) for d in crud.list_devices(db)]


@devices_router.post("")
def create_device(data: DeviceCreate, db: Session = Depends(get_db)):
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(400, "name fehlt")
    device, token = crud.create_device(db, name)
    # Klartext-Token nur in dieser einen Antwort - danach nicht mehr abrufbar,
    # gleiches Muster wie /settings/native-sync/regenerate.
    return {**_serialize(device), "token": token}


@devices_router.delete("/{device_id}")
def revoke_device(device_id: int, db: Session = Depends(get_db)):
    device = crud.revoke_device(db, device_id)
    if not device:
        raise HTTPException(404, "Gerät nicht gefunden")
    return _serialize(device)
