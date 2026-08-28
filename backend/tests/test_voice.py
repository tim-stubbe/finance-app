"""Sprach-Ein-/Ausgabe des Smart-Home-Assistenten (Phase 2, app/voice/).

Wichtigster Test: `/api/smarthome/voice/command` liefert mit einer echten
Audio-Testdatei eine reply durch die komplette Pipeline. Zusaetzlich ein
echter End-to-End-Lauf (Piper synthetisiert -> faster-whisper transkribiert),
der sauber uebersprungen wird, wenn die optionalen Pakete/Modelle fehlen
(dokumentierter Offline-Fallback).
"""

import importlib.util
import io
import math
import os
import struct
import wave

import pytest

from app import voice, ha_client, auth, bank_sync
from app.database import SessionLocal

_HAS_WHISPER = importlib.util.find_spec("faster_whisper") is not None
_HAS_PIPER = importlib.util.find_spec("piper") is not None
# Die echten Modell-Tests laden Modelle von HuggingFace (~140 MB) - im CI und
# in normalen Läufen deshalb übersprungen, damit ein langsames/fehlendes Netz
# den Lauf nicht hängen lässt. Explizit anschalten: KIES_VOICE_E2E=1 pytest ...
_E2E = bool(os.environ.get("KIES_VOICE_E2E"))


