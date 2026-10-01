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
