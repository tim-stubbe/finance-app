"""Serverseitige Weckwort-Erkennung mit openWakeWord ("hey jarvis").

Der Browser streamt 16-kHz-Mono-PCM (int16) per WebSocket
(/api/smarthome/voice/stream). Dieser Detektor bekommt die rohen Bytes,
schneidet sie in 80-ms-Frames (1280 samples) und liefert je Frame den
Weckwort-Score. Ab `threshold` gilt das Weckwort als erkannt, danach nimmt
der Endpunkt den eigentlichen Befehl auf und schickt ihn durch die normale
Pipeline.

Modelle (~8 MB) laden beim ersten Gebrauch nach `$DATA_DIR/openwakeword`.
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
