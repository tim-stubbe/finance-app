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

from .. import agent_core, assistant_memory, auth, jarvis, models, schemas, smarthome
from ..database import get_db

jarvis_router = APIRouter(prefix="/api")

# `/jarvis/chat` bekommt in main.py bewusst KEINE der beiden pauschalen
# Router-Dependencies (Web-Session via `jarvis_router`), sondern hängt seine
# Auth direkt am Endpoint via `auth.require_session_or_device` - das ist der
# einzige Jarvis-Endpunkt, den native Clients per Device-Token erreichen
# dürfen. Alle anderen Endpunkte in `jarvis_router` bleiben ausschließlich
# über die Web-Session erreichbar (siehe main.py: dependencies=_require_auth).
jarvis_chat_router = APIRouter(prefix="/api")


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


@jarvis_chat_router.post("/jarvis/chat")
def jarvis_chat(
    data: JarvisChatIn,
    db: Session = Depends(get_db),
    principal: models.AuthenticatedPrincipal = Depends(auth.require_session_or_device),
    space_id: int = Depends(auth.get_active_space_id),
):
    """Conversation-first assistant endpoint with private-data tool calling.

    Erreichbar per Web-Session ODER Device-Token (siehe
    `auth.require_session_or_device`). Der Agent Core selbst bekommt davon
    nichts mit - er sieht nur `settings`/`space_id`, genau wie beim
    Web-Aufruf. `space_id` wird bewusst weiterhin über
    `auth.get_active_space_id` aufgelöst statt aus `principal`, weil Device
    (noch) nicht an einen Space gebunden ist (Single-User-App, siehe
    models.Device) - die Funktion behandelt "kein Nutzer in der Session"
    bereits korrekt.

    Der Verlauf wird server-seitig persistiert (Conversation Threads, siehe
    `assistant_memory.py`/`agent_core._persist_turn`), gebunden per
    `chat_id="jarvis:{space_id}"`. `data.history` bleibt nur noch als Fallback
    für den (unwahrscheinlichen) Fall bestehen, dass noch kein persistierter
    Verlauf existiert.
    """
    settings = auth.get_or_create_settings(db)
    chat_id = f"jarvis:{space_id}"
    return agent_core.handle(db, settings, data.message, space_id,
                             history=data.history, chat_id=chat_id)


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


@jarvis_chat_router.get("/jarvis/chat/history")
def jarvis_chat_history(
    db: Session = Depends(get_db),
    principal: models.AuthenticatedPrincipal = Depends(auth.require_session_or_device),
    space_id: int = Depends(auth.get_active_space_id),
):
    """Persistierter Chat-Thread für den aktuellen Space, chronologisch - zum
    Laden beim App-/Seitenstart (siehe `assistant_memory.list_thread`)."""
    turns = assistant_memory.list_thread(db, chat_id=f"jarvis:{space_id}")
    return {"ok": True, "turns": turns}


@jarvis_chat_router.delete("/jarvis/chat/history")
def jarvis_chat_history_clear(
    db: Session = Depends(get_db),
    principal: models.AuthenticatedPrincipal = Depends(auth.require_session_or_device),
    space_id: int = Depends(auth.get_active_space_id),
):
    """Löscht den persistierten Chat-Thread für den aktuellen Space (Langzeit-
    Gedächtnis/`AssistantMemory` bleibt unberührt, siehe `clear_history`)."""
    n = assistant_memory.clear_history(db, chat_id=f"jarvis:{space_id}")
    return {"ok": True, "deleted": n}
