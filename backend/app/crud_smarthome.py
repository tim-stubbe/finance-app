"""Smart-Home-CRUD (Aliase + Aktions-Protokoll) - eigenes Modul analog zu den
uebrigen crud_*.py (siehe crud_vehicle.py-Kopf). crud.py importiert die
Namen zurueck, damit routers/smarthome.py und smarthome.py sie unter dem
gewohnten `crud.`-Stil nutzen koennen.

Bewusst NICHT an einen space_id gebunden: Home Assistant steuert die ganze
Wohnung, das ist keine Privat/Geschaeftlich-Trennung (anders als Konten).
"""

import json
from datetime import datetime

from sqlalchemy.orm import Session

from . import models


# ---------------- Aliase ----------------
def get_smarthome_aliases(db: Session):
    rows = db.query(models.SmartHomeAlias).order_by(models.SmartHomeAlias.phrase).all()
    return [{"id": r.id, "phrase": r.phrase, "entity_id": r.entity_id} for r in rows]


def create_smarthome_alias(db: Session, phrase: str, entity_id: str) -> models.SmartHomeAlias:
    alias = models.SmartHomeAlias(phrase=phrase.strip(), entity_id=entity_id.strip())
    db.add(alias)
    db.commit()
    db.refresh(alias)
    return alias


def delete_smarthome_alias(db: Session, alias_id: int) -> bool:
    alias = db.query(models.SmartHomeAlias).filter_by(id=alias_id).first()
    if not alias:
        return False
    db.delete(alias)
    db.commit()
    return True


# ---------------- Aktions-Protokoll ----------------
def log_smarthome_action(db: Session, *, text, intent, domain, service, entity_id,
                         data, ok, error, source) -> models.SmartHomeAction:
    row = models.SmartHomeAction(
        created_at=datetime.utcnow(),
        text=text,
        intent=intent,
        domain=domain,
        service=service,
        entity_id=entity_id,
        data_json=json.dumps(data or {}, ensure_ascii=False),
        ok=bool(ok),
        error=error,
        source=source,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------- Grundriss (Phase 3) ----------------
def get_floorplan(db: Session) -> dict:
    row = db.query(models.SmartHomeFloorplan).filter_by(id=1).first()
    if not row or not row.data_json:
        return {"rooms": [], "devices": []}
    try:
        data = json.loads(row.data_json)
    except ValueError:
        return {"rooms": [], "devices": []}
    data.setdefault("rooms", [])
    data.setdefault("devices", [])
    return data


def save_floorplan(db: Session, data: dict) -> dict:
    clean = {
        "rooms": data.get("rooms", []) or [],
        "devices": data.get("devices", []) or [],
    }
    row = db.query(models.SmartHomeFloorplan).filter_by(id=1).first()
    if not row:
        row = models.SmartHomeFloorplan(id=1)
        db.add(row)
    row.data_json = json.dumps(clean, ensure_ascii=False)
    db.commit()
    return clean


def get_smarthome_actions(db: Session, limit: int = 30):
    rows = (
        db.query(models.SmartHomeAction)
        .order_by(models.SmartHomeAction.created_at.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    out = []
    for r in rows:
        try:
            data = json.loads(r.data_json) if r.data_json else {}
        except ValueError:
            data = {}
        out.append({
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "text": r.text,
            "intent": r.intent,
            "domain": r.domain,
            "service": r.service,
            "entity_id": r.entity_id,
            "data": data,
            "ok": r.ok,
            "error": r.error,
            "source": r.source,
        })
    return out
