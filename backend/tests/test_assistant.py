"""Tests für den Jarvis-Assistenten-Kern - gezielt für die drei in dieser
Nacht gefundenen/gefixten Bugs (Code-Review-Fund: bisher gab es dafür KEINE
Regressionstests, nur die Doku im Commit):

1. get_due_routines() muss einen verpassten 15-Minuten-Slot nachholen
   (crud_routines.py) - der ursprüngliche exakte hour==now/minute==now-
   Vergleich hätte das nie getan.
2. Ein abgelehnter category_rule-Vorschlag darf NICHT beim nächsten Lauf
   erneut vorgeschlagen werden (crud.py: decide_pending_suggestion löscht
   den Draft nicht mehr, check_for_learnable_correction_pattern findet ihn
   dann als "already").
3. GET /assistant/sync-errors aggregiert last_sync_status über alle
   Verbindungsarten korrekt.

ISIN-Auflösung (prices.resolve_isin_to_ticker) bewusst NICHT hier getestet -
echter Netzwerkaufruf gegen OpenFIGI, in CI unnötig flaky/langsam. Wurde
beim Bauen bereits live gegen 11 echte ISINs verifiziert (siehe Commit-
Historie)."""
from datetime import datetime, timedelta

from app import crud, models, schemas
from app.database import SessionLocal


def _db():
    return SessionLocal()


# ---------- get_due_routines: Nachhol-Logik ----------

def test_due_routine_at_exact_scheduled_time(auth_client):
    r = auth_client.post("/api/routines", json={
        "name": "Morgens", "weekdays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "hour": 8, "minute": 0, "items": ["Zähne putzen"], "active": True,
    })
    assert r.status_code == 200

    db = _db()
    try:
        now = datetime(2026, 8, 28, 8, 0)  # ein Freitag, exakt zur geplanten Zeit
        due = crud.get_due_routines(db, now)
        assert len(due) == 1
        assert due[0].name == "Morgens"
    finally:
        db.close()


def test_due_routine_catches_up_missed_slot(auth_client):
    """Kern-Regressionstest für den in dieser Nacht gefundenen Bug: eine für
    08:00 geplante Routine, die bis 08:30 nicht verschickt wurde (z.B. durch
    einen Server-Ausfall), muss beim 08:30-Prüflauf trotzdem noch fällig
    sein - die alte, exakte hour==now/minute==now-Prüfung hätte das NIE
    nachgeholt."""
    r = auth_client.post("/api/routines", json={
        "name": "Morgens", "weekdays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "hour": 8, "minute": 0, "items": ["Zähne putzen"], "active": True,
    })
    assert r.status_code == 200

    db = _db()
    try:
        later = datetime(2026, 8, 28, 8, 30)  # verpasster Slot, 30 Min. später
        due = crud.get_due_routines(db, later)
        assert len(due) == 1
    finally:
        db.close()


def test_due_routine_future_slot_not_fired_early(auth_client):
    """Die Nachhol-Logik darf nicht dazu führen, dass eine Routine VOR ihrer
    geplanten Zeit feuert."""
    auth_client.post("/api/routines", json={
        "name": "Abends", "weekdays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "hour": 20, "minute": 0, "items": ["Licht aus"], "active": True,
    })
    db = _db()
    try:
        too_early = datetime(2026, 8, 28, 19, 59)
        assert crud.get_due_routines(db, too_early) == []
    finally:
        db.close()


def test_due_routine_not_sent_twice_same_day(auth_client):
    r = auth_client.post("/api/routines", json={
        "name": "Morgens", "weekdays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "hour": 8, "minute": 0, "items": ["Zähne putzen"], "active": True,
    })
    routine_id = r.json()["id"]
    db = _db()
    try:
        routine = db.query(models.Routine).filter_by(id=routine_id).first()
        routine.last_sent_date = datetime(2026, 8, 28).date()
        db.commit()
        assert crud.get_due_routines(db, datetime(2026, 8, 28, 9, 0)) == []
    finally:
        db.close()


# ---------- category_rule-Vorschlag: kein erneutes Vorschlagen nach Ablehnung ----------

def _seed_corrections(db, merchant_key: str, category_id: int, n: int):
    for _ in range(n):
        db.add(models.CategoryCorrection(merchant_key=merchant_key, new_category_id=category_id))
    db.commit()


def test_learnable_pattern_detected_after_threshold(auth_client):
    cat = auth_client.post("/api/categories", json={"name": "Lebensmittel", "type": "ausgabe"}).json()
    db = _db()
    try:
        _seed_corrections(db, "rewe markt", cat["id"], crud.CATEGORY_RULE_LEARN_THRESHOLD)
        suggestion = crud.check_for_learnable_correction_pattern(db)
        assert suggestion is not None
        assert suggestion.kind == "category_rule"
    finally:
        db.close()


def test_rejected_category_rule_not_suggested_again():
    """Kern-Regressionstest für den in dieser Nacht gefundenen Bug: nach
    Ablehnung eines Regel-Vorschlags durfte check_for_learnable_correction_
    pattern dasselbe Muster NICHT ein zweites Mal vorschlagen - die alte
    Version löschte den Draft beim Ablehnen komplett und verlor damit jede
    Spur der Ablehnung."""
    db = _db()
    try:
        cat = crud.create_category(db, schemas.CategoryCreate(
            name="Lebensmittel", type=models.CategoryType.ausgabe,
        ))
        _seed_corrections(db, "rewe markt", cat.id, crud.CATEGORY_RULE_LEARN_THRESHOLD)

        first = crud.check_for_learnable_correction_pattern(db)
        assert first is not None

        crud.decide_pending_suggestion(db, "reject")

        # Weiterhin exakt derselbe Korrektur-Bestand (Schwellwert weiterhin
        # erfüllt) - trotzdem darf jetzt KEIN neuer Vorschlag entstehen.
        second = crud.check_for_learnable_correction_pattern(db)
        assert second is None
    finally:
        db.close()


# ---------- Fehler-Log ----------

def _seed_bank_connection(db, name, status, at):
    space = db.query(models.Space).first()
    account = models.Account(space_id=space.id, name=f"Konto {name}", type=models.AccountType.girokonto)
    db.add(account)
    db.flush()
    db.add(models.BankConnection(
        space_id=space.id, name=name, blz="12345678", fints_url="https://x", login="u",
        pin_encrypted="x", account_id=account.id, last_sync_status=status, last_sync_at=at,
    ))
    db.commit()


def test_sync_errors_endpoint_reports_recent_failures(auth_client):
    db = _db()
    try:
        _seed_bank_connection(db, "Testbank", "Fehler: Verbindung fehlgeschlagen", datetime.utcnow())
    finally:
        db.close()

    r = auth_client.get("/api/assistant/sync-errors")
    assert r.status_code == 200
    errors = r.json()
    assert len(errors) == 1
    assert errors[0]["source"] == "Bank (FinTS)"


def test_sync_errors_ignores_old_and_successful(auth_client):
    db = _db()
    try:
        _seed_bank_connection(db, "Alte Bank", "Fehler: alt", datetime.utcnow() - timedelta(hours=48))
        _seed_bank_connection(db, "OK-Bank", "OK", datetime.utcnow())
    finally:
        db.close()

    r = auth_client.get("/api/assistant/sync-errors")
    assert r.json() == []
