"""Serverseitige Weckwort-Erkennung mit openWakeWord ("hey jarvis").

Der Browser streamt 16-kHz-Mono-PCM (int16) per WebSocket
(/api/smarthome/voice/stream). Dieser Detektor bekommt die rohen Bytes,
schneidet sie in 80-ms-Frames (1280 samples) und liefert je Frame den
Weckwort-Score. Ab `threshold` gilt das Weckwort als erkannt, danach nimmt
der Endpunkt den eigentlichen Befehl auf und schickt ihn durch die normale
Pipeline.

Backend-Wahl ueber `WAKEWORD_BACKEND` (siehe voice/__init__.py):
  - "openwakeword" (Default): laeuft im Kies-Prozess, braucht das Paket
    openwakeword (requirements-voice.txt). Modelle (~8 MB) laden beim
    ersten Gebrauch nach `$DATA_DIR/openwakeword`.
  - "http": ein selbst gehosteter Weckwort-Webservice im eigenen Netz
    (voice-stack Sidecar), Adresse in `WAKEWORD_HTTP_URL`. So bleibt
    openwakeword aus dem Produktions-Image (bricht dort den py3.14-Build).
"""

from __future__ import annotations

import os

DATA_DIR = os.environ.get("DATA_DIR", "/data")
FRAME = 1280  # samples pro openWakeWord-Frame (80 ms @ 16 kHz)


class WakeWord:
    def __init__(self, model: str | None = None, threshold: float = 0.5):
        self.model_name = model or os.environ.get("WAKEWORD_MODEL", "hey_jarvis")
        self.threshold = float(os.environ.get("WAKEWORD_THRESHOLD", threshold))
        self._model = None
        self._buf = b""

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            import openwakeword
            from openwakeword.model import Model
        except ImportError as exc:
            raise NotImplementedError(
                "openwakeword ist nicht installiert (requirements-voice.txt). "
                "Ohne serverseitiges Weckwort bleibt die Freihand-Steuerung "
                "beim bisherigen Browser-VAD-Verfahren."
            ) from exc
        target = os.path.join(DATA_DIR, "openwakeword")
        os.makedirs(target, exist_ok=True)
        try:
            openwakeword.utils.download_models(
                [self.model_name], target_directory=target
            )
            paths = [
                os.path.join(target, f)
                for f in os.listdir(target)
                if f.startswith(self.model_name) and f.endswith(".onnx")
            ]
        except Exception:  # noqa: BLE001 - Download-Ausfall -> Standardpfad
            paths = [self.model_name]
        self._model = Model(
            wakeword_models=paths or [self.model_name],
            inference_framework="onnx",
        )
        return self._model

    def reset(self):
        self._buf = b""
        if self._model is not None:
            try:
                self._model.reset()
            except Exception:  # noqa: BLE001
                pass

    def process(self, pcm: bytes) -> float:
        """Fuettert PCM-Bytes frameweise, liefert den hoechsten Score."""
        import numpy as np

        model = self._load()
        self._buf += pcm
        best = 0.0
        step = FRAME * 2  # int16 = 2 Bytes
        while len(self._buf) >= step:
            chunk, self._buf = self._buf[:step], self._buf[step:]
            frame = np.frombuffer(chunk, dtype=np.int16)
            scores = model.predict(frame)
            best = max(best, float(scores.get(self.model_name, 0.0)))
        return best


class HttpWakeWord:
    """Weckwort-Erkennung ueber einen selbst gehosteten Sidecar im eigenen Netz.

    Gleiche Schnittstelle wie `WakeWord` (`process`/`reset`/`_load`), damit der
    /voice/stream-Endpunkt nichts weiter wissen muss. Der Sidecar
    (voice-stack `voice-wakeword`) haelt Streaming-Puffer und Modell-Status:
      - `POST {url}/process`  Body = rohe PCM-Bytes (int16, 16 kHz) -> {"score": x}
      - `POST {url}/reset`    Streaming-Status zuruecksetzen
    So bleibt openwakeword aus dem Produktions-Image.
    """

    def __init__(self, model: str | None = None, threshold: float = 0.5):
        self.model_name = model or os.environ.get("WAKEWORD_MODEL", "hey_jarvis")
        self.threshold = float(os.environ.get("WAKEWORD_THRESHOLD", threshold))
        self.url = os.environ.get("WAKEWORD_HTTP_URL", "").rstrip("/")

    def _load(self):
        if not self.url:
            raise NotImplementedError(
                "WAKEWORD_BACKEND=http, aber WAKEWORD_HTTP_URL ist nicht gesetzt "
                "(Adresse deines lokalen Weckwort-Sidecars)."
            )
        import requests
        try:
            requests.get(f"{self.url}/health", timeout=5).raise_for_status()
        except requests.RequestException as exc:
            raise NotImplementedError(
                f"Weckwort-Sidecar nicht erreichbar ({self.url}): {exc}"
            ) from exc
        return self

    def reset(self):
        if not self.url:
            return
        import requests
        try:
            requests.post(f"{self.url}/reset", timeout=5)
        except requests.RequestException:
            pass

    def process(self, pcm: bytes) -> float:
        if not self.url:
            return 0.0
        import requests
        try:
            resp = requests.post(
                f"{self.url}/process",
                data=pcm,
                headers={"Content-Type": "application/octet-stream"},
                timeout=10,
            )
            resp.raise_for_status()
            return float(resp.json().get("score", 0.0))
        except (requests.RequestException, ValueError):
            return 0.0
