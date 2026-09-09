"""Device-CRUD (native Agent-/Sync-Geräte) - eigenes Modul analog zu den
übrigen crud_*.py (siehe crud_vehicle.py-Kopf). crud.py importiert die Namen
zurück, damit routers/devices.py sie unter dem gewohnten `crud.`-Stil nutzen
kann. Siehe models.Device-Docstring für den Hintergrund.
"""

import secrets
from datetime import datetime

from sqlalchemy.orm import Session

from . import auth, models


def list_devices(db: Session) -> list[models.Device]:
    return db.query(models.Device).order_by(models.Device.created_at.desc()).all()


def create_device(db: Session, name: str) -> tuple[models.Device, str]:
    """Legt ein neues Gerät an und gibt (Device, Klartext-Token) zurück - das
    Token ist danach nirgends mehr im Klartext abrufbar, nur noch als Hash."""
    token = secrets.token_urlsafe(32)
    device = models.Device(
        name=name.strip() or "Gerät",
        token_hash=auth.hash_password(token),
        created_at=datetime.utcnow(),
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return device, token


def revoke_device(db: Session, device_id: int) -> models.Device | None:
    device = db.query(models.Device).get(device_id)
    if not device:
        return None
    device.revoked_at = datetime.utcnow()
    db.commit()
    return device


def authenticate_device(db: Session, token: str) -> models.Device | None:
    """Prüft ein Klartext-Token gegen alle nicht widerrufenen Geräte-Hashes
    und aktualisiert last_seen_at bei Erfolg. Linear über alle Geräte, weil
    der Token selbst (anders als z.B. ein Username) kein Suchschlüssel sein
    darf - in der erwarteten Größenordnung (eigene Geräte, keine Nutzerzahl)
    unproblematisch."""
    if not token:
        return None
    for device in db.query(models.Device).filter(models.Device.revoked_at.is_(None)).all():
        if auth.verify_password(token, device.token_hash):
            device.last_seen_at = datetime.utcnow()
            db.commit()
            return device
    return None
