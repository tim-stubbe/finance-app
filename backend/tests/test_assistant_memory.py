"""Dauerhaftes Assistenten-Gedächtnis (assistant_memory.py)."""
from datetime import datetime, timedelta

from app import assistant_memory, models
from app.database import SessionLocal


def _db():
    return SessionLocal()


def test_add_memory_inserts_and_upserts_by_key():
    db = _db()
    try:
        a = assistant_memory.add_memory(db, text="Tim verkauft Samuel die Drohne", key="drohne")
        db.commit()
        assert a.id is not None
        b = assistant_memory.add_memory(db, text="Tim verkauft Samuel die Drohne diese Woche",
                                        key="drohne", importance=3)
        db.commit()
        assert b.id == a.id                       # Update, keine zweite Zeile
        assert b.importance == 3
        assert db.query(models.AssistantMemory).count() == 1
    finally:
        db.close()


def test_add_memory_key_collision_with_foreign_text_gets_suffix():
    db = _db()
    try:
        assistant_memory.add_memory(db, text="Katze heisst Mimi", key="tier")
        db.commit()
        row = assistant_memory.add_memory(db, text="Auto ist ein Golf", key="tier")
        db.commit()
        assert row.key != "tier" and row.key.startswith("tier-")
        assert db.query(models.AssistantMemory).count() == 2
    finally:
        db.close()


def test_add_memory_dedupes_near_identical_text_without_key():
    db = _db()
    try:
        assistant_memory.add_memory(db, text="Tim mag kurze knappe Antworten bitte")
        db.commit()
        assistant_memory.add_memory(db, text="Tim mag kurze knappe Antworten")
        db.commit()
        assert db.query(models.AssistantMemory).count() == 1
    finally:
        db.close()


def test_build_memory_block_order_budget_and_bump():
    db = _db()
    try:
        assistant_memory.add_memory(db, text="unwichtig eins", key="u1", importance=1)
        assistant_memory.add_memory(db, text="WICHTIG gepinnt", key="p1", importance=1, pinned=True)
        assistant_memory.add_memory(db, text="mittel zwei", key="m2", importance=3)
        db.commit()

        block = assistant_memory.build_memory_block(db, char_budget=2000)
        lines = block.strip().splitlines()
        assert lines[0].startswith("Was ich mir gemerkt")
        assert lines[1] == "- WICHTIG gepinnt"            # pinned zuerst
        assert lines[2] == "- mittel zwei"                # dann importance desc

        # last_used_at wurde gebumpt
        assert all(r.last_used_at is not None
                   for r in db.query(models.AssistantMemory).all())

        # hartes Zeichenbudget
        tiny = assistant_memory.build_memory_block(db, char_budget=40)
        assert len(tiny) <= 80
    finally:
        db.close()


def test_build_memory_block_skips_expired_and_verworfen():
    db = _db()
    try:
        assistant_memory.add_memory(db, text="abgelaufen", key="ex",
                                    expires_at=datetime.utcnow() - timedelta(days=1))
        r = assistant_memory.add_memory(db, text="verworfen", key="vw")
        db.commit()
        assistant_memory.forget_memory(db, key="vw")
        db.commit()
        assert assistant_memory.build_memory_block(db) == ""
    finally:
        db.close()


def test_forget_memory_soft_and_hard():
    db = _db()
    try:
        assistant_memory.add_memory(db, text="weg damit", key="w")
        db.commit()
        assert assistant_memory.forget_memory(db, key="w") is True
        db.commit()
        assert db.query(models.AssistantMemory).filter_by(key="w").first().status == "verworfen"
        assert assistant_memory.forget_memory(db, key="w", hard=True) is True
        db.commit()
        assert db.query(models.AssistantMemory).filter_by(key="w").first() is None
        assert assistant_memory.forget_memory(db, key="gibtsnicht") is False
    finally:
        db.close()


def test_prune_removes_expired_old_and_caps_but_keeps_pinned():
    db = _db()
    try:
        old = assistant_memory.add_memory(db, text="alt verworfen", key="av")
        db.commit()
        old.status = "verworfen"
        old.updated_at = datetime.utcnow() - timedelta(days=40)
        assistant_memory.add_memory(db, text="frisch gepinnt", key="fp", pinned=True)
        assistant_memory.add_memory(db, text="abgelaufen", key="ex2",
                                    expires_at=datetime.utcnow() - timedelta(days=2))
        db.commit()

        assistant_memory.prune(db, keep_active=1)
        keys = {r.key for r in db.query(models.AssistantMemory).all()}
        assert "av" not in keys and "ex2" not in keys
        assert "fp" in keys                               # pinned bleibt
    finally:
        db.close()


