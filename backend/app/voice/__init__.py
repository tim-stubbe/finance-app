"""Voice-Adapter fuer den Smart-Home-Assistenten.

Die Pipeline in smarthome.py ist so geschnitten, dass Voice nur `transcribe()`
davor und `speak()` danach haengt - `process_command(text)` bleibt gleich.

Backend-Wahl ueber Env-Variablen. Alles laeuft im eigenen Netz, kein Cloud-
STT/-TTS:

  STT_BACKEND = stub (Default) | faster-whisper | http
  TTS_BACKEND = stub (Default) | piper | http

  WHISPER_MODEL     (Default "base"; z.B. tiny/base/small/medium)
  WHISPER_DEVICE    (Default "cpu"), WHISPER_COMPUTE (Default "int8")
  WHISPER_HTTP_URL  (fuer STT_BACKEND=http)
  PIPER_VOICE       (Default "de_DE-thorsten-medium")
  PIPER_VOICE_PATH  (explizite .onnx-Datei statt Auto-Download)
  PIPER_DATA_DIR    (Default $DATA_DIR/piper-voices)
  PIPER_HTTP_URL    (fuer TTS_BACKEND=http)
  ASSISTANT_LANGUAGE (Default "de")

Solange STT_BACKEND=stub ist, antwortet /api/smarthome/voice/command mit 501
und einer Anleitung - der dokumentierte Offline-Fallback.
"""

import os

from .stt import STT, StubSTT, FasterWhisperSTT, HttpWhisperSTT
from .tts import TTS, StubTTS, PiperTTS, HttpPiperTTS

__all__ = ["STT", "TTS", "get_stt", "get_tts"]


def _language() -> str:
    return os.environ.get("ASSISTANT_LANGUAGE", "de") or "de"


def get_stt() -> STT:
    backend = os.environ.get("STT_BACKEND", "stub").lower()
    if backend in ("faster-whisper", "faster_whisper", "whisper"):
        return FasterWhisperSTT(
            model=os.environ.get("WHISPER_MODEL", "base"),
            language=os.environ.get("WHISPER_LANGUAGE", _language()),
        )
    if backend == "http":
        return HttpWhisperSTT(language=os.environ.get("WHISPER_LANGUAGE", _language()))
    return StubSTT()


def get_tts() -> TTS:
    backend = os.environ.get("TTS_BACKEND", "stub").lower()
    if backend == "piper":
        return PiperTTS(voice=os.environ.get("PIPER_VOICE", "de_DE-thorsten-medium"))
    if backend == "http":
        return HttpPiperTTS()
    return StubTTS()
