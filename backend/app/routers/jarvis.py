"""Einheitlicher Jarvis-Einstieg (siehe backend/app/jarvis.py).

`POST /api/jarvis/command` ist der kanonische Endpunkt für Text- und
STT-Befehle - dieselbe Logik, die Telegram (`/haus`, freier Bot), die
Web-Kommandozeile und der Voice-Pfad nutzen. `/api/jarvis/house-summary`
liefert den kompakten Haus-Status fürs Cockpit, `/api/jarvis/memory` das
Kurzzeitgedächtnis (letztes Gerät / Intent).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import auth, jarvis, schemas, smarthome
from ..database import get_db

jarvis_router = APIRouter(prefix="/api")


@jarvis_router.post("/jarvis/command")
def jarvis_command(
    data: schemas.SmartHomeCommand,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    settings = auth.get_or_create_settings(db)
    return jarvis.handle(db, settings, data.text, space_id,
                         source="web", confirm=data.confirm)


@jarvis_router.get("/jarvis/house-summary")
def jarvis_house_summary(db: Session = Depends(get_db)):
    return smarthome.house_summary(auth.get_or_create_settings(db))


@jarvis_router.get("/jarvis/memory")
def jarvis_memory(db: Session = Depends(get_db)):
    return jarvis.recall(auth.get_or_create_settings(db)) or {}


@jarvis_router.delete("/jarvis/memory")
def jarvis_memory_clear():
    jarvis.forget()
    return {"ok": True}