def test_conversation_turns_roundtrip_and_budget():
    db = _db()
    try:
        for i in range(10):
            assistant_memory.append_turn(db, "user", f"nachricht nummer {i} " * 20, chat_id="c1")
            assistant_memory.append_turn(db, "assistant", f"antwort {i}", chat_id="c1")
        hist = assistant_memory.load_history_for_prompt(db, char_budget=500, chat_id="c1")
        assert hist and hist[-1]["role"] == "assistant"
        assert sum(len(h["content"]) for h in hist) <= 500 + 2000  # grob budgetiert
        # anderer Chat sieht nichts
        assert assistant_memory.load_history_for_prompt(db, chat_id="c2") == []
    finally:
        db.close()


def test_distill_recent_writes_facts(monkeypatch):
    db = _db()
    try:
        from app import auth
        s = auth.get_or_create_settings(db)
        s.ollama_url = "http://x"
        s.ollama_model = "m"
        db.commit()
        assistant_memory.append_turn(db, "user", "Ab jetzt keine Vorschläge vor 9 Uhr bitte", chat_id="c1")

        monkeypatch.setattr(assistant_memory.ollama_client, "chat", lambda *a, **k:
                            '{"facts":[{"text":"Keine Vorschlaege vor 9 Uhr","category":"praeferenz","importance":3},'
                            '{"text":"Keine Vorschlaege vor 9 Uhr","category":"praeferenz","importance":2}]}')
        created = assistant_memory.distill_recent(db, s)
        assert len(created) == 1                          # Duplikat gefiltert
        assert created[0].source == "destillation"
        assert created[0].importance <= 2                 # nie 3 vom Job
    finally:
        db.close()


def test_distill_recent_survives_string_importance(monkeypatch):
    db = _db()
    try:
        from app import auth
        s = auth.get_or_create_settings(db)
        s.ollama_url, s.ollama_model = "http://x", "m"
        db.commit()
        assistant_memory.append_turn(db, "user", "Merk dir X", chat_id="c1")
        monkeypatch.setattr(assistant_memory.ollama_client, "chat", lambda *a, **k:
                            '{"facts":[{"text":"Fakt X","category":"fakt","importance":"hoch"}]}')
        created = assistant_memory.distill_recent(db, s)  # darf nicht crashen
        assert created and created[0].importance == 2
    finally:
        db.close()


def test_compress_keeps_prior_weekly_summary(monkeypatch):
    db = _db()
    try:
        from app import auth
        s = auth.get_or_create_settings(db)
        s.ollama_url, s.ollama_model = "http://x", "m"
        db.commit()
        calls = []
        monkeypatch.setattr(assistant_memory.ollama_client, "chat",
                            lambda url, model, msgs, **k: (calls.append(msgs[-1]["content"]), "ZUSAMMENFASSUNG")[1])
        for i in range(12):
            assistant_memory.append_turn(db, "user", f"lange nachricht {i} " * 40, chat_id="c1")
            assistant_memory.append_turn(db, "assistant", f"antwort {i} " * 40, chat_id="c1")
        assistant_memory.compress_old_turns(db, s, keep_chars=2000, chat_id="c1")
        # zweiter Lauf: die vorhandene Wochenzusammenfassung muss im Prompt landen
        for i in range(12, 24):
            assistant_memory.append_turn(db, "user", f"neue nachricht {i} " * 40, chat_id="c1")
            assistant_memory.append_turn(db, "assistant", f"antwort {i} " * 40, chat_id="c1")
        assistant_memory.compress_old_turns(db, s, keep_chars=2000, chat_id="c1")
        assert any("Bisherige Zusammenfassung" in c for c in calls)
        rows = [m for m in db.query(assistant_memory.models.AssistantMemory)
                .filter_by(category="zusammenfassung").all()]
        assert len(rows) == 1  # eine Zeile pro ISO-Woche
    finally:
        db.close()
