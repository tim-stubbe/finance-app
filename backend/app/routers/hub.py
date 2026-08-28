"""Universelle Hub-Kommandozeile (siehe hub_command.py)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import auth, hub_command, schemas
from ..database import get_db

hub_router = APIRouter(prefix="/api")


@hub_router.post("/hub/command")
def hub_command_endpoint(
    data: schemas.SmartHomeCommand,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    settings = auth.get_or_create_settings(db)
    return hub_command.route(db, settings, data.text, space_id, confirm=data.confirm)
