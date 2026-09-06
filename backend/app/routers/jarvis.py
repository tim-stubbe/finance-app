"""Einheitlicher Jarvis-/Agent-Einstieg.

`POST /api/jarvis/command` bleibt der kanonische kurze Text/STT-Befehl und
nutzt die schnellen Jarvis-Routen. Komplexe Frage/Chat-Intents landen jetzt
im Agent Core.

`POST /api/jarvis/chat` ist der history-aware Assistenten-Endpunkt für UI und
längere Gespräche. Er startet direkt im Agent Core und arbeitet nach dem
Least-Context-Prinzip mit gezielten Tools.
"""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import agent_core, auth, jarvis, schemas, smarthome
from ..database import get_db

jarvis_router = APIRouter(prefix="/api")


class JarvisChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    history: list[dict[str, Any]] = Field(default_factory=list)


@jarvis_router.post("/jarvis/command")
def jarvis_command(
    data: schemas.SmartHomeCommand,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    settings = auth.get_or_create_settings(db)
    return jarvis.handle(db, settings, data.text, space_id,
                         source="web", confirm=data.confirm)


@jarvis_router.post("/jarvis/chat")
def jarvis_chat(
    data: JarvisChatIn,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    """Conversation-first assistant endpoint with private-data tool calling."""
    settings = auth.get_or_create_settings(db)
    return agent_core.handle(db, settings, data.message, space_id, history=data.history)


@jarvis_router.get("/jarvis/capabilities")
def jarvis_capabilities():
    """Small machine-readable contract for web/iOS clients."""
    return {
        "mode": "agent_v1",
        "privacy": "least_context",
        "local_model_default": True,
        "tools": [
            {"name": p.name, "risk": p.risk, "description": p.description}
            for p in agent_core.TOOL_POLICIES.values()
        ],
        "sensitive_actions": {
            "finance_mutations": "proposal_only",
            "smarthome": "existing_confirmation_pipeline",
            "email_send": "not_exposed_in_agent_v1",
        },
    }


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
