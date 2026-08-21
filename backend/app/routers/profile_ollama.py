"""Profil-Settings (Anzeigename) und Ollama-Server-Verwaltung (URL/Modell,
verfuegbare Modelle abfragen, Modell herunterladen).

Vierundzwanzigster Schritt der Code-Modularisierung (siehe ROADMAP.md),
nach investments/tax/debts/goals/trips/wishlist/personal/business_life/
budgets_alerts/deadlines/calendar_todos/categories/immich_routes/
bank_connections/enablebanking_ebay/mail_routes/spaces_accounts/
backup_restore/export_import/analytics/settings_misc/notify_settings/
dashboard. Zwei kleine, in main.py durch Transaktionen/Geburtsjahr
bzw. den /ai-Abschnitt getrennte Bloecke, hier zusammengefasst statt
je eine Ein-Datei-Domaene."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas, auth, ollama_client
from ..database import get_db

profile_ollama_router = APIRouter(prefix="/api")


# ---------------- Profil ----------------
@profile_ollama_router.get("/auth/profile", response_model=schemas.ProfileOut)
def get_profile(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.ProfileOut(display_name=settings.display_name)


@profile_ollama_router.put("/auth/profile", response_model=schemas.ProfileOut)
def update_profile(data: schemas.ProfileUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.display_name = data.display_name
    db.commit()
    return schemas.ProfileOut(display_name=settings.display_name)

# ---------------- KI-Assistent (Ollama) ----------------
@profile_ollama_router.get("/settings/ollama", response_model=schemas.OllamaSettingsOut)
def get_ollama_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.OllamaSettingsOut(url=settings.ollama_url, model=settings.ollama_model, beleg_chat_model=settings.beleg_chat_model)


@profile_ollama_router.put("/settings/ollama", response_model=schemas.OllamaSettingsOut)
def update_ollama_settings(data: schemas.OllamaSettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.ollama_url = data.url
    settings.ollama_model = data.model
    settings.beleg_chat_model = data.beleg_chat_model
    db.commit()
    return schemas.OllamaSettingsOut(url=settings.ollama_url, model=settings.ollama_model, beleg_chat_model=settings.beleg_chat_model)


@profile_ollama_router.get("/ollama/models", response_model=schemas.OllamaModelsOut)
def get_ollama_models(url: Optional[str] = None, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    target = url or settings.ollama_url
    if not target:
        raise HTTPException(400, "Bitte zuerst eine Ollama-Server-URL angeben")
    try:
        return schemas.OllamaModelsOut(models=ollama_client.list_models(target))
    except Exception as e:
        raise HTTPException(400, f"Ollama nicht erreichbar: {e}")


@profile_ollama_router.post("/ollama/pull", response_model=schemas.OllamaPullResult)
def pull_ollama_model(data: schemas.OllamaPullRequest, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    target = data.url or settings.ollama_url
    if not target:
        raise HTTPException(400, "Bitte zuerst eine Ollama-Server-URL angeben")
    model = data.model.strip()
    if not model:
        raise HTTPException(400, "Bitte einen Modellnamen angeben (z.B. llama3.2:1b)")
    try:
        status = ollama_client.pull_model(target, model)
        return schemas.OllamaPullResult(ok=True, status=status)
    except Exception as e:
        raise HTTPException(400, f"Herunterladen fehlgeschlagen: {e}")
