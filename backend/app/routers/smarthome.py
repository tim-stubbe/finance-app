"""Smart-Home-/Sprach-Assistent (Home Assistant <-> lokale Ollama).

Teil des "Life OS"-Hubs (siehe CLAUDE.md / smarthome.py) - eigener Router,
klar getrennt von der Finanzlogik. Alle Endpunkte haengen wie die uebrigen
geschuetzten Router an auth.require_auth (in main.py verdrahtet).

Die eigentliche Pipeline steckt in app/smarthome.py; hier nur HTTP-Fassade
+ Einstellungen (HA-URL/-Token verschluesselt, wie Immich/Radicale).
"""

import base64
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from .. import schemas, auth, bank_sync, crud, smarthome, ha_client, voice
from ..database import get_db

smarthome_router = APIRouter(prefix="/api/smarthome")


# ---------------- Einstellungen ----------------
@smarthome_router.get("/settings", response_model=schemas.SmartHomeSettingsOut)
def get_smarthome_settings(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    return schemas.SmartHomeSettingsOut(
        url=s.homeassistant_url,
        token_set=bool(s.homeassistant_token_encrypted),
        allowed_domains=s.homeassistant_allowed_domains,
        allowed_areas=s.homeassistant_allowed_areas,
        extra_services=s.homeassistant_extra_services,
        require_confirmation=s.homeassistant_require_confirmation,
        dry_run=s.homeassistant_dry_run,
    )


@smarthome_router.put("/settings", response_model=schemas.SmartHomeSettingsOut)
def update_smarthome_settings(data: schemas.SmartHomeSettingsUpdate, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    if data.url is not None:
        s.homeassistant_url = data.url.strip().rstrip("/") or None
    if data.token is not None:
        # "" loescht den Token, ein echter Wert ersetzt ihn, None (nicht im
        # Request) laesst ihn unangetastet.
        s.homeassistant_token_encrypted = (
            bank_sync.encrypt_secret(s.secret_key, data.token.strip())
            if data.token.strip() else None
        )
    if data.allowed_domains is not None:
        s.homeassistant_allowed_domains = data.allowed_domains.strip() or None
    if data.allowed_areas is not None:
        s.homeassistant_allowed_areas = data.allowed_areas.strip() or None
    if data.extra_services is not None:
        s.homeassistant_extra_services = data.extra_services.strip() or None
    if data.require_confirmation is not None:
        s.homeassistant_require_confirmation = data.require_confirmation
    if data.dry_run is not None:
        s.homeassistant_dry_run = data.dry_run
    db.commit()
    return get_smarthome_settings(db)


# ---------------- Status ----------------
@smarthome_router.get("/health")
def smarthome_health(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    return smarthome.health(s)


# ---------------- Geraete ----------------
@smarthome_router.get("/devices")
def smarthome_devices(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    try:
        return smarthome.list_devices(s)
    except ha_client.HAError as exc:
        raise HTTPException(502, str(exc))


@smarthome_router.get("/devices/{entity_id}")
def smarthome_device(entity_id: str, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    try:
        st = ha_client.get_state(s.homeassistant_url, smarthome._token(s), entity_id)
    except ha_client.HAError as exc:
        raise HTTPException(502, str(exc))
    return {
        "entity_id": st.get("entity_id"),
        "state": st.get("state"),
        "attributes": st.get("attributes", {}),
        "last_changed": st.get("last_changed"),
        # Verlauf/History bewusst noch nicht - siehe smarthome.py "Naechste Schritte".
        "history_hint": "Verlaufsdaten folgen mit der WebSocket-Anbindung (Phase 2).",
    }


# ---------------- Befehl ----------------
@smarthome_router.post("/command")
def smarthome_command(data: schemas.SmartHomeCommand, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    return smarthome.process_command(db, s, data.text, confirm=data.confirm, source="text")


# ---------------- Verlauf ----------------
@smarthome_router.get("/history")
def smarthome_history(limit: int = 30, db: Session = Depends(get_db)):
    return crud.get_smarthome_actions(db, limit=limit)


# ---------------- Aliase ----------------
@smarthome_router.get("/aliases", response_model=List[schemas.SmartHomeAliasOut])
def list_aliases(db: Session = Depends(get_db)):
    return crud.get_smarthome_aliases(db)


@smarthome_router.post("/aliases", response_model=schemas.SmartHomeAliasOut)
def create_alias(data: schemas.SmartHomeAliasCreate, db: Session = Depends(get_db)):
    if not data.phrase.strip() or not data.entity_id.strip():
        raise HTTPException(400, "Bitte Sprich-Name und entity_id angeben.")
    if "." not in data.entity_id:
        raise HTTPException(400, "entity_id sieht ungueltig aus (erwartet z.B. 'light.wohnzimmer').")
    alias = crud.create_smarthome_alias(db, data.phrase, data.entity_id)
    return {"id": alias.id, "phrase": alias.phrase, "entity_id": alias.entity_id}


@smarthome_router.delete("/aliases/{alias_id}")
def delete_alias(alias_id: int, db: Session = Depends(get_db)):
    if not crud.delete_smarthome_alias(db, alias_id):
        raise HTTPException(404, "Alias nicht gefunden.")
    return {"ok": True}


# ---------------- Voice (Phase 2) ----------------
def _voice_soft_error(reply: str) -> dict:
    return {"ok": False, "reply": reply, "intent": "chat", "actions": [],
            "needs_confirmation": False, "candidates": [], "transcript": ""}


@smarthome_router.post("/voice/command")
async def smarthome_voice_command(
    file: UploadFile = File(...),
    speak: bool = True,
    db: Session = Depends(get_db),
):
    """Audio hochladen -> lokale Spracherkennung -> exakt dieselbe Pipeline wie
    /command -> Antworttext (und, wenn `speak` und ein TTS-Backend aktiv sind,
    zusaetzlich `reply_audio_b64`).

    501 nur, wenn gar kein STT-Backend eingerichtet ist (STT_BACKEND=stub) -
    das ist der dokumentierte Offline-Fallback. Ein nicht erreichbarer Dienst
    ergibt einen weichen Fehler (200, ok:false), keinen 500."""
    s = auth.get_or_create_settings(db)
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "Leere Audiodatei.")

    stt = voice.get_stt()
    try:
        transcript = stt.transcribe(audio)
    except NotImplementedError as exc:
        raise HTTPException(501, str(exc))
    except Exception as exc:  # noqa: BLE001 - Dienst weg / Audio kaputt
        return _voice_soft_error(f"Spracherkennung fehlgeschlagen: {exc}")

    if not transcript.strip():
        return _voice_soft_error("Ich habe nichts verstanden.")

    result = smarthome.process_command(db, s, transcript, source="voice")
    result["transcript"] = transcript

    if speak:
        tts = voice.get_tts()
        try:
            wav = tts.speak(result.get("reply") or "")
            if wav:
                result["reply_audio_b64"] = base64.b64encode(wav).decode("ascii")
                result["reply_audio_format"] = getattr(tts, "audio_format", "audio/wav")
        except NotImplementedError:
            pass  # TTS-Stub: nur Text zurueck, kein Fehler
        except Exception as exc:  # noqa: BLE001
            result["tts_error"] = str(exc)
    return result
