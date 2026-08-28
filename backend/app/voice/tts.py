"""Text-to-Speech fuer den Smart-Home-Assistenten - komplett lokal, kein Cloud-TTS.

Interface: `speak(text) -> bytes` (fertige WAV-Datei als Bytes). Der Router
gibt sie base64-kodiert neben dem Antworttext zurueck; TTS ist optional -
faellt es aus oder ist es "stub", kommt trotzdem die Text-Antwort.

Backends (Env `TTS_BACKEND`, siehe voice/__init__.py):
  - "stub" (Default): wirft NotImplementedError -> nur Text-Antwort
  - "piper": Piper (piper-tts, ONNX). Die Stimme (.onnx + .onnx.json) liegt
    unter `$DATA_DIR/piper-voices/`; fehlt sie, wird sie beim ersten Aufruf
    einmalig von huggingface.co/rhasspy/piper-voices geladen (einmaliger
    Modell-Download wie `ollama pull`, danach offline).
  - "http": selbst gehosteter Piper-HTTP-Server im eigenen Netz
    (`python -m piper.http_server ...`), Adresse in `PIPER_HTTP_URL`.
"""

from __future__ import annotations

import io
import os
import wave

DATA_DIR = os.environ.get("DATA_DIR", "/data")


class TTS:
    audio_format = "audio/wav"

    def speak(self, text: str) -> bytes:  # pragma: no cover - Interface
        raise NotImplementedError


class StubTTS(TTS):
    def speak(self, text: str) -> bytes:
        raise NotImplementedError(
            "Kein Sprachausgabe-Backend aktiv (TTS_BACKEND=stub). Fuer "
            "gesprochene Antworten TTS_BACKEND=piper setzen (laeuft lokal) "
            "oder TTS_BACKEND=http mit PIPER_HTTP_URL. Kein Cloud-TTS."
        )


class PiperTTS(TTS):
    """Lokale Sprachausgabe mit Piper. Stimme + Modell werden lazy geladen."""

    def __init__(self, voice: str = "de_DE-thorsten-medium",
                 data_dir: str | None = None, voice_path: str | None = None):
        self.voice = voice
        self.data_dir = data_dir or os.environ.get(
            "PIPER_DATA_DIR", os.path.join(DATA_DIR, "piper-voices"))
        self.voice_path = voice_path or os.environ.get("PIPER_VOICE_PATH") or None
        self._voice = None

    def _model_path(self):
        from pathlib import Path
        if self.voice_path:
            return Path(self.voice_path)
        target = Path(self.data_dir) / f"{self.voice}.onnx"
        if not target.exists():
            os.makedirs(self.data_dir, exist_ok=True)
            try:
                from piper.download_voices import download_voice
            except ImportError as exc:
                raise NotImplementedError(
                    "piper-tts ist im Image nicht installiert. Entweder "
                    "backend/requirements-voice.txt mit ins Image aufnehmen "
                    "(siehe README) oder TTS_BACKEND=http nutzen."
                ) from exc
            download_voice(self.voice, Path(self.data_dir))
        return target

    def _load(self):
        if self._voice is None:
            try:
                from piper import PiperVoice
            except ImportError as exc:
                raise NotImplementedError(
                    "piper-tts ist im Image nicht installiert (siehe README / "
                    "requirements-voice.txt) oder TTS_BACKEND=http nutzen."
                ) from exc
            self._voice = PiperVoice.load(self._model_path())
        return self._voice

    def speak(self, text: str) -> bytes:
        text = (text or "").strip()
        if not text:
            return b""
        voice = self._load()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            voice.synthesize_wav(text, wav_file)
        return buf.getvalue()


class HttpPiperTTS(TTS):
    """Selbst gehosteter Piper-HTTP-Server im eigenen Netz - kein Cloud-TTS.

    Kompatibel mit `python -m piper.http_server` (POST-Body = Text -> WAV).
    """

    def __init__(self, url: str | None = None):
        self.url = (url or os.environ.get("PIPER_HTTP_URL", "")).rstrip("/")

    def speak(self, text: str) -> bytes:
        text = (text or "").strip()
        if not text:
            return b""
        if not self.url:
            raise NotImplementedError(
                "TTS_BACKEND=http, aber PIPER_HTTP_URL ist nicht gesetzt."
            )
        import requests
        try:
            resp = requests.post(self.url, data=text.encode("utf-8"), timeout=60)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Piper-HTTP-Server nicht erreichbar: {exc}") from exc
        return resp.content
