"""Duenner Ollama-Client.

WICHTIG - warum wir *streamen* statt `stream:false`:
Kies erreicht Ollama ueber die TrueNAS-NodePort-Adresse (`…:30068`). Deren
Proxy kappt eine Verbindung, die ~120 s lang KEIN Byte liefert. Eine
nicht-gestreamte Chat-Antwort kommt aber erst am Stueck, wenn das Modell
komplett fertig ist - auf der CPU-only-Box dauert das regelmaessig laenger
als 120 s, und die Anfrage stirbt mit HTTP 500 nach exakt 2m0s. Genau daran
ist der proaktive Assistent monatelang still gescheitert. Beim Streamen
fliessen laufend Tokens, der Proxy sieht Aktivitaet, nichts bricht ab.
"""
import json

import requests

from . import net_guard


def _base(url: str) -> str:
    # SSRF-Schutz: zentral hier, damit jeder Aufrufer (Router, Scheduler,
    # Smart Home) automatisch abgesichert ist - nur http/https, kein
    # Link-Local/Cloud-Metadata-Bereich.
    net_guard.validate_external_url(url)
    return url.rstrip("/")


def list_models(url: str) -> list[str]:
    resp = requests.get(f"{_base(url)}/api/tags", timeout=10, allow_redirects=False)
    resp.raise_for_status()
    data = resp.json()
    return [m.get("name") for m in (data.get("models") or []) if m.get("name")]


def _stream(url: str, path: str, body: dict, timeout):
    """POST an Ollama, Antwort als NDJSON-Stream. `timeout` ist hier der
    Abstand zwischen zwei Bytes (Connect + Read), NICHT die Gesamtdauer -
    solange Tokens fliessen, laeuft es weiter."""
    body = {**body, "stream": True}
    with requests.post(f"{_base(url)}{path}", json=body, timeout=timeout,
                       allow_redirects=False, stream=True) as resp:
        if not resp.ok:
            try:
                detail = resp.json().get("error")
            except Exception:
                detail = resp.text[:300]
            raise requests.HTTPError(
                f"{resp.status_code} von Ollama: {detail or resp.reason}", response=resp)
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("error"):
                raise ValueError(obj["error"])
            yield obj
            if obj.get("done"):
                break


def generate(url: str, model: str, prompt: str, timeout: int = 600) -> str:
    parts = [obj.get("response") or "" for obj in
             _stream(url, "/api/generate", {"model": model, "prompt": prompt}, timeout)]
    text = "".join(parts).strip()
    if not text:
        raise ValueError("Ollama hat keine Antwort geliefert")
    return text


def pull_model(url: str, model: str, timeout: int = 1800) -> str:
    """Laedt ein Modell aus der Ollama-Bibliothek auf den Server. Nicht-streamend
    (stream: false) - der Pull-Endpunkt haelt die Verbindung selbst mit
    Status-Zeilen wach, kein 120-s-Problem."""
    resp = requests.post(
        f"{_base(url)}/api/pull",
        json={"name": model, "stream": False},
        timeout=timeout,
        allow_redirects=False,
    )
    if not resp.ok:
        try:
            detail = resp.json().get("error")
        except Exception:
            detail = resp.text[:300]
        raise requests.HTTPError(f"{resp.status_code} von Ollama: {detail or resp.reason}", response=resp)
    data = resp.json()
    status = data.get("status", "")
    if "error" in data:
        raise ValueError(data["error"])
    return status or "erfolgreich"


def chat(url: str, model: str, messages: list[dict], timeout: int = 600,
         format: str | None = None, options: dict | None = None) -> str:
    """`format="json"` zwingt Ollama zu ausschliesslich gueltigem JSON
    (grammar-constrained) - robuster als hinterher zu parsen. `options` reicht
    z.B. {"num_predict": 900} oder {"num_ctx": 8192} durch."""
    body: dict = {"model": model, "messages": messages}
    if format:
        body["format"] = format
    if options:
        body["options"] = options
    parts = [(obj.get("message") or {}).get("content") or "" for obj in
             _stream(url, "/api/chat", body, timeout)]
    content = "".join(parts).strip()
    if not content:
        raise ValueError("Ollama hat keine Antwort geliefert")
    return content
