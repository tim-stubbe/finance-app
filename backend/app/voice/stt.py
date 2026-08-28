"""Speech-to-Text fuer den Smart-Home-Assistenten - komplett lokal, kein Cloud-STT.

Interface: `transcribe(audio_bytes) -> str`. `audio_bytes` ist eine komplette
Audiodatei (WAV/MP3/OGG/WebM/M4A - faster-whisper dekodiert via PyAV selbst,
der Client muss also nichts konvertieren).

Backends (Auswahl ueber die Env-Variable `STT_BACKEND`, siehe voice/__init__.py):
  - "stub" (Default): wirft NotImplementedError -> Endpunkt antwortet 501
  - "faster-whisper": lokales Whisper-Modell (CTranslate2). Modell wird beim
    ersten Aufruf nach `$DATA_DIR/whisper-models` geladen und ueberlebt dank
    des Volumes einen Neustart (wie `ollama pull`).
  - "http": ein selbst gehosteter Whisper-Webservice im eigenen Netz
    (z.B. onerahmet/openai-whisper-asr-webservice), Adresse in
    `WHISPER_HTTP_URL` - fuer Setups, die die ~250 MB Modell-/Runtime-
    Abhaengigkeiten nicht ins Kies-Image holen wollen.
"""

from __future__ import annotations

import io
import os

DATA_DIR = os.environ.get("DATA_DIR", "/data")


class STT:
    def transcribe(self, audio: bytes) -> str:  # pragma: no cover - Interface
        raise NotImplementedError


class StubSTT(STT):
    def transcribe(self, audio: bytes) -> str:
        raise NotImplementedError(
            "Kein Spracherkennungs-Backend aktiv (STT_BACKEND=stub). "
            "Fuer echte Sprachsteuerung STT_BACKEND=faster-whisper setzen "
            "(laeuft lokal, Modelldownload beim ersten Aufruf) oder "
            "STT_BACKEND=http mit WHISPER_HTTP_URL auf einen selbst gehosteten "
            "Whisper-Webservice zeigen. Kein Cloud-STT."
        )


class FasterWhisperSTT(STT):
    """Lokale Transkription mit faster-whisper (CTranslate2). Modell wird lazy
    beim ersten `transcribe()` geladen, damit Import/Start billig bleiben."""

    def __init__(self, model: str = "base", language: str = "de",
                 device: str | None = None, compute_type: str | None = None,
                 download_root: str | None = None):
        self.model_name = model
        self.language = language or None
        self.device = device or os.environ.get("WHISPER_DEVICE", "cpu")
        self.compute_type = compute_type or os.environ.get("WHISPER_COMPUTE", "int8")
        self.download_root = download_root or os.path.join(DATA_DIR, "whisper-models")
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise NotImplementedError(
                    "faster-whisper ist im Image nicht installiert. Entweder "
                    "backend/requirements-voice.txt mit ins Image aufnehmen "
                    "(siehe README) oder STT_BACKEND=http nutzen."
                ) from exc
            os.makedirs(self.download_root, exist_ok=True)
            self._model = WhisperModel(
                self.model_name, device=self.device,
                compute_type=self.compute_type, download_root=self.download_root,
            )
        return self._model

    def transcribe(self, audio: bytes) -> str:
        model = self._load()
        segments, _info = model.transcribe(
            io.BytesIO(audio), language=self.language, vad_filter=True,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()


class HttpWhisperSTT(STT):
    """Selbst gehosteter Whisper-Webservice im eigenen Netz - kein Cloud-STT.

    Erwartet die API von onerahmet/openai-whisper-asr-webservice:
    `POST {WHISPER_HTTP_URL}/asr?output=text` mit multipart-Feld `audio_file`,
    Antwort ist der reine Text.
    """

    def __init__(self, url: str | None = None, language: str = "de"):
        self.url = (url or os.environ.get("WHISPER_HTTP_URL", "")).rstrip("/")
        self.language = language

    def transcribe(self, audio: bytes) -> str:
        if not self.url:
            raise NotImplementedError(
                "STT_BACKEND=http, aber WHISPER_HTTP_URL ist nicht gesetzt "
                "(Adresse deines lokalen Whisper-Webservice)."
            )
        import requests
        try:
            resp = requests.post(
                f"{self.url}/asr",
                params={"output": "text", "language": self.language},
                files={"audio_file": ("audio.wav", audio, "audio/wav")},
                timeout=120,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Whisper-Webservice nicht erreichbar: {exc}") from exc
        return resp.text.strip()
