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


def chat(url: str, model: str, messages: list[dict], timeout: int = 600) -> str:
    resp = requests.post(
        f"{_base(url)}/api/chat",
        json={"model": model, "messages": messages, "stream": False},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    content = (data.get("message") or {}).get("content")
    if not content:
        raise ValueError("Ollama hat keine Antwort geliefert")
    return content.strip()
