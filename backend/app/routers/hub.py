"""Universelle Hub-Kommandozeile (siehe hub_command.py)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import auth, jarvis, schemas
from ..database import get_db

hub_router = APIRouter(prefix="/api")


@hub_router.post("/hub/command")
def hub_command_endpoint(
    data: schemas.SmartHomeCommand,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    # Geht seit der Jarvis-Vereinheitlichung über jarvis.handle (Schnellpfade
    # + Kurzzeitgedächtnis), das intern weiter hub_command.route als
    # Ollama-Fallback nutzt.
    settings = auth.get_or_create_settings(db)
    return jarvis.handle(db, settings, data.text, space_id, source="hub", confirm=data.confirm)
