"""Kies Agent Core v1: tool calling, least-context and mandatory research."""

from app import agent_core, auth, ollama_client
from app.database import SessionLocal


def _configure_ollama():
    db = SessionLocal()
    settings = auth.get_or_create_settings(db)
    settings.ollama_url = "http://ollama.test:11434"
    settings.ollama_model = "test-model"
    db.commit()
    db.close()


def _chat_sequence(monkeypatch, replies):
    queue = list(replies)
    monkeypatch.setattr(ollama_client, "chat", lambda *a, **kw: queue.pop(0))


def test_agent_reads_only_requested_finance_context(auth_client, monkeypatch):
    _configure_ollama()
    auth_client.post("/api/accounts", json={"name": "Giro", "type": "girokonto", "initial_balance": 123.45})
    _chat_sequence(monkeypatch, [
        '{"type":"tool","name":"get_account_balances","arguments":{}}',
        '{"type":"answer","reply":"Auf deinem Girokonto liegen 123,45 €."}',
    ])

    r = auth_client.post("/api/jarvis/chat", json={"message": "Wie viel Geld habe ich auf meinem Konto?"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["domain"] == "agent"
    assert body["privacy"]["full_database_shared"] is False
    assert body["privacy"]["tools_used"] == ["get_account_balances"]
    assert body["tool_trace"][0]["risk"] == "read"
    assert "123,45" in body["reply"]


def test_tax_question_forces_web_research(auth_client, monkeypatch):
    _configure_ollama()
    db = SessionLocal()
    settings = auth.get_or_create_settings(db)
    settings.websearch_provider = "searxng"
    settings.searxng_url = "https://search.example"
    db.commit()
    db.close()

    monkeypatch.setattr(agent_core, "_search_web", lambda settings, query: [{
        "title": "Bundesfinanzministerium",
        "url": "https://example.test/bmf",
        "snippet": "Aktuelle steuerliche Information",
    }])
    _chat_sequence(monkeypatch, [
        '{"type":"answer","reply":"Nach aktueller Rechtslage kommt ein Abzug grundsätzlich in Betracht; die konkrete Zuordnung hängt von der Nutzung ab."}'
    ])

    r = auth_client.post("/api/jarvis/chat", json={"message": "Kann ich meinen beruflich genutzten Laptop steuerlich absetzen?"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "search_web" in body["privacy"]["tools_used"]
    assert body["sources"][0]["url"] == "https://example.test/bmf"
    assert body["tool_trace"][0]["risk"] == "external_read"


def test_agent_can_create_low_risk_todo(auth_client, monkeypatch):
    _configure_ollama()
    _chat_sequence(monkeypatch, [
        '{"type":"tool","name":"create_todo","arguments":{"title":"Lukas anrufen","due_date":null}}',
        '{"type":"answer","reply":"Erledigt, ich habe „Lukas anrufen“ als Aufgabe angelegt."}',
    ])

    r = auth_client.post("/api/jarvis/chat", json={"message": "Erinnere mich daran, Lukas anzurufen."})
    body = r.json()
    assert body["ok"] is True
    assert any(a["type"] == "todo_created" for a in body["actions"])
    assert body["tool_trace"][0]["risk"] == "write_safe"
    assert any(t["title"] == "Lukas anrufen" for t in auth_client.get("/api/todos").json())


def test_agent_finance_mutation_is_proposal_only(auth_client, monkeypatch):
    _configure_ollama()
    _chat_sequence(monkeypatch, [
        '{"type":"tool","name":"propose_finance_action","arguments":{"summary":"Kontostand manuell auf 500 € setzen"}}',
        '{"type":"answer","reply":"Ich habe die Änderung nur als Vorschlag vorbereitet und nichts verändert."}',
    ])

    body = auth_client.post("/api/jarvis/chat", json={"message": "Setz meinen Kontostand auf 500 Euro."}).json()
    action = body["actions"][0]
    assert action["type"] == "finance_proposal"
    assert action["requires_confirmation"] is True
    assert action["executed"] is False
    assert body["tool_trace"][0]["risk"] == "propose_only"


def test_agent_stops_on_repeated_identical_tool_call(auth_client, monkeypatch):
    # A model that keeps requesting the same tool with the same arguments
    # instead of progressing must not burn through all MAX_TOOL_STEPS - the
    # second identical call should be short-circuited into a forced answer.
    _configure_ollama()
    _chat_sequence(monkeypatch, [
        '{"type":"tool","name":"get_todos","arguments":{"include_done":false}}',
        '{"type":"tool","name":"get_todos","arguments":{"include_done":false}}',
        '{"type":"answer","reply":"Du hast keine offenen Aufgaben."}',
    ])

    r = auth_client.post("/api/jarvis/chat", json={"message": "Was steht bei mir an?"})
    body = r.json()
    assert body["ok"] is True
    assert body["tool_trace"][1]["note"] == "duplicate_call_skipped"
    assert body["tool_trace"][1]["ok"] is False


def test_agent_survives_failing_tool(auth_client, monkeypatch):
    # An unexpected exception inside a tool (e.g. a DB error) must be
    # surfaced to the model as a normal tool failure instead of crashing
    # the whole request.
    _configure_ollama()
    monkeypatch.setattr(agent_core, "crud", type("Crud", (), {
        "get_accounts": staticmethod(lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db down"))),
    }))
    _chat_sequence(monkeypatch, [
        '{"type":"tool","name":"get_account_balances","arguments":{}}',
        '{"type":"answer","reply":"Ich konnte deine Kontostände gerade nicht abrufen."}',
    ])

    r = auth_client.post("/api/jarvis/chat", json={"message": "Wie viel Geld habe ich?"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["tool_trace"][0]["ok"] is False


def test_capabilities_publish_security_contract(auth_client):
    body = auth_client.get("/api/jarvis/capabilities").json()
    assert body["mode"] == "agent_v1"
    assert body["privacy"] == "least_context"
    assert body["sensitive_actions"]["finance_mutations"] == "proposal_only"
    names = {t["name"] for t in body["tools"]}
    assert {"get_account_balances", "search_web", "create_todo"}.issubset(names)
