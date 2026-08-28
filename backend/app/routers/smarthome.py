"""Smart-Home-/Sprach-Assistent (Home Assistant <-> lokale Ollama).

Teil des "Life OS"-Hubs (siehe CLAUDE.md / smarthome.py) - eigener Router,
klar getrennt von der Finanzlogik. Alle Endpunkte haengen wie die uebrigen
geschuetzten Router an auth.require_auth (in main.py verdrahtet).

Die eigentliche Pipeline steckt in app/smarthome.py; hier nur HTTP-Fassade
+ Einstellungen (HA-URL/-Token verschluesselt, wie Immich/Radicale).
"""

import asyncio
import base64
import io
import json
import wave
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import schemas, auth, bank_sync, crud, smarthome, ha_client, voice
from .. import smarthome_automations, smarthome_ws
from ..database import get_db, SessionLocal

smarthome_router = APIRouter(prefix="/api/smarthome")
# Der WebSocket-Endpunkt haengt NICHT an dependencies=[Depends(auth.require_auth)]
# (das braucht ein Request-Objekt, das es beim WS nicht gibt) - Auth laeuft im
# Handler selbst ueber die Session. Wird in main.py ohne _require_auth inkludiert.
smarthome_ws_router = APIRouter(prefix="/api/smarthome")


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
        wake_word=s.homeassistant_wake_word or "hey_jarvis",
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
    if data.wake_word is not None:
        s.homeassistant_wake_word = data.wake_word.strip().lower() or None
    db.commit()
    return get_smarthome_settings(db)


# ---------------- Status ----------------
@smarthome_router.get("/health")
def smarthome_health(quick: bool = False, db: Session = Depends(get_db)):
    """quick=1 ueberspringt die Netz-Probes (HA/Ollama anpingen) und meldet nur,
    ob ueberhaupt konfiguriert - fuer Aufrufer wie das Hub-Panel, die nur
    wissen wollen, ob das Feature sichtbar sein soll."""
    s = auth.get_or_create_settings(db)
    if quick:
        return {
            "ha_configured": bool(s.homeassistant_url and s.homeassistant_token_encrypted),
            "ollama_configured": bool(s.ollama_url and s.ollama_model),
            "live": smarthome_ws.is_live(),
        }
    out = smarthome.health(s)
    out["live"] = smarthome_ws.is_live()
    return out