def _sine_wav(seconds=0.4, freq=220, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        for i in range(int(seconds * rate)):
            w.writeframes(struct.pack("<h", int(3000 * math.sin(2 * math.pi * freq * i / rate))))
    return buf.getvalue()


def _configure_fake_ha(monkeypatch):
    """Settings mit HA-URL/-Token, ha_client komplett gemockt. Gibt die Liste
    der ausgefuehrten (domain, service)-Calls zurueck."""
    db = SessionLocal()
    s = auth.get_or_create_settings(db)
    s.homeassistant_url = "http://ha.test:8123"
    s.homeassistant_token_encrypted = bank_sync.encrypt_secret(s.secret_key, "tok")
    db.commit()
    db.close()
    calls = []
    states = [{"entity_id": "light.wohnzimmer", "state": "on",
               "attributes": {"friendly_name": "Wohnzimmer Licht"}}]
    monkeypatch.setattr(ha_client, "get_states", lambda u, t: states)
    monkeypatch.setattr(ha_client, "area_map", lambda u, t: {})
    monkeypatch.setattr(ha_client, "call_service",
                        lambda u, t, d, sv, dt: calls.append((d, sv)) or [])
    return calls


# ---------------- Stub / Fallback ----------------

def test_voice_command_stub_returns_501(auth_client, monkeypatch):
    monkeypatch.delenv("STT_BACKEND", raising=False)
    r = auth_client.post("/api/smarthome/voice/command",
                         files={"file": ("a.wav", _sine_wav(), "audio/wav")})
    assert r.status_code == 501
    assert "faster-whisper" in r.text


def test_voice_command_empty_file_rejected(auth_client):
    r = auth_client.post("/api/smarthome/voice/command",
                         files={"file": ("a.wav", b"", "audio/wav")})
    assert r.status_code == 400


def test_http_stt_without_url_is_soft_501(auth_client, monkeypatch):
    monkeypatch.setenv("STT_BACKEND", "http")
    monkeypatch.delenv("WHISPER_HTTP_URL", raising=False)
    r = auth_client.post("/api/smarthome/voice/command",
                         files={"file": ("a.wav", _sine_wav(), "audio/wav")})
    assert r.status_code == 501
    assert "WHISPER_HTTP_URL" in r.text


# ---------------- Volle Pipeline mit eingespeistem STT ----------------

class _FakeSTT(voice.STT):
    def __init__(self, text):
        self._text = text

    def transcribe(self, audio: bytes) -> str:
        assert audio, "Audio-Bytes sollten ankommen"
        return self._text


def test_voice_command_with_injected_stt_returns_reply(auth_client, monkeypatch):
    """Beweist: eine hochgeladene Testdatei -> STT -> process_command -> reply,
    und der Schnellpfad schaltet tatsaechlich (gemocktes Home Assistant)."""
    calls = _configure_fake_ha(monkeypatch)
    monkeypatch.setattr(voice, "get_stt", lambda: _FakeSTT("Wohnzimmerlicht aus"))
    auth_client.post("/api/smarthome/aliases",
                     json={"phrase": "Wohnzimmerlicht", "entity_id": "light.wohnzimmer"})

    r = auth_client.post("/api/smarthome/voice/command?speak=false",
                         files={"file": ("cmd.wav", _sine_wav(), "audio/wav")})
    assert r.status_code == 200
    body = r.json()
    assert body["transcript"] == "Wohnzimmerlicht aus"
    assert body["ok"] is True
    assert body["intent"] == "control"
    assert ("light", "turn_off") in calls


def test_voice_command_blank_transcript_is_soft_error(auth_client, monkeypatch):
    _configure_fake_ha(monkeypatch)
    monkeypatch.setattr(voice, "get_stt", lambda: _FakeSTT("   "))
    r = auth_client.post("/api/smarthome/voice/command?speak=false",
                         files={"file": ("cmd.wav", _sine_wav(), "audio/wav")})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_wake_word_gates_the_pipeline(auth_client, monkeypatch):
    calls = _configure_fake_ha(monkeypatch)
    auth_client.post("/api/smarthome/aliases",
                     json={"phrase": "Wohnzimmerlicht", "entity_id": "light.wohnzimmer"})

    # Ohne Weckwort -> ignoriert, keine Aktion
    monkeypatch.setattr(voice, "get_stt", lambda: _FakeSTT("mach das Wohnzimmerlicht aus"))
    r = auth_client.post("/api/smarthome/voice/command?wake=1&speak=false",
                         files={"file": ("s.wav", _sine_wav(), "audio/wav")})
    assert r.json()["ignored"] is True
    assert calls == []

    # Mit Weckwort -> Weckwort wird abgeschnitten, Rest laeuft
    monkeypatch.setattr(voice, "get_stt", lambda: _FakeSTT("Jarvis, Wohnzimmerlicht aus"))
    r = auth_client.post("/api/smarthome/voice/command?wake=1&speak=false",
                         files={"file": ("s.wav", _sine_wav(), "audio/wav")})
    body = r.json()
    assert not body.get("ignored")
    assert body["transcript"] == "Wohnzimmerlicht aus"
    assert ("light", "turn_off") in calls


def test_voice_command_speaks_reply_when_tts_backend_present(auth_client, monkeypatch):
    _configure_fake_ha(monkeypatch)
    monkeypatch.setattr(voice, "get_stt", lambda: _FakeSTT("Wie spaet ist es"))

    class _FakeTTS(voice.TTS):
        def speak(self, text: str) -> bytes:
            return b"RIFF....WAVEfake"

    monkeypatch.setattr(voice, "get_tts", lambda: _FakeTTS())
    r = auth_client.post("/api/smarthome/voice/command",
                         files={"file": ("cmd.wav", _sine_wav(), "audio/wav")})
    body = r.json()
    assert "reply_audio_b64" in body
    import base64
    assert base64.b64decode(body["reply_audio_b64"]).startswith(b"RIFF")


# ---------------- Weckwort / WebSocket-Stream ----------------

def test_wakeword_process_slices_frames(monkeypatch):
    from app.voice.wakeword import WakeWord, FRAME
    ww = WakeWord()
    seen = []

    class _FakeModel:
        def predict(self, frame):
            seen.append(len(frame))
            return {"hey_jarvis": 0.9 if len(seen) == 2 else 0.1}

        def reset(self):
            pass

    monkeypatch.setattr(ww, "_load", lambda: _FakeModel())
    # 3 Frames auf einmal reinschieben
    best = ww.process(b"\x00\x00" * FRAME * 3)
    assert seen == [FRAME, FRAME, FRAME]
    assert best == 0.9


def _ws_session_header(c):
    # http.cookiejar (im TestClient) haengt ein Secure-Cookie NICHT an eine
    # wss://-Anfrage an - echte Browser tun das sehr wohl. Fuer den Test also
    # das Session-Cookie explizit als Header mitgeben.
    v = c.cookies.get("finance_session")
    return {"Cookie": f"finance_session={v}"} if v else {}


def test_voice_stream_requires_auth(client):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/smarthome/voice/stream"):
            pass


def test_voice_stream_errors_without_setup(auth_client):
    with auth_client.websocket_connect(
        "/api/smarthome/voice/stream", headers=_ws_session_header(auth_client)
    ) as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "eingerichtet" in msg["message"].lower()


# ---------------- Echte lokale Modelle (uebersprungen wenn nicht da) ----------------

@pytest.mark.skipif(not (_HAS_WHISPER and _E2E), reason="Echte Modell-Tests nur mit KIES_VOICE_E2E=1 (laden ~140 MB von HuggingFace)")
def test_faster_whisper_transcribes_without_crashing():
    from app.voice.stt import FasterWhisperSTT
    stt = FasterWhisperSTT(model="tiny")
    try:
        text = stt.transcribe(_sine_wav())
    except Exception as exc:  # Modell-Download im CI nicht moeglich o.ae.
        pytest.skip(f"Whisper-Modell nicht ladbar: {exc}")
    assert isinstance(text, str)


@pytest.mark.skipif(not (_HAS_WHISPER and _HAS_PIPER and _E2E),
                    reason="Echte Modell-Tests nur mit KIES_VOICE_E2E=1")
def test_real_roundtrip_piper_synth_then_whisper_via_endpoint(auth_client, monkeypatch, tmp_path):
    """Piper spricht einen deutschen Befehl -> faster-whisper transkribiert ->
    /api/smarthome/voice/command fuehrt ihn aus. Der eigentliche Ende-zu-Ende-
    Nachweis, dass Phase 2 wirklich laeuft (kein Stub)."""
    from app.voice.tts import PiperTTS

    piper = PiperTTS(voice="de_DE-thorsten-medium", data_dir=str(tmp_path))
    try:
        wav = piper.speak("Schalte das Licht im Wohnzimmer aus")
    except Exception as exc:  # Stimmen-Download im CI nicht moeglich
        pytest.skip(f"Piper-Stimme nicht ladbar: {exc}")
    assert wav.startswith(b"RIFF")

    monkeypatch.setenv("STT_BACKEND", "faster-whisper")
    monkeypatch.setenv("WHISPER_MODEL", "tiny")
    calls = _configure_fake_ha(monkeypatch)
    auth_client.post("/api/smarthome/aliases",
                     json={"phrase": "Licht", "entity_id": "light.wohnzimmer"})

    r = auth_client.post("/api/smarthome/voice/command?speak=false",
                         files={"file": ("cmd.wav", wav, "audio/wav")})
    assert r.status_code == 200
    body = r.json()
    assert "licht" in body["transcript"].lower()
    assert ("light", "turn_off") in calls
