from types import SimpleNamespace

from app import calls


def test_speech_safe_removes_symbols_links_and_expands_units():
    spoken = calls._speech_safe("❗ **Cashflow**: -200 € (10 %) https://example.test/x")
    assert "❗" not in spoken and "**" not in spoken and "https" not in spoken
    assert "Euro" in spoken and "Prozent" in spoken


def test_automatic_one_way_call_is_blocked(monkeypatch):
    monkeypatch.delenv("KIES_ALLOW_ONE_WAY_CALLS", raising=False)
    monkeypatch.setenv("KIES_LOCAL_CALL_URL", "https://calls.example")
    monkeypatch.setenv("KIES_LOCAL_CALL_TOKEN", "secret")
    monkeypatch.setenv("KIES_CALL_TO", "+49123")
    attempted = []
    monkeypatch.setattr(calls, "make_local_call", lambda *args: attempted.append(args))
    calls.call(SimpleNamespace(calls_enabled=True), "Automatische Meldung")
    assert attempted == []


def test_interactive_twiml_waits_for_spoken_answer():
    xml = calls._twiml("Kontostand niedrig", "https://example.test/api/calls/reply?token=a%26b")
    assert '<Gather input="speech" language="de-DE"' in xml
    assert "Was soll ich tun?" in xml
    assert "a%26b" in xml


def test_call_reply_runs_jarvis_and_speaks_result(client, monkeypatch):
    from app.routers import settings_misc

    monkeypatch.setenv("KIES_CALL_CALLBACK_TOKEN", "call-secret")
    monkeypatch.setattr(settings_misc.jarvis, "handle", lambda *args, **kwargs: {
        "ok": True, "reply": "To-do ist angelegt."
    })
    response = client.post("/api/calls/reply?token=call-secret",
                           data={"SpeechResult": "Erinnere mich morgen"})
    assert response.status_code == 200
    assert "To-do ist angelegt" in response.text


def test_call_reply_rejects_wrong_token(client, monkeypatch):
    monkeypatch.setenv("KIES_CALL_CALLBACK_TOKEN", "call-secret")
    response = client.post("/api/calls/reply?token=falsch", data={"SpeechResult": "Hallo"})
    assert response.status_code == 401
