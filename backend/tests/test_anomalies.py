"""Regressionstest für einen live gemeldeten Bug (28.08.): eine Kategorie
vom Typ "einnahme" konnte einen "Ausgaben-Ausreißer" auslösen, wenn genug
negativ vorzeichnete Buchungen (z.B. nicht als Umbuchung erkannte Transfers)
darin landeten - crud.detect_spending_anomalies prüfte category.type nie."""
from datetime import date, timedelta

from app import crud, models, schemas
from app.database import SessionLocal


def _make_account(db):
    space = db.query(models.Space).first()
    account = models.Account(space_id=space.id, name="Testkonto", type=models.AccountType.girokonto)
    db.add(account)
    db.flush()
    return account


def _add_tx(db, account_id, category_id, amount, days_ago):
    db.add(models.Transaction(
        account_id=account_id, category_id=category_id, amount=amount,
        date=date.today() - timedelta(days=days_ago), description="x",
    ))


def test_income_category_never_triggers_spending_anomaly(auth_client):
    """Kern-Regressionstest: eine Einnahmen-Kategorie mit überwiegend
    negativen Buchungen diesen Monat (z.B. Korrekturen/nicht erkannte
    Umbuchungen) darf NIE als "Ausgaben-Ausreißer" gemeldet werden."""
    db = SessionLocal()
    try:
        account = _make_account(db)
        income_cat = crud.create_category(db, schemas.CategoryCreate(
            name="Sonstige Einnahmen", type=models.CategoryType.einnahme,
        ))
        # Historie: kleine, meist negative Beträge in den Vormonaten.
        for m in (35, 65, 95):
            _add_tx(db, account.id, income_cat.id, -5.0, m)
        # Laufender Monat: deutlich größere negative Summe (z.B. zwei nicht
        # erkannte Transfers) - würde ohne den Fix als Ausreißer gelten.
        _add_tx(db, account.id, income_cat.id, -800.0, 1)
        _add_tx(db, account.id, income_cat.id, -900.0, 2)
        db.commit()

        # Genügend Tage im Monat vergangen, damit die Funktion überhaupt wertet.
        if date.today().day < 5:
            return  # an den ersten Tagen des Monats testet detect_spending_anomalies gar nichts

        anomalies = crud.detect_spending_anomalies(db, account.space_id)
        assert not any(a["category_id"] == income_cat.id for a in anomalies)
    finally:
        db.close()


def test_expense_category_still_triggers_spending_anomaly(auth_client):
    """Gegenprobe: eine echte Ausgaben-Kategorie mit einem deutlichen
    Anstieg muss weiterhin erkannt werden - der Fix darf die eigentliche
    Funktion nicht kaputt machen."""
    db = SessionLocal()
    try:
        account = _make_account(db)
        expense_cat = crud.create_category(db, schemas.CategoryCreate(
            name="Lebensmittel", type=models.CategoryType.ausgabe,
        ))
        for m in (35, 65, 95):
            _add_tx(db, account.id, expense_cat.id, -100.0, m)
        _add_tx(db, account.id, expense_cat.id, -500.0, 1)
        db.commit()

        if date.today().day < 5:
            return
        anomalies = crud.detect_spending_anomalies(db, account.space_id)
        assert any(a["category_id"] == expense_cat.id for a in anomalies)
    finally:
        db.close()