def _pcm_to_wav(pcm: bytes, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


@smarthome_ws_router.websocket("/voice/stream")
async def smarthome_voice_stream(ws: WebSocket):
    """Freihand-Betrieb mit serverseitigem Weckwort.

    Der Client streamt fortlaufend 16-kHz-Mono-PCM (int16, binaere Frames).
    Server erkennt das Weckwort (openWakeWord "hey jarvis"), meldet
    {"type":"wake"}, nimmt danach den Befehl bis zu einer Sprechpause auf
    (einfache Energie-VAD, oder Client sendet {"type":"stop"}), transkribiert
    lokal und schickt {"type":"result", ...} - selbe Pipeline wie /command.
    """
    if not ws.session.get("authenticated"):
        await ws.close(code=1008)
        return
    await ws.accept()

    db = SessionLocal()
    try:
        settings = auth.get_or_create_settings(db)
        if not (settings.homeassistant_url and settings.homeassistant_token_encrypted):
            await ws.send_json({"type": "error", "message": "Smart Home ist nicht eingerichtet."})
            return
        stt = voice.get_stt()
        if isinstance(stt, voice.StubSTT):
            await ws.send_json({"type": "error",
                                "message": "Kein Spracherkennungs-Backend aktiv (STT_BACKEND=stub)."})
            return
        try:
            detector = voice.WakeWord(model=settings.homeassistant_wake_word or None)
            await asyncio.to_thread(detector._load)
        except NotImplementedError as exc:
            await ws.send_json({"type": "error", "message": str(exc)})
            return

        await ws.send_json({"type": "ready", "wake_word": detector.model_name})

        RATE = 16000
        SILENCE_BYTES = int(0.7 * RATE) * 2
        MAX_CMD_BYTES = 6 * RATE * 2
        state = "idle"
        cmd = bytearray()
        low_run = 0

        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            data = msg.get("bytes")
            force_stop = False
            if msg.get("text"):
                try:
                    force_stop = json.loads(msg["text"]).get("type") == "stop"
                except (ValueError, TypeError):
                    pass
                if not force_stop:
                    continue

            if state == "idle":
                if data and await asyncio.to_thread(detector.process, data) >= detector.threshold:
                    await ws.send_json({"type": "wake"})
                    state, cmd, low_run = "capturing", bytearray(), 0
                continue

            # state == "capturing"
            if data:
                cmd.extend(data)
                import numpy as np
                arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                rms = float((arr * arr).mean() ** 0.5) if arr.size else 0.0
                low_run = low_run + len(data) if rms < 500 else 0

            if not (force_stop or low_run >= SILENCE_BYTES or len(cmd) >= MAX_CMD_BYTES):
                continue

            pcm, state = bytes(cmd), "idle"
            cmd = bytearray()
            detector.reset()
            if len(pcm) < RATE:  # < 0,5 s -> zu kurz
                await ws.send_json({"type": "result", "ok": True, "ignored": True,
                                    "reply": "", "transcript": ""})
                continue
            wav = _pcm_to_wav(pcm, RATE)
            try:
                transcript = await asyncio.to_thread(stt.transcribe, wav)
            except Exception as exc:  # noqa: BLE001
                await ws.send_json({"type": "result", "ok": False,
                                    "reply": f"Spracherkennung fehlgeschlagen: {exc}", "transcript": ""})
                continue
            if not transcript.strip():
                await ws.send_json({"type": "result", "ok": True, "ignored": True,
                                    "reply": "", "transcript": ""})
                continue
            settings = auth.get_or_create_settings(db)
            result = await asyncio.to_thread(
                smarthome.process_command, db, settings, transcript, False, "voice")
            result["type"] = "result"
            result["transcript"] = transcript
            try:
                tts = voice.get_tts()
                wav_out = await asyncio.to_thread(tts.speak, result.get("reply") or "")
                if wav_out:
                    result["reply_audio_b64"] = base64.b64encode(wav_out).decode("ascii")
                    result["reply_audio_format"] = getattr(tts, "audio_format", "audio/wav")
            except NotImplementedError:
                pass
            except Exception as exc:  # noqa: BLE001
                result["tts_error"] = str(exc)
            await ws.send_json(result)
    except WebSocketDisconnect:
        pass
    finally:
        db.close()


@smarthome_router.get("/events")
def smarthome_events():
    """Server-Sent-Events: pro HA-Zustandsaenderung eine data:-Zeile
    ({entity_id, state, friendly_name}). Speist aus dem WebSocket-Cache
    (smarthome_ws) - die Web-UI zieht damit ohne eigenen WS-Client live nach."""
    return StreamingResponse(
        smarthome_ws.events_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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


# ---------------- Grundriss (Phase 3) ----------------
@smarthome_router.get("/floorplan")
def get_floorplan(db: Session = Depends(get_db)):
    """Gespeichertes Layout + aktuelle Geraetezustaende zusammengefuehrt, damit
    das Frontend nicht zwei Aufrufe koordinieren muss. Bei nicht erreichbarem
    Home Assistant kommt trotzdem das Layout (states leer)."""
    s = auth.get_or_create_settings(db)
    plan = crud.get_floorplan(db)
    states = {}
    try:
        for st in smarthome.list_devices(s):
            states[st["entity_id"]] = {"state": st["state"], "name": st["name"],
                                       "domain": st["domain"], "toggleable": st["toggleable"]}
    except Exception:  # noqa: BLE001 - Layout hat Vorrang vor Live-Status
        states = {}
    return {"rooms": plan.get("rooms", []), "devices": plan.get("devices", []),
            "states": states}


@smarthome_router.put("/floorplan")
def put_floorplan(data: schemas.SmartHomeFloorplanIn, db: Session = Depends(get_db)):
    saved = crud.save_floorplan(db, data.model_dump())
    return saved


@smarthome_router.post("/floorplan/autolayout")
def autolayout_floorplan(db: Session = Depends(get_db)):
    """Ersetzt das Layout durch eine automatische Aufteilung aus den
    HA-Bereichen (ein Raum je Bereich, Geraete darin verteilt)."""
    s = auth.get_or_create_settings(db)
    try:
        plan = smarthome.autolayout(s)
    except ha_client.HAError as exc:
        raise HTTPException(502, str(exc))
    return crud.save_floorplan(db, plan)


# ---------------- KI-Automationen (Phase 4) ----------------
def _automation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ha_client.HAError):
        return HTTPException(502, str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(400, str(exc))
    return HTTPException(502, f"KI/Home Assistant nicht ansprechbar: {exc}")


@smarthome_router.get("/automations")
def list_automations(db: Session = Depends(get_db)):
    return crud.get_automation_drafts(db)


@smarthome_router.post("/automations/suggest")
def suggest_automations(data: schemas.AutomationSuggestRequest, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    try:
        return smarthome_automations.suggest(db, s, n=max(1, min(data.count, 10)))
    except Exception as exc:  # noqa: BLE001
        raise _automation_error(exc)


@smarthome_router.post("/automations/draft-freeform")
def draft_automation_freeform(data: schemas.AutomationFreeformRequest, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    try:
        return smarthome_automations.draft_yaml(db, s, freeform=data.text)
    except Exception as exc:  # noqa: BLE001
        raise _automation_error(exc)


@smarthome_router.post("/automations/{draft_id}/draft")
def draft_automation_yaml(draft_id: int, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    try:
        return smarthome_automations.draft_yaml(db, s, draft_id=draft_id)
    except Exception as exc:  # noqa: BLE001
        raise _automation_error(exc)


@smarthome_router.put("/automations/{draft_id}")
def update_automation_yaml(draft_id: int, data: schemas.AutomationYamlUpdate, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    try:
        return smarthome_automations.save_yaml(db, s, draft_id, data.yaml_text)
    except Exception as exc:  # noqa: BLE001
        raise _automation_error(exc)


@smarthome_router.post("/automations/{draft_id}/apply")
def apply_automation(draft_id: int, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    try:
        return smarthome_automations.apply(db, s, draft_id)
    except Exception as exc:  # noqa: BLE001
        raise _automation_error(exc)


@smarthome_router.post("/automations/{draft_id}/reject")
def reject_automation(draft_id: int, db: Session = Depends(get_db)):
    out = crud.set_automation_draft_status(db, draft_id, "verworfen")
    if not out:
        raise HTTPException(404, "Vorschlag nicht gefunden.")
    return out


@smarthome_router.delete("/automations/{draft_id}")
def delete_automation(draft_id: int, db: Session = Depends(get_db)):
    if not crud.delete_automation_draft(db, draft_id):
        raise HTTPException(404, "Vorschlag nicht gefunden.")
    return {"ok": True}


# ---------------- Voice (Phase 2) ----------------
def _voice_soft_error(reply: str) -> dict:
    return {"ok": False, "reply": reply, "intent": "chat", "actions": [],
            "needs_confirmation": False, "candidates": [], "transcript": ""}


@smarthome_router.post("/voice/command")
async def smarthome_voice_command(
    file: UploadFile = File(...),
    speak: bool = True,
    wake: bool = False,
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

    if wake:
        # Freihaendiger Betrieb: nur reagieren, wenn das Segment das Weckwort
        # enthaelt. Alles bis einschliesslich Weckwort wird abgeschnitten.
        ww = (s.homeassistant_wake_word or "jarvis").strip().lower()
        idx = transcript.lower().find(ww)
        rest = transcript[idx + len(ww):].lstrip(" ,.:;–-\t").strip() if idx != -1 else ""
        if idx == -1 or not rest:
            return {"ok": True, "ignored": True, "reply": "", "transcript": transcript,
                    "intent": "chat", "actions": [], "needs_confirmation": False, "candidates": []}
        transcript = rest

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
