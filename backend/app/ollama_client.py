import requests


def _base(url: str) -> str:
    return url.rstrip("/")


def list_models(url: str) -> list[str]:
    resp = requests.get(f"{_base(url)}/api/tags", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return [m.get("name") for m in (data.get("models") or []) if m.get("name")]


def generate(url: str, model: str, prompt: str, timeout: int = 600) -> str:
    resp = requests.post(
        f"{_base(url)}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data.get("response")
    if not text:
        raise ValueError("Ollama hat keine Antwort geliefert")
    return text.strip()


def pull_model(url: str, model: str, timeout: int = 1800) -> str:
    """Lädt ein Modell aus der Ollama-Bibliothek auf den Server. Nicht-streamend
    (stream: false) - blockiert bis fertig, dafür kein SSE/WebSocket-Aufwand nötig.
    Bei kleinen Modellen (~1-2GB) dauert das typischerweise 1-5 Minuten, deshalb
    ein deutlich längeres Timeout als bei normalen Chat-Anfragen."""
    resp = requests.post(
        f"{_base(url)}/api/pull",
        json={"name": model, "stream": False},
        timeout=timeout,
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


def chat(url: str, model: str, messages: list[dict], timeout: int = 600) -> str:
    resp = requests.post(
        f"{_base(url)}/api/chat",
        json={"model": model, "messages": messages, "stream": False},
        timeout=timeout,
    )
    if not resp.ok:
        # Ollama liefert bei 4xx/5xx oft eine erklärende JSON-Fehlermeldung im Body
        # ("error": "..."), die requests' generische raise_for_status()-Meldung
        # verschluckt - für die Fehlerdiagnose (siehe Protokoll) ist genau die aber
        # oft der einzige Hinweis, was am Request falsch war.
        try:
            detail = resp.json().get("error")
        except Exception:
            detail = resp.text[:300]
        raise requests.HTTPError(f"{resp.status_code} von Ollama: {detail or resp.reason}", response=resp)
    data = resp.json()
    content = (data.get("message") or {}).get("content")
    if not content:
        raise ValueError("Ollama hat keine Antwort geliefert")
    return content.strip()
