import calendar
import hashlib
import json
import math
import re
import unicodedata
from datetime import date, datetime, timedelta
from statistics import median
from sqlalchemy import func, extract
from sqlalchemy.orm import Session
from . import models, schemas, prices, debts, radicale_sync, travel_time

CACHE_TTL = timedelta(hours=24)


def get_cached_history(db: Session, asset_type: str, symbol: str, range_key: str) -> list[tuple[str, float]]:
    """Holt Kurshistorie, cacht sie aber für 'lange' Ranges (alles außer 1d/2w) einen
    Tag lang auf der Festplatte statt bei jedem Chart-Aufruf erneut die externe API
    zu befragen. 1d/2w bleiben bewusst immer live, da sie kurzfristige Bewegungen
    zeigen sollen. Schlägt der Live-Abruf fehl, wird - falls vorhanden - auf einen
    auch älteren Cache-Stand zurückgegriffen statt einen Fehler zu werfen."""
    if range_key in prices.LIVE_RANGES:
        return prices.fetch_history(asset_type, symbol, range_key)

    row = (
        db.query(models.PriceHistoryCache)
        .filter_by(asset_type=asset_type, symbol=symbol, range_key=range_key)
        .first()
    )
    if row and (datetime.utcnow() - row.fetched_at) < CACHE_TTL:
        return json.loads(row.data_json)

    try:
        points = prices.fetch_history(asset_type, symbol, range_key)
    except Exception:
        if row:
            return json.loads(row.data_json)
        raise

    payload = json.dumps(points)
    if row:
        row.data_json = payload
        row.fetched_at = datetime.utcnow()
    else:
        db.add(models.PriceHistoryCache(
            asset_type=asset_type, symbol=symbol, range_key=range_key,
            fetched_at=datetime.utcnow(), data_json=payload,
        ))
    db.commit()
    return points


def _as_date(value) -> date:
    """Normalisiert das Datum einer importierten Buchung auf ein echtes date-Objekt.

    Die Quellen liefern unterschiedliche Typen: FinTS gibt ein date, Enable Banking
    und PayPal geben ISO-Strings. SQLite akzeptiert nur date-Objekte, ein String
    lässt sonst den kompletten Import-Flush scheitern."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def import_bank_transaction(db: Session, account_id: int, tx_date, amount: float, applicant: str | None,
                            purpose: str | None, external_id: str | None = None) -> bool:
    """Importiert eine von einer externen Quelle (FinTS, Enable Banking, PayPal, ...)
    gelieferte Buchung dedupliziert per Hash. Gibt True zurück, wenn neu importiert,
    False bei Duplikat.

    Liefert die Quelle eine stabile eigene ID (`external_id`, z.B. PayPals
    transaction_id), wird nur diese gehasht. Sonst bleibt es beim Hash über die
    Inhalte - der ist zwangsläufig fragil, weil sich schon eine geänderte
    Beschriftung wie ein neuer Vorgang auswirkt."""
    # SQLite erzwingt keine Fremdschlüssel: zeigt eine Verbindung auf ein
    # gelöschtes Konto, würden die Buchungen zwar geschrieben, aber nirgends mehr
    # auftauchen (alle Abfragen joinen Account). Lieber hörbar scheitern.
    if not db.query(models.Account).filter(models.Account.id == account_id).first():
        raise ValueError(
            f"Das Zielkonto (id {account_id}) existiert nicht mehr. "
            "Bitte die Verbindung löschen und mit einem gültigen Konto neu anlegen."
        )
    tx_date = _as_date(tx_date)
    hash_input = (
        f"{account_id}|ext:{external_id}" if external_id
        else f"{account_id}|{tx_date}|{amount}|{applicant}|{purpose}"
    )
    import_hash = hashlib.sha256(hash_input.encode()).hexdigest()
    exists = db.query(models.Transaction).filter(models.Transaction.import_hash == import_hash).first()
    if exists:
        return False
    db.add(models.Transaction(
        date=tx_date, amount=amount, account_id=account_id,
        description=applicant, notes=purpose, import_hash=import_hash,
    ))
    return True


# ---------- Spaces ----------
def get_spaces(db: Session):
    return db.query(models.Space).order_by(models.Space.created_at).all()


def get_space(db: Session, space_id: int):
    return db.query(models.Space).filter(models.Space.id == space_id).first()


def create_space(db: Session, data: schemas.SpaceCreate):
    space = models.Space(name=data.name, icon=data.icon or "🏠")
    db.add(space)
    db.commit()
    db.refresh(space)
    return space


def delete_space(db: Session, space_id: int):
    space = get_space(db, space_id)
    if space:
        db.delete(space)
        db.commit()
    return space


# ---------- Accounts ----------
def get_accounts(db: Session, space_id: int):
    return (
        db.query(models.Account)
        .filter(models.Account.space_id == space_id)
        .order_by(models.Account.name)
        .all()
    )


def get_account(db: Session, account_id: int, space_id: int):
    return (
        db.query(models.Account)
        .filter(models.Account.id == account_id, models.Account.space_id == space_id)
        .first()
    )


def create_account(db: Session, account: schemas.AccountCreate, space_id: int):
    db_account = models.Account(**account.model_dump(), space_id=space_id)
    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    return db_account


def update_account(db: Session, account_id: int, space_id: int, data: schemas.AccountUpdate, source: str = "app"):
    db_account = get_account(db, account_id, space_id)
    if not db_account:
        return None
    changes = data.model_dump(exclude_unset=True)
    if "initial_balance" in changes and changes["initial_balance"] != db_account.initial_balance:
        old_balance = account_balance(db, db_account)
        new_balance = old_balance - db_account.initial_balance + changes["initial_balance"]
        db.add(models.AccountBalanceLog(
            account_id=db_account.id, old_balance=old_balance, new_balance=new_balance, source=source,
        ))
    for key, value in changes.items():
        setattr(db_account, key, value)
    db.commit()
    db.refresh(db_account)
    return db_account


def set_debt_balance(db: Session, debt: models.Debt, new_balance: float, source: str = "telegram") -> models.Debt:
    """Setzt die Restschuld direkt statt sie aus dem Zahlungs-Ledger abzuleiten -
    fuer eine Kreditkarte/Kreditlinie (kind=dispo) gibt es kein festes
    Tilgungsschema, der Saldo schwankt durch laufende Ausgaben/Zahlungen, die
    hier nicht einzeln erfasst werden. Analog zu update_account(initial_balance)
    wird auch das im AccountBalanceLog vermerkt."""
    old_balance = debt.current_balance
    if new_balance != old_balance:
        db.add(models.AccountBalanceLog(debt_id=debt.id, old_balance=old_balance, new_balance=new_balance, source=source))
    debt.original_amount = round(new_balance, 2)
    recompute_debt_from_payments(db, debt)
    return debt


def set_balance_by_name(db: Session, space_id: int, name_query: str, new_balance: float, source: str = "telegram"):
    """Setzt den aktuellen Saldo (Konto ODER Schuld, z.B. eine Kreditkarte als
    Dispo/Kreditlinie) über einen (Teil-)Namen statt einer ID - fürs Telegram-
    Kommando gedacht. Gibt (objekt, error) zurück: error ist None bei Erfolg,
    sonst ein Text zum direkten Zurücksenden (kein Treffer / mehrdeutig -
    bewusst KEIN Rateversuch bei einer Geldsumme)."""
    accounts = get_accounts(db, space_id)
    debts_list = get_debts(db, space_id)
    q = name_query.strip().lower()
    acc_matches = [a for a in accounts if q in a.name.lower()]
    debt_matches = [d for d in debts_list if q in d.name.lower()]
    if not acc_matches and not debt_matches:
        namen = ", ".join([a.name for a in accounts] + [d.name for d in debts_list])
        return None, f"Nichts mit „{name_query}“ gefunden. Vorhanden: {namen}"
    if len(acc_matches) + len(debt_matches) > 1:
        namen = ", ".join([a.name for a in acc_matches] + [d.name for d in debt_matches])
        return None, f"„{name_query}“ ist nicht eindeutig, passt auf: {namen}. Bitte genauer benennen."
    if acc_matches:
        account = acc_matches[0]
        updated = update_account(db, account.id, space_id, schemas.AccountUpdate(
            initial_balance=round(account.initial_balance - account_balance(db, account) + new_balance, 2),
        ), source=source)
        return updated, None
    debt = set_debt_balance(db, debt_matches[0], new_balance, source=source)
    return debt, None


def recent_balance_changes(db: Session, space_id: int, limit: int = 20) -> list[dict]:
    rows = (
        db.query(models.AccountBalanceLog)
        .outerjoin(models.Account, models.AccountBalanceLog.account_id == models.Account.id)
        .outerjoin(models.Debt, models.AccountBalanceLog.debt_id == models.Debt.id)
        .filter((models.Account.space_id == space_id) | (models.Debt.space_id == space_id))
        .order_by(models.AccountBalanceLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [{
        "account_name": (r.account.name if r.account else None) or (r.debt.name if r.debt else None) or "",
        "old_balance": r.old_balance, "new_balance": r.new_balance,
        "source": r.source, "created_at": r.created_at,
    } for r in rows]


def delete_account(db: Session, account_id: int, space_id: int):
    db_account = get_account(db, account_id, space_id)
    if db_account:
        db.delete(db_account)
        db.commit()
    return db_account


def account_balance(db: Session, account: models.Account) -> float:
    total = (
        db.query(func.coalesce(func.sum(models.Transaction.amount), 0.0))
        .filter(models.Transaction.account_id == account.id)
        .scalar()
    )
    return round(account.initial_balance + total, 2)


# ---------- Categories (global, nicht bereichsgebunden) ----------
def get_categories(db: Session):
    return db.query(models.Category).order_by(models.Category.name).all()


def get_category(db: Session, category_id: int):
    return db.query(models.Category).filter(models.Category.id == category_id).first()


def create_category(db: Session, category: schemas.CategoryCreate):
    db_category = models.Category(**category.model_dump())
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category


def category_totals(db: Session, space_id: int, year: int, month: int | None = None) -> dict[int, float]:
    """Summe je Kategorie fuer ein Jahr (optional auf einen Monat eingegrenzt) -
    zeigt in der Kategorien-Liste auf einen Blick, welche Kategorien ueberhaupt
    genutzt werden, ohne extra ins Dashboard wechseln zu muessen. Kategorien
    sind global, die Summe aber je Bereich."""
    query = (
        db.query(models.Transaction.category_id, func.sum(models.Transaction.amount))
        .join(models.Account)
        .filter(
            models.Account.space_id == space_id,
            extract("year", models.Transaction.date) == year,
            models.Transaction.is_transfer.is_(False),
            models.Transaction.category_id.isnot(None),
        )
    )
    if month:
        query = query.filter(extract("month", models.Transaction.date) == month)
    rows = query.group_by(models.Transaction.category_id).all()
    return {cat_id: round(total, 2) for cat_id, total in rows}


def category_sign_mismatches(db: Session, space_id: int) -> list[dict]:
    """Kategorien, in denen mindestens eine Buchung ein zum Kategorie-Typ
    unpassendes Vorzeichen hat (Ausgabe-Kategorie mit positivem Betrag oder
    Einnahme-Kategorie mit negativem) - der zuverlässigste (wenn auch nicht
    vollständige) automatische Hinweis auf durcheinandergeratene Zuordnungen,
    z.B. nach einem Kategorien-Reset mit wiederverwendeten IDs (live erlebt:
    alle Kategorien neu angelegt, alte Buchungen zeigten seitdem unter
    derselben ID eine andere Kategorie). Erfasst nicht jede Fehlzuordnung
    (eine Ausgabe in der falschen, aber vorzeichen-passenden Kategorie fällt
    nicht auf), ist aber günstig genug für einen Hinweis bei jedem Laden des
    Kategorien-Tabs."""
    rows = (
        db.query(models.Transaction, models.Category)
        .join(models.Account, models.Transaction.account_id == models.Account.id)
        .join(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Account.space_id == space_id,
            models.Transaction.is_transfer.is_(False),
        )
        .all()
    )
    by_category: dict[int, dict] = {}
    for t, c in rows:
        mismatch = (c.type == "ausgabe" and t.amount > 0) or (c.type == "einnahme" and t.amount < 0)
        if not mismatch:
            continue
        entry = by_category.setdefault(c.id, {"category_id": c.id, "category_name": c.name, "category_type": c.type, "count": 0})
        entry["count"] += 1
    return sorted(by_category.values(), key=lambda e: -e["count"])


def update_category(db: Session, category_id: int, data: schemas.CategoryUpdate):
    db_category = get_category(db, category_id)
    if not db_category:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(db_category, key, value)
    db.commit()
    db.refresh(db_category)
    return db_category


def delete_category(db: Session, category_id: int):
    db_category = get_category(db, category_id)
    if db_category:
        db.delete(db_category)
        db.commit()
    return db_category


# ---------- Transactions ----------
def get_transactions(
    db: Session,
    space_id: int,
    account_id: int | None = None,
    category_id: int | None = None,
    year: int | None = None,
    month: int | None = None,
    search: str | None = None,
    trip_id: int | None = None,
    hide_transfers: bool = False,
):
    query = db.query(models.Transaction).join(models.Account).filter(models.Account.space_id == space_id)
    if account_id:
        query = query.filter(models.Transaction.account_id == account_id)
    if category_id:
        query = query.filter(models.Transaction.category_id == category_id)
    if year:
        query = query.filter(extract("year", models.Transaction.date) == year)
    if month:
        query = query.filter(extract("month", models.Transaction.date) == month)
    if trip_id:
        query = query.filter(models.Transaction.trip_id == trip_id)
    if hide_transfers:
        query = query.filter(models.Transaction.is_transfer.is_(False))
    if search:
        like = f"%{search}%"
        query = query.filter(
            (models.Transaction.description.ilike(like))
            | (models.Transaction.notes.ilike(like))
        )
    return query.order_by(models.Transaction.date.desc(), models.Transaction.id.desc()).all()


def get_transactions_for_export(
    db: Session, space_id: int,
    date_from: date | None = None, date_to: date | None = None,
    account_id: int | None = None, category_id: int | None = None,
    is_business: bool | None = None,
) -> list[models.Transaction]:
    """Eigene, einfachere Filterung für den Steuer-Export (main.tax_export) -
    bewusst nicht in get_transactions gemischt, damit dessen bestehende
    Filter (Jahr/Monat/Suche/Umbuchungen) unangetastet bleiben."""
    query = db.query(models.Transaction).join(models.Account).filter(models.Account.space_id == space_id)
    if date_from:
        query = query.filter(models.Transaction.date >= date_from)
    if date_to:
        query = query.filter(models.Transaction.date <= date_to)
    if account_id:
        query = query.filter(models.Transaction.account_id == account_id)
    if category_id:
        query = query.filter(models.Transaction.category_id == category_id)
    if is_business is not None:
        query = query.filter(models.Account.is_business.is_(is_business))
    return query.order_by(models.Transaction.date, models.Transaction.id).all()


_RECURRING_FREQUENCIES = [
    ("woechentlich", 7, 2),
    ("zweiwoechentlich", 14, 3),
    ("monatlich", 30, 5),
    ("quartalsweise", 91, 10),
    ("jaehrlich", 365, 20),
]


def _normalize_description(desc: str | None) -> str:
    """Live beobachtet: derselbe PayPal-Empfaenger tauchte je nach Buchung als
    "PayPal (Europe) S.à r.l. et Cie, SCA", "PayPal Europe S.a.r.l. et Cie S.C.A"
    und "PayPal (Europe) S.a r.l. et Cie, S.C.A." auf - reines Whitespace-Trimmen
    reichte nicht, um das als denselben Empfaenger zu erkennen (weder bei "Wo dein
    Geld hingeht" noch bei der Abo-Erkennung). Deshalb zusaetzlich Akzente und
    Satzzeichen vereinheitlichen, bevor verglichen wird."""
    if not desc:
        return ""
    text = unicodedata.normalize("NFKD", desc.strip().lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[.,()/-]", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\b\d{6,}\b", "", text)
    return text.strip()


TRANSFER_MATCH_WINDOW_DAYS = 3
TRANSFER_CANDIDATE_LIMIT = 500


def detect_and_mark_transfers(db: Session, space_id: int) -> int:
    """Erkennt Umbuchungen zwischen zwei eigenen Konten und markiert beide Seiten
    als `is_transfer`, damit sie nicht als Einnahme/Ausgabe zählen.

    Heuristik: zwei bislang unkategorisierte, unmarkierte Buchungen auf zwei
    unterschiedlichen Konten desselben Bereichs mit exakt entgegengesetztem Betrag
    innerhalb weniger Tage. Nur unkategorisierte Buchungen werden betrachtet, damit
    eine bereits bewusst vergebene Kategorie nie überschrieben wird. Begrenzt auf
    die letzten 500 Kandidaten (statt aller je erfassten Buchungen) - der Abgleich
    ist O(n²), das reicht für einen stündlichen Lauf über die jeweils neuen Buchungen
    locker aus, ohne mit wachsender Historie immer langsamer zu werden."""
    candidates = (
        db.query(models.Transaction)
        .join(models.Account)
        .filter(
            models.Account.space_id == space_id,
            models.Transaction.is_transfer.is_(False),
            models.Transaction.category_id.is_(None),
        )
        .order_by(models.Transaction.date.desc())
        .limit(TRANSFER_CANDIDATE_LIMIT)
        .all()
    )
    used: set[int] = set()
    marked = 0
    for i, t in enumerate(candidates):
        if t.id in used:
            continue
        for other in candidates[i + 1:]:
            if other.id in used or other.account_id == t.account_id:
                continue
            if abs((other.date - t.date).days) > TRANSFER_MATCH_WINDOW_DAYS:
                continue
            if round(other.amount + t.amount, 2) != 0:
                continue
            t.is_transfer = True
            other.is_transfer = True
            used.add(t.id)
            used.add(other.id)
            marked += 2
            break
    if marked:
        db.commit()
    return marked


RECURRING_INTERVAL_DAYS = {label: target for label, target, _tol in _RECURRING_FREQUENCIES}


def _cashflow_events(db: Session, space_id: int, end: date) -> list[dict]:
    """Baut die Liste künftiger Zahlungsereignisse (erkannte wiederkehrende
    Zahlungen + laufende Kreditraten) bis `end` - gemeinsame Grundlage für
    cashflow_forecast UND cashflow_scenario, damit beide exakt dieselbe
    Heuristik verwenden und nicht auseinanderlaufen können."""
    today = date.today()
    events: list[dict] = []
    for r in detect_recurring_transactions(db, space_id):
        interval = RECURRING_INTERVAL_DAYS.get(r["frequency"])
        if not interval:
            continue
        occ_date = r["next_expected_date"]
        # Liegt der nächste erwartete Termin schon in der Vergangenheit (z.B. weil
        # länger nicht geschaut wurde), auf den nächsten zukünftigen Termin vorspulen.
        while occ_date < today:
            occ_date += timedelta(days=interval)
        while occ_date <= end:
            events.append({
                "date": occ_date, "amount": r["avg_amount"], "description": r["description"],
                "description_key": r["description_key"],
            })
            occ_date += timedelta(days=interval)

    # Laufende Kreditraten fließen mit ein - bewusst nur die monatliche Rate
    # (inkl. Zins-/Nebenkostenanteil), NICHT die gesamte Restschuld auf einen
    # Schlag. debts.projection() übernimmt die eigentliche Tilgungsrechnung
    # (kennt Zins, Laufzeitende, Kreditart) statt das hier zu duplizieren -
    # sie bricht von selbst ab, sobald die Restschuld getilgt ist.
    for d in get_debts(db, space_id):
        if d.status != models.DebtStatus.active:
            continue
        rows, _ = debts.projection(d)
        for row in rows:
            if row.date > end:
                break
            events.append({
                "date": row.date, "amount": -abs(row.payment), "description": f"Kredit: {d.name}",
                "description_key": None,
            })

    events.sort(key=lambda e: e["date"])
    return events


def _cashflow_points(start_balance: float, events: list[dict], today: date, end: date) -> list[schemas.CashflowPoint]:
    points: list[schemas.CashflowPoint] = []
    balance = start_balance
    idx = 0
    d = today
    while d <= end:
        while idx < len(events) and events[idx]["date"] == d:
            balance += events[idx]["amount"]
            idx += 1
        points.append(schemas.CashflowPoint(date=d.isoformat(), balance=round(balance, 2)))
        d += timedelta(days=1)
    return points


def _cashflow_summary(start_balance: float, horizon_days: int, points: list[schemas.CashflowPoint], events: list[dict]) -> schemas.CashflowForecastOut:
    lowest = min(points, key=lambda p: p.balance) if points else None
    first_negative = next((p for p in points if p.balance < 0), None)
    return schemas.CashflowForecastOut(
        start_balance=start_balance,
        horizon_days=horizon_days,
        points=points,
        upcoming_events=[
            schemas.CashflowEvent(date=e["date"], amount=e["amount"], description=e["description"])
            for e in events
        ],
        lowest_balance=lowest.balance if lowest else start_balance,
        lowest_date=lowest.date if lowest else None,
        goes_negative=first_negative is not None,
        first_negative_date=first_negative.date if first_negative else None,
    )


def cashflow_forecast(db: Session, space_id: int, horizon_days: int = 90) -> schemas.CashflowForecastOut:
    """Projiziert den Gesamtkontostand nach vorne, indem die erkannten wiederkehrenden
    Zahlungen (Abos, Miete, Gehalt, ...) und die laufenden Kreditraten im gewählten
    Zeitraum weitergeschrieben werden. Bewusst begrenzt: nur Muster, die
    crud.detect_recurring_transactions bereits als wiederkehrend erkannt hat, fließen
    ein - einmalige/unregelmäßige Ausgaben (z.B. spontane Einkäufe) werden NICHT
    vorhergesagt, die Kurve bleibt zwischen zwei Terminen flach. Das ist eine bewusste
    Einschränkung, keine Wettervorhersage für Spontanausgaben - im Frontend
    entsprechend kommuniziert."""
    accounts = get_accounts(db, space_id)
    start_balance = round(sum(account_balance(db, a) for a in accounts), 2)
    today = date.today()
    end = today + timedelta(days=horizon_days)
    events = _cashflow_events(db, space_id, end)
    points = _cashflow_points(start_balance, events, today, end)
    return _cashflow_summary(start_balance, horizon_days, points, events)


def cashflow_scenario(
    db: Session, space_id: int, horizon_days: int = 90,
    cancel_description_key: str | None = None,
    extra_monthly_saving: float = 0.0, extra_monthly_expense: float = 0.0,
) -> schemas.CashflowScenarioOut:
    """Vergleicht die normale Cashflow-Prognose (cashflow_forecast) mit einer
    einfachen "Was-wäre-wenn"-Variante: ein erkanntes Abo herausrechnen
    und/oder eine zusätzliche monatliche Sparrate bzw. Ausgabe einrechnen -
    bewusst nur diese drei simplen Stellschrauben statt eines vollständigen
    Simulations-Frameworks. Die zusätzliche Sparrate/Ausgabe wird als ein
    einzelnes monatliches Ereignis ab in 30 Tagen angenommen (kein festes
    Kalenderdatum wie beim Gehalt), das reicht für eine grobe Orientierung."""
    accounts = get_accounts(db, space_id)
    start_balance = round(sum(account_balance(db, a) for a in accounts), 2)
    today = date.today()
    end = today + timedelta(days=horizon_days)

    baseline_events = _cashflow_events(db, space_id, end)
    baseline_points = _cashflow_points(start_balance, baseline_events, today, end)
    baseline = _cashflow_summary(start_balance, horizon_days, baseline_points, baseline_events)

    scenario_events = [
        e for e in baseline_events
        if not (cancel_description_key and e.get("description_key") == cancel_description_key)
    ]
    net_monthly = extra_monthly_saving - extra_monthly_expense
    if net_monthly:
        occ = today + timedelta(days=30)
        while occ <= end:
            scenario_events.append({
                "date": occ, "amount": net_monthly, "description": "Szenario-Anpassung", "description_key": None,
            })
            occ += timedelta(days=30)
        scenario_events.sort(key=lambda e: e["date"])
    scenario_points = _cashflow_points(start_balance, scenario_events, today, end)
    scenario = _cashflow_summary(start_balance, horizon_days, scenario_points, scenario_events)

    return schemas.CashflowScenarioOut(baseline=baseline, scenario=scenario)


# ---------- Ignorierte wiederkehrende Zahlungen (Fehlerkennungen) ----------
def get_ignored_recurring_payments(db: Session, space_id: int) -> list[schemas.IgnoredRecurringPaymentOut]:
    rows = (
        db.query(models.IgnoredRecurringPayment)
        .filter(models.IgnoredRecurringPayment.space_id == space_id)
        .order_by(models.IgnoredRecurringPayment.label)
        .all()
    )
    accounts = {a.id: a.name for a in get_accounts(db, space_id)}
    return [
        schemas.IgnoredRecurringPaymentOut(
            id=r.id, account_id=r.account_id, account_name=accounts.get(r.account_id),
            description_key=r.description_key, label=r.label,
        )
        for r in rows
    ]


def create_ignored_recurring_payment(db: Session, space_id: int, data: schemas.IgnoredRecurringPaymentCreate) -> schemas.IgnoredRecurringPaymentOut:
    existing = db.query(models.IgnoredRecurringPayment).filter(
        models.IgnoredRecurringPayment.space_id == space_id,
        models.IgnoredRecurringPayment.account_id == data.account_id,
        models.IgnoredRecurringPayment.description_key == data.description_key,
    ).first()
    row = existing or models.IgnoredRecurringPayment(space_id=space_id, **data.model_dump())
    row.label = data.label
    if not existing:
        db.add(row)
    db.commit()
    db.refresh(row)
    account = db.get(models.Account, row.account_id)
    return schemas.IgnoredRecurringPaymentOut(
        id=row.id, account_id=row.account_id, account_name=account.name if account else None,
        description_key=row.description_key, label=row.label,
    )


def delete_ignored_recurring_payment(db: Session, ignore_id: int, space_id: int) -> bool:
    row = db.query(models.IgnoredRecurringPayment).filter(
        models.IgnoredRecurringPayment.id == ignore_id, models.IgnoredRecurringPayment.space_id == space_id,
    ).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def detect_recurring_transactions(db: Session, space_id: int) -> list[dict]:
    """Gruppiert Buchungen je Konto nach (normalisierter) Bezeichnung und erkennt
    Gruppen mit regelmäßigem zeitlichem Abstand und ähnlichem Betrag als
    wiederkehrende Zahlung (Abo, Miete, Gehalt, ...). Heuristik, kein Vertragsdatenabgleich.
    Als Fehlerkennung ignorierte (Konto, Bezeichnung)-Paare (siehe
    IgnoredRecurringPayment) werden dabei übersprungen - wirkt dadurch auch auf
    Cashflow-Prognose und Überschneidungs-Erkennung, die auf dieser Funktion aufbauen."""
    ignored_keys = {
        (r.account_id, r.description_key)
        for r in db.query(models.IgnoredRecurringPayment).filter(models.IgnoredRecurringPayment.space_id == space_id).all()
    }
    txs = (
        db.query(models.Transaction)
        .join(models.Account)
        .filter(models.Account.space_id == space_id)
        .order_by(models.Transaction.date)
        .all()
    )
    accounts = {a.id: a.name for a in get_accounts(db, space_id)}
    categories = {c.id: c.name for c in db.query(models.Category).all()}

    groups: dict[tuple[int, str], list[models.Transaction]] = {}
    for tx in txs:
        norm = _normalize_description(tx.description)
        if not norm or (tx.account_id, norm) in ignored_keys:
            continue
        groups.setdefault((tx.account_id, norm), []).append(tx)

    results = []
    for (account_id, norm), items in groups.items():
        if len(items) < 3:
            continue
        items.sort(key=lambda t: t.date)
        dates = [t.date for t in items]
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        if not gaps:
            continue
        gap_med = median(gaps)
        freq_label = next(
            (label for label, target, tol in _RECURRING_FREQUENCIES if abs(gap_med - target) <= tol),
            None,
        )
        if not freq_label:
            continue

        amounts = [t.amount for t in items]
        amt_med = median(amounts)
        if amt_med == 0:
            continue
        consistent = sum(1 for a in amounts if abs(a - amt_med) <= max(abs(amt_med) * 0.15, 1.0))
        if consistent / len(amounts) < 0.7:
            continue

        last = items[-1]
        cat_counts: dict[int, int] = {}
        for t in items:
            if t.category_id:
                cat_counts[t.category_id] = cat_counts.get(t.category_id, 0) + 1
        top_category_id = max(cat_counts, key=cat_counts.get) if cat_counts else None

        results.append({
            "description": last.description,
            "description_key": norm,
            "account_id": account_id,
            "account_name": accounts.get(account_id),
            "category_id": top_category_id,
            "category_name": categories.get(top_category_id) if top_category_id else None,
            "frequency": freq_label,
            "avg_amount": round(amt_med, 2),
            "occurrences": len(items),
            "last_date": last.date,
            "next_expected_date": last.date + timedelta(days=round(gap_med)),
            "total_amount": round(sum(amounts), 2),
        })

    results.sort(key=lambda r: r["next_expected_date"])
    return results


def detect_overlapping_contracts(db: Session, space_id: int) -> list[dict]:
    """Gruppiert die schon erkannten wiederkehrenden Zahlungen (siehe
    detect_recurring_transactions) nach Kategorie und markiert Kategorien mit
    mehreren UNTERSCHIEDLICHEN Abos als moegliche Ueberschneidung - typischer
    Fall: zwei gleichzeitig laufende Mobilfunkvertraege oder zwei Versicherungen
    derselben Art, die eigentlich nur eine sein sollten.

    Bewusst kategoriebasiert statt KI-basiert (Markennamen erraten/vergleichen):
    keine neue Ollama-Abhaengigkeit und kein Risiko, zwei unterschiedliche Dienste
    faelschlich als "dasselbe" zu erkennen. Dafuer muss der Nutzer seine
    Kategorien halbwegs sinnvoll vergeben - reiner Heuristik-Kompromiss, kein
    Vertragsdatenabgleich."""
    recurring = detect_recurring_transactions(db, space_id)
    by_category: dict[int, list[dict]] = {}
    for r in recurring:
        if r["category_id"]:
            by_category.setdefault(r["category_id"], []).append(r)

    groups = []
    for cat_id, items in by_category.items():
        if len(items) < 2:
            continue
        monthly_total = sum(
            abs(r["avg_amount"]) * 30.44 / RECURRING_INTERVAL_DAYS.get(r["frequency"], 30.44)
            for r in items
        )
        groups.append({
            "category_id": cat_id,
            "category_name": items[0]["category_name"],
            "items": items,
            "monthly_total": round(monthly_total, 2),
        })
    groups.sort(key=lambda g: -g["monthly_total"])
    return groups


def detect_price_increases(db: Session, space_id: int) -> list[dict]:
    """Erkennt Abos, deren letzte Abbuchung teurer war als die vorherigen üblichen -
    reine Auswertung der ohnehin schon vorhandenen Buchungen, kein neuer Datenbestand
    und keine Bestätigung/Rückfrage bei einer Bank nötig. Braucht mindestens 3
    vorherige, zeitlich und betragsmäßig konsistente Zahlungen, um eine echte
    Preiserhöhung von normaler Schwankung (Rundungsdifferenzen, Fremdwährungskurs)
    zu unterscheiden - dieselbe Heuristik wie detect_recurring_transactions, nur mit
    Blick auf die letzte Zahlung statt auf den Gesamt-Median. Ebenfalls dieselbe
    Ignorierliste (IgnoredRecurringPayment) wie dort."""
    ignored_keys = {
        (r.account_id, r.description_key)
        for r in db.query(models.IgnoredRecurringPayment).filter(models.IgnoredRecurringPayment.space_id == space_id).all()
    }
    txs = (
        db.query(models.Transaction)
        .join(models.Account)
        .filter(models.Account.space_id == space_id)
        .order_by(models.Transaction.date)
        .all()
    )
    accounts = {a.id: a.name for a in get_accounts(db, space_id)}

    groups: dict[tuple[int, str], list[models.Transaction]] = {}
    for tx in txs:
        norm = _normalize_description(tx.description)
        if not norm or (tx.account_id, norm) in ignored_keys:
            continue
        groups.setdefault((tx.account_id, norm), []).append(tx)

    results = []
    for (account_id, norm), items in groups.items():
        if len(items) < 4:
            continue
        items.sort(key=lambda t: t.date)
        prior, last = items[:-1], items[-1]

        gaps = [(prior[i + 1].date - prior[i].date).days for i in range(len(prior) - 1)]
        if not gaps:
            continue
        gap_med = median(gaps)
        freq_label = next(
            (label for label, target, tol in _RECURRING_FREQUENCIES if abs(gap_med - target) <= tol), None,
        )
        if not freq_label:
            continue
        # Letzte Zahlung muss zeitlich noch zur Serie passen - sonst vermutlich
        # gekündigt oder ein neues, unabhängiges Muster, keine "Erhöhung".
        if (last.date - prior[-1].date).days > RECURRING_INTERVAL_DAYS[freq_label] * 1.5:
            continue

        prior_amounts = [t.amount for t in prior]
        prior_median = median(prior_amounts)
        if prior_median >= 0 or last.amount >= 0:
            continue  # nur Ausgaben, keine wiederkehrenden Einnahmen (z.B. Gehalt)

        consistent = sum(1 for a in prior_amounts if abs(a - prior_median) <= max(abs(prior_median) * 0.1, 1.0))
        if consistent / len(prior_amounts) < 0.8:
            continue  # vorher schon nicht stabil genug fuer eine verlaessliche Aussage

        increase_pct = (abs(last.amount) - abs(prior_median)) / abs(prior_median)
        if increase_pct < 0.05:
            continue

        results.append({
            "description": last.description,
            "description_key": norm,
            "account_id": account_id,
            "account_name": accounts.get(account_id),
            "frequency": freq_label,
            "old_amount": round(prior_median, 2),
            "new_amount": round(last.amount, 2),
            "increase_pct": round(increase_pct * 100, 1),
            "changed_date": last.date,
        })

    results.sort(key=lambda r: -r["increase_pct"])
    return results


def detect_spending_anomalies(db: Session, space_id: int, lookback_months: int = 3, threshold_pct: float = 30.0) -> list[dict]:
    """Vergleicht die Ausgaben je Kategorie im laufenden Monat mit dem Durchschnitt
    der letzten `lookback_months` abgeschlossenen Monate derselben Kategorie - anders
    als budget_progress() unabhängig davon, ob überhaupt ein Budget-Limit gesetzt
    wurde, deckt also auch Kategorien ohne Budget ab. Der laufende Monat wird auf
    einen vollen Monat hochgerechnet (gleiches Vorgehen wie budget_progress.
    projected_total), sonst wirkt er an den ersten Tagen immer künstlich niedrig -
    braucht deshalb mindestens 5 vergangene Tage im Monat, um überhaupt zu werten."""
    today = date.today()
    if today.day < 5:
        return []
    days_in_month = calendar.monthrange(today.year, today.month)[1]

    rows = (
        db.query(
            models.Transaction.category_id,
            extract("year", models.Transaction.date).label("y"),
            extract("month", models.Transaction.date).label("m"),
            func.sum(models.Transaction.amount).label("total"),
        )
        .join(models.Account)
        .filter(
            models.Account.space_id == space_id,
            models.Transaction.category_id.isnot(None),
            models.Transaction.is_transfer.is_(False),
        )
        .group_by(models.Transaction.category_id, "y", "m")
        .all()
    )
    by_cat_month = {(r.category_id, int(r.y), int(r.m)): r.total for r in rows}
    category_names = {c.id: c.name for c in db.query(models.Category).all()}
    cat_ids = {cid for cid, _, _ in by_cat_month.keys()}

    results = []
    for cat_id in cat_ids:
        current_total = by_cat_month.get((cat_id, today.year, today.month))
        if current_total is None or current_total >= 0:
            continue
        current_spent = abs(current_total)
        projected_spent = current_spent / today.day * days_in_month

        prior_totals = []
        yy, mm = today.year, today.month
        for _ in range(lookback_months):
            mm -= 1
            if mm == 0:
                mm, yy = 12, yy - 1
            t = by_cat_month.get((cat_id, yy, mm))
            if t is not None and t < 0:
                prior_totals.append(abs(t))
        if len(prior_totals) < 2:
            continue  # zu wenig Historie fuer einen verlaesslichen Vergleich

        avg_prior = sum(prior_totals) / len(prior_totals)
        if avg_prior <= 0:
            continue
        deviation_pct = (projected_spent - avg_prior) / avg_prior * 100
        if deviation_pct < threshold_pct:
            continue

        results.append({
            "category_id": cat_id,
            "category_name": category_names.get(cat_id, "Unbekannt"),
            "current_spent": round(current_spent, 2),
            "projected_spent": round(projected_spent, 2),
            "avg_prior_months": round(avg_prior, 2),
            "deviation_pct": round(deviation_pct, 1),
        })

    results.sort(key=lambda r: -r["deviation_pct"])
    return results


def is_anomaly_notified(db: Session, space_id: int, key: str) -> bool:
    return (
        db.query(models.NotifiedAnomaly)
        .filter(models.NotifiedAnomaly.space_id == space_id, models.NotifiedAnomaly.key == key)
        .first()
        is not None
    )


def mark_anomaly_notified(db: Session, space_id: int, key: str) -> None:
    db.add(models.NotifiedAnomaly(space_id=space_id, key=key))
    db.commit()


# ---------- Eigene Regeln (Sofort-Alarme) ----------
def get_alert_rules(db: Session, space_id: int) -> list[models.AlertRule]:
    rules = db.query(models.AlertRule).filter(models.AlertRule.space_id == space_id).order_by(models.AlertRule.id).all()
    for r in rules:
        r.category_name = r.category.name if r.category else None
        r.account_name = r.account.name if r.account else None
        r.goal_title = r.goal.title if r.goal else None
    return rules


def create_alert_rule(db: Session, space_id: int, data: schemas.AlertRuleCreate) -> models.AlertRule:
    rule = models.AlertRule(
        space_id=space_id, rule_type=data.rule_type, category_id=data.category_id,
        account_id=data.account_id, goal_id=data.goal_id,
        threshold=data.threshold, active=data.active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    rule.category_name = rule.category.name if rule.category else None
    rule.account_name = rule.account.name if rule.account else None
    rule.goal_title = rule.goal.title if rule.goal else None
    return rule


def update_alert_rule(db: Session, rule: models.AlertRule, data: schemas.AlertRuleUpdate) -> models.AlertRule:
    if data.threshold is not None:
        rule.threshold = data.threshold
    if data.active is not None:
        rule.active = data.active
    db.commit()
    db.refresh(rule)
    rule.category_name = rule.category.name if rule.category else None
    rule.account_name = rule.account.name if rule.account else None
    rule.goal_title = rule.goal.title if rule.goal else None
    return rule


def delete_alert_rule(db: Session, rule: models.AlertRule) -> None:
    db.delete(rule)
    db.commit()


def evaluate_alert_rule(db: Session, rule: models.AlertRule) -> tuple[bool, str]:
    """Prüft eine einzelne Regel rein lesend (kein last_triggered_date-
    Update) - main._scheduled_alert_rules entscheidet anhand dessen, ob heute
    schon gemeldet wurde. Bewusst nur die Regeltypen aus AlertRuleType,
    keine freie Bedingungs-Engine."""
    if rule.rule_type == models.AlertRuleType.category_spend_above:
        if not rule.category_id:
            return False, ""
        today = date.today()
        total = (
            db.query(func.sum(models.Transaction.amount))
            .join(models.Account)
            .filter(
                models.Account.space_id == rule.space_id,
                models.Transaction.category_id == rule.category_id,
                models.Transaction.is_transfer.is_(False),
                models.Transaction.date >= today.replace(day=1),
            )
            .scalar()
        ) or 0
        spent = abs(total) if total < 0 else 0.0
        if spent > rule.threshold:
            cat = db.query(models.Category).filter(models.Category.id == rule.category_id).first()
            cat_name = cat.name if cat else "?"
            return True, (f"🔔 Regel ausgelöst: Ausgaben in „{cat_name}“ diesen Monat {spent:.2f} € "
                           f"(Schwelle {rule.threshold:.2f} €).")
        return False, ""

    if rule.rule_type == models.AlertRuleType.account_balance_below:
        if not rule.account_id:
            return False, ""
        account = db.query(models.Account).filter(models.Account.id == rule.account_id).first()
        if not account:
            return False, ""
        balance = account_balance(db, account)
        if balance < rule.threshold:
            return True, (f"🔔 Regel ausgelöst: Kontostand „{account.name}“ liegt bei {balance:.2f} € "
                           f"(Schwelle {rule.threshold:.2f} €).")
        return False, ""

    if rule.rule_type == models.AlertRuleType.category_deviation:
        if not rule.category_id:
            return False, ""
        anomalies = detect_spending_anomalies(db, rule.space_id, threshold_pct=rule.threshold)
        match = next((a for a in anomalies if a["category_id"] == rule.category_id), None)
        if match:
            return True, (f"🔔 Regel ausgelöst: „{match['category_name']}“ liegt diesen Monat hochgerechnet bei "
                           f"{match['projected_spent']:.2f} € (sonst ø {match['avg_prior_months']:.2f} €, "
                           f"+{match['deviation_pct']:.0f}%, Schwelle {rule.threshold:.0f}%).")
        return False, ""

    if rule.rule_type == models.AlertRuleType.goal_progress_above:
        if not rule.goal_id:
            return False, ""
        goal = db.query(models.Goal).filter(models.Goal.id == rule.goal_id).first()
        if not goal or goal.status != models.GoalStatus.open:
            return False, ""
        # Lokaler Import: goals.py importiert seinerseits crud (fuer
        # Kontostand/Depotwert), ein Modul-Import hier waere zirkulaer. Zur
        # Laufzeit ist crud laengst vollstaendig geladen.
        from . import goals as goals_module

        result = goals_module.evaluate_metric(db, goal)
        if result.value is None or result.threshold is None or result.error:
            return False, ""
        pct = goals_module.progress_percent(result.value, result.threshold, result.comparison)
        if pct >= rule.threshold:
            return True, (f"🔔 Regel ausgeloest: Ziel „{goal.title}“ ist zu {pct:.0f}% erreicht "
                           f"(Schwelle {rule.threshold:.0f}%).")
        return False, ""

    return False, ""


# ---------- Kündigungsfrist-Erinnerungen ----------
def _contract_reminder_out(r: models.ContractReminder, account_name: str | None) -> schemas.ContractReminderOut:
    reminder_date = r.renewal_date - timedelta(days=r.notice_period_days)
    return schemas.ContractReminderOut(
        id=r.id, account_id=r.account_id, account_name=account_name,
        description_key=r.description_key, label=r.label,
        notice_period_days=r.notice_period_days, renewal_date=r.renewal_date,
        auto_advance_frequency=r.auto_advance_frequency, reminder_date=reminder_date,
        days_until_reminder=(reminder_date - date.today()).days,
        due=date.today() >= reminder_date,
        notes=r.notes, should_cancel=r.should_cancel,
    )


def get_contract_reminders(db: Session, space_id: int) -> list[schemas.ContractReminderOut]:
    rows = (
        db.query(models.ContractReminder)
        .filter(models.ContractReminder.space_id == space_id)
        .order_by(models.ContractReminder.renewal_date)
        .all()
    )
    accounts = {a.id: a.name for a in get_accounts(db, space_id)}
    return [_contract_reminder_out(r, accounts.get(r.account_id)) for r in rows]


def create_contract_reminder(db: Session, space_id: int, data: schemas.ContractReminderCreate) -> schemas.ContractReminderOut:
    row = models.ContractReminder(space_id=space_id, **data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    account = db.get(models.Account, row.account_id)
    return _contract_reminder_out(row, account.name if account else None)


def update_contract_reminder(db: Session, reminder_id: int, space_id: int, data: schemas.ContractReminderUpdate) -> schemas.ContractReminderOut | None:
    row = db.query(models.ContractReminder).filter(
        models.ContractReminder.id == reminder_id, models.ContractReminder.space_id == space_id,
    ).first()
    if not row:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    # Neues Verlängerungsdatum -> alte Erinnerungssperre ist hinfällig.
    if "renewal_date" in data.model_dump(exclude_unset=True):
        row.last_reminded_for = None
    db.commit()
    db.refresh(row)
    account = db.get(models.Account, row.account_id)
    return _contract_reminder_out(row, account.name if account else None)


def delete_contract_reminder(db: Session, reminder_id: int, space_id: int) -> bool:
    row = db.query(models.ContractReminder).filter(
        models.ContractReminder.id == reminder_id, models.ContractReminder.space_id == space_id,
    ).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def evaluate_contract_reminders(db: Session, space_id: int) -> list[models.ContractReminder]:
    """Läuft täglich (siehe main._check_daily_alerts): rückt abgelaufene
    Verlängerungstermine automatisch weiter (nur wenn eine Frequenz
    hinterlegt ist - sonst bleibt das Datum stehen, bis der Nutzer es selbst
    korrigiert) und gibt die Erinnerungen zurück, die JETZT erstmals fällig
    sind (für genau diesen Verlängerungstermin noch nicht gemeldet)."""
    today = date.today()
    due: list[models.ContractReminder] = []
    rows = db.query(models.ContractReminder).filter(models.ContractReminder.space_id == space_id).all()
    for r in rows:
        interval = RECURRING_INTERVAL_DAYS.get(r.auto_advance_frequency)
        if interval:
            while r.renewal_date < today:
                r.renewal_date += timedelta(days=interval)
                r.last_reminded_for = None
        reminder_date = r.renewal_date - timedelta(days=r.notice_period_days)
        if today >= reminder_date and r.last_reminded_for != r.renewal_date:
            r.last_reminded_for = r.renewal_date
            due.append(r)
    db.commit()
    return due


# ---------- Rückgabefristen ----------
def _return_deadline_out(r: models.ReturnDeadline, tx: models.Transaction | None) -> schemas.ReturnDeadlineOut:
    deadline_date = r.start_date + timedelta(days=r.deadline_days)
    return schemas.ReturnDeadlineOut(
        id=r.id, transaction_id=r.transaction_id,
        transaction_description=tx.description if tx else None,
        transaction_amount=tx.amount if tx else None,
        start_date=r.start_date, deadline_days=r.deadline_days,
        remind_days_before=r.remind_days_before, returned=r.returned,
        deadline_date=deadline_date,
        days_left=(deadline_date - date.today()).days,
        due=(not r.returned) and date.today() >= deadline_date - timedelta(days=r.remind_days_before),
    )


def get_return_deadlines(db: Session, space_id: int) -> list[schemas.ReturnDeadlineOut]:
    rows = (
        db.query(models.ReturnDeadline)
        .join(models.Transaction, models.ReturnDeadline.transaction_id == models.Transaction.id)
        .join(models.Account, models.Transaction.account_id == models.Account.id)
        .filter(models.Account.space_id == space_id)
        .order_by(models.ReturnDeadline.start_date)
        .all()
    )
    tx_by_id = {t.id: t for t in db.query(models.Transaction).filter(
        models.Transaction.id.in_([r.transaction_id for r in rows])
    ).all()} if rows else {}
    return [_return_deadline_out(r, tx_by_id.get(r.transaction_id)) for r in rows]


def create_return_deadline(db: Session, space_id: int, data: schemas.ReturnDeadlineCreate) -> schemas.ReturnDeadlineOut | None:
    tx = get_transaction(db, data.transaction_id, space_id)
    if not tx:
        return None
    row = models.ReturnDeadline(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _return_deadline_out(row, tx)


def update_return_deadline(db: Session, deadline_id: int, space_id: int, data: schemas.ReturnDeadlineUpdate) -> schemas.ReturnDeadlineOut | None:
    row = (
        db.query(models.ReturnDeadline)
        .join(models.Transaction, models.ReturnDeadline.transaction_id == models.Transaction.id)
        .join(models.Account, models.Transaction.account_id == models.Account.id)
        .filter(models.ReturnDeadline.id == deadline_id, models.Account.space_id == space_id)
        .first()
    )
    if not row:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    # Frist/Startdatum geändert -> eine schon verschickte Erinnerung war ggf.
    # für den alten Termin - bei neuem Termin wieder erinnerbar machen.
    if {"start_date", "deadline_days"} & set(data.model_dump(exclude_unset=True)):
        row.reminded = False
    db.commit()
    db.refresh(row)
    return _return_deadline_out(row, get_transaction(db, row.transaction_id, space_id))


def delete_return_deadline(db: Session, deadline_id: int, space_id: int) -> bool:
    row = (
        db.query(models.ReturnDeadline)
        .join(models.Transaction, models.ReturnDeadline.transaction_id == models.Transaction.id)
        .join(models.Account, models.Transaction.account_id == models.Account.id)
        .filter(models.ReturnDeadline.id == deadline_id, models.Account.space_id == space_id)
        .first()
    )
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def evaluate_return_deadlines(db: Session, space_id: int) -> list[dict]:
    """Läuft täglich (siehe main._check_daily_alerts): meldet jede noch nicht
    zurückgeschickte Frist, die in remind_days_before-Tagen oder weniger
    abläuft, genau einmal (kein wiederkehrender Termin wie bei
    ContractReminder - ein einmaliger Hinweis reicht)."""
    today = date.today()
    due: list[dict] = []
    rows = (
        db.query(models.ReturnDeadline)
        .join(models.Transaction, models.ReturnDeadline.transaction_id == models.Transaction.id)
        .join(models.Account, models.Transaction.account_id == models.Account.id)
        .filter(
            models.Account.space_id == space_id,
            models.ReturnDeadline.returned.is_(False),
            models.ReturnDeadline.reminded.is_(False),
        )
        .all()
    )
    for r in rows:
        deadline_date = r.start_date + timedelta(days=r.deadline_days)
        if today >= deadline_date - timedelta(days=r.remind_days_before):
            r.reminded = True
            tx = get_transaction(db, r.transaction_id, space_id)
            due.append({
                "label": (tx.description if tx and tx.description else "Kauf"),
                "deadline_date": deadline_date,
                "days_left": (deadline_date - today).days,
            })
    if due:
        db.commit()
    return due


CREDITCARD_BILL_REMIND_DAYS = 3


def next_creditcard_bill(db: Session, space_id: int):
    """Naechste bevorstehende/aktuelle Kreditkarten-Faelligkeit fuers Hub -
    reine Anzeige, kein Reminder-Statuswechsel wie bei evaluate_*. Haengt
    entweder an einem Konto oder einer Schuld (siehe CreditCardBill), daher
    LEFT JOIN auf beide statt eines einzelnen INNER JOIN."""
    return (
        db.query(models.CreditCardBill)
        .outerjoin(models.Account, models.CreditCardBill.account_id == models.Account.id)
        .outerjoin(models.Debt, models.CreditCardBill.debt_id == models.Debt.id)
        .filter(
            models.CreditCardBill.due_date.is_not(None),
            (models.Account.space_id == space_id) | (models.Debt.space_id == space_id),
        )
        .order_by(models.CreditCardBill.due_date.desc())
        .first()
    )


def evaluate_creditcard_bills(db: Session, space_id: int) -> list[dict]:
    """Läuft täglich (siehe main._check_daily_alerts): meldet jede erkannte
    Kreditkarten-Rechnung CREDITCARD_BILL_REMIND_DAYS Tage vor Fälligkeit genau
    einmal - analog zu evaluate_return_deadlines."""
    today = date.today()
    due: list[dict] = []
    rows = (
        db.query(models.CreditCardBill)
        .outerjoin(models.Account, models.CreditCardBill.account_id == models.Account.id)
        .outerjoin(models.Debt, models.CreditCardBill.debt_id == models.Debt.id)
        .filter(
            (models.Account.space_id == space_id) | (models.Debt.space_id == space_id),
            models.CreditCardBill.notified.is_(False),
            models.CreditCardBill.due_date.is_not(None),
        )
        .all()
    )
    for bill in rows:
        if today >= bill.due_date - timedelta(days=CREDITCARD_BILL_REMIND_DAYS):
            bill.notified = True
            label = (bill.account.name if bill.account else None) or (bill.debt.name if bill.debt else None) or "Kreditkarte"
            due.append({
                "account_name": label,
                "due_date": bill.due_date,
                "amount": bill.amount,
                "days_left": (bill.due_date - today).days,
            })
    if due:
        db.commit()
    return due


def search_receipts(db: Session, space_id: int, query: str, limit: int = 50) -> list[models.Transaction]:
    """Volltextsuche über Beleg-Text (receipt_text, siehe main.
    _scheduled_receipt_indexing) UND Beschreibung/Notiz - reines SQL LIKE
    statt eines Suchindex (SQLite FTS5 wäre ein weiterer Baustein, bei der
    hier üblichen Beleg-Anzahl eines Einzelnutzers unnötig). Nur Buchungen
    MIT Beleg, sonst wäre es nur die normale Buchungssuche noch einmal."""
    q = f"%{query.strip()}%"
    return (
        db.query(models.Transaction)
        .join(models.Account)
        .filter(
            models.Account.space_id == space_id,
            models.Transaction.receipt_filename.isnot(None),
            (models.Transaction.receipt_text.ilike(q))
            | (models.Transaction.description.ilike(q))
            | (models.Transaction.notes.ilike(q)),
        )
        .order_by(models.Transaction.date.desc())
        .limit(limit)
        .all()
    )


def find_duplicate_transactions(db: Session, space_id: int) -> list[dict]:
    """Findet Buchungen, die in Konto, Datum, Betrag, Beschreibung UND Notiz
    exakt übereinstimmen - bewusst kein Fuzzy-Match, um keine echten, nur
    zufällig ähnlichen Buchungen (z.B. zwei Kartenzahlungen mit demselben
    runden Betrag am selben Tag) faelschlich als Duplikat zu melden.

    Entstehen kann so etwas z.B. wenn eine importierte Buchung nachträglich
    einem anderen Konto zugeordnet wird und der Sync-Fingerabdruck dadurch
    nicht mehr zur nächsten Synchronisierung passt (siehe update_transaction) -
    dieser Check ist das dauerhafte Sicherheitsnetz dafür, nicht nur eine
    einmalige Aufräumaktion."""
    key_cols = (
        models.Transaction.account_id, models.Transaction.date, models.Transaction.amount,
        models.Transaction.description, models.Transaction.notes,
    )
    dup_keys = (
        db.query(*key_cols)
        .join(models.Account)
        .filter(models.Account.space_id == space_id)
        .group_by(*key_cols)
        .having(func.count(models.Transaction.id) > 1)
        .all()
    )
    groups = []
    for account_id, tx_date, amount, description, notes in dup_keys:
        rows = (
            db.query(models.Transaction)
            .filter(
                models.Transaction.account_id == account_id, models.Transaction.date == tx_date,
                models.Transaction.amount == amount, models.Transaction.description == description,
                models.Transaction.notes == notes,
            )
            .order_by(models.Transaction.id)
            .all()
        )
        account = db.get(models.Account, account_id)
        groups.append({
            "account_id": account_id, "account_name": account.name if account else "",
            "date": tx_date, "amount": amount, "description": description,
            "transaction_ids": [r.id for r in rows],
        })
    groups.sort(key=lambda g: g["date"], reverse=True)
    return groups


def get_transaction(db: Session, transaction_id: int, space_id: int):
    return (
        db.query(models.Transaction)
        .join(models.Account)
        .filter(models.Transaction.id == transaction_id, models.Account.space_id == space_id)
        .first()
    )


def create_transaction(db: Session, transaction: schemas.TransactionCreate):
    db_transaction = models.Transaction(**transaction.model_dump())
    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)
    return db_transaction


def update_transaction(db: Session, transaction_id: int, space_id: int, data: schemas.TransactionUpdate):
    db_transaction = get_transaction(db, transaction_id, space_id)
    if not db_transaction:
        return None
    changes = data.model_dump(exclude_unset=True)
    # Wird eine importierte Buchung auf ein anderes Konto verschoben (oder Datum/
    # Betrag/Text geaendert), muss ihr Sync-Fingerabdruck mitwandern - sonst haelt
    # der naechste Bank-Sync sie faelschlich fuer neu und importiert sie ein
    # zweites Mal. Live beobachtet: Konto nach dem Einrichten manuell korrigiert,
    # der Fingerabdruck blieb am alten Konto haengen, 223 Dubletten entstanden.
    # Nur bei per Inhalt gehashten Buchungen (Enable Banking/FinTS) - bei per
    # externer ID gehashten (PayPal) wuerde ein Neuberechnen den eigentlich noch
    # gueltigen Fingerabdruck kaputt machen, das laesst sich von aussen nicht
    # unterscheiden, also lieber unangetastet lassen.
    relevant = {"account_id", "date", "amount", "description", "notes"}
    if db_transaction.import_hash and relevant & changes.keys():
        old_hash_input = f"{db_transaction.account_id}|{db_transaction.date}|{db_transaction.amount}|{db_transaction.description}|{db_transaction.notes}"
        if db_transaction.import_hash == hashlib.sha256(old_hash_input.encode()).hexdigest():
            new_account_id = changes.get("account_id", db_transaction.account_id)
            new_date = changes.get("date", db_transaction.date)
            new_amount = changes.get("amount", db_transaction.amount)
            new_description = changes.get("description", db_transaction.description)
            new_notes = changes.get("notes", db_transaction.notes)
            new_hash_input = f"{new_account_id}|{new_date}|{new_amount}|{new_description}|{new_notes}"
            db_transaction.import_hash = hashlib.sha256(new_hash_input.encode()).hexdigest()
    if changes.get("category_id") is not None and changes["category_id"] != db_transaction.category_id:
        db_transaction.categorized_at = datetime.utcnow()
    for key, value in changes.items():
        setattr(db_transaction, key, value)
    db.commit()
    db.refresh(db_transaction)
    return db_transaction


def delete_transaction(db: Session, transaction_id: int, space_id: int):
    db_transaction = get_transaction(db, transaction_id, space_id)
    if db_transaction:
        db.delete(db_transaction)
        db.commit()
    return db_transaction


def bulk_set_category(db: Session, space_id: int, transaction_ids: list[int], category_id: int | None) -> int:
    """Weist mehreren Buchungen auf einmal dieselbe Kategorie zu (oder entfernt
    sie mit category_id=None) - fuer das manuelle Aufraeumen des Kategorisierungs-
    Rueckstands per Mehrfachauswahl, ohne auf die KI zu warten. Ueber space_id
    join gefiltert, damit niemand IDs aus einem fremden Bereich raten kann."""
    rows = (
        db.query(models.Transaction)
        .join(models.Account)
        .filter(models.Account.space_id == space_id, models.Transaction.id.in_(transaction_ids))
        .all()
    )
    for tx in rows:
        tx.category_id = category_id
        if category_id is not None:
            tx.categorized_at = datetime.utcnow()
    db.commit()
    return len(rows)


# ---------- Trips ----------
def get_trips(db: Session, space_id: int):
    return db.query(models.Trip).filter(models.Trip.space_id == space_id).order_by(models.Trip.start_date.desc()).all()


def get_trip(db: Session, trip_id: int, space_id: int):
    return db.query(models.Trip).filter(models.Trip.id == trip_id, models.Trip.space_id == space_id).first()


def create_trip(db: Session, data: schemas.TripCreate, space_id: int):
    trip = models.Trip(**data.model_dump(), space_id=space_id)
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return trip


def update_trip(db: Session, trip_id: int, space_id: int, data: schemas.TripUpdate):
    trip = get_trip(db, trip_id, space_id)
    if not trip:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(trip, key, value)
    db.commit()
    db.refresh(trip)
    return trip


def delete_trip(db: Session, trip_id: int, space_id: int):
    trip = get_trip(db, trip_id, space_id)
    if trip:
        db.query(models.Transaction).filter(models.Transaction.trip_id == trip_id).update({"trip_id": None})
        db.delete(trip)
        db.commit()
    return trip


def trip_summary(db: Session, trip: models.Trip):
    total = (
        db.query(func.coalesce(func.sum(models.Transaction.amount), 0.0))
        .filter(models.Transaction.trip_id == trip.id)
        .scalar()
    )
    count = (
        db.query(func.count(models.Transaction.id))
        .filter(models.Transaction.trip_id == trip.id)
        .scalar()
    )
    return schemas.TripOut(
        id=trip.id,
        name=trip.name,
        start_date=trip.start_date,
        end_date=trip.end_date,
        budget=trip.budget,
        total_spent=round(abs(min(0.0, total or 0.0)), 2),
        transaction_count=count or 0,
    )


# ---------- Budgets ----------
def get_budgets(db: Session, space_id: int):
    return db.query(models.Budget).filter(models.Budget.space_id == space_id).all()


def upsert_budget(db: Session, space_id: int, data: schemas.BudgetCreate):
    budget = (
        db.query(models.Budget)
        .filter(models.Budget.space_id == space_id, models.Budget.category_id == data.category_id)
        .first()
    )
    if budget:
        budget.monthly_limit = data.monthly_limit
    else:
        budget = models.Budget(space_id=space_id, category_id=data.category_id, monthly_limit=data.monthly_limit)
        db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget


def delete_budget(db: Session, space_id: int, category_id: int):
    budget = (
        db.query(models.Budget)
        .filter(models.Budget.space_id == space_id, models.Budget.category_id == category_id)
        .first()
    )
    if budget:
        db.delete(budget)
        db.commit()
    return budget


def suggest_budgets(db: Session, space_id: int, months: int = 3) -> list[dict]:
    """Schlägt ein Monatslimit für Ausgaben-Kategorien vor, die noch kein
    Budget haben - Durchschnitt der letzten `months` Monate plus 10% Puffer
    (auf 5 EUR gerundet), damit normale Schwankungen nicht sofort als
    überschritten gemeldet werden. Bewusst konservativ: nur Kategorien mit
    Buchungen in mindestens 2 verschiedenen Monaten UND mindestens 3
    Buchungen insgesamt - eine einzelne Anschaffung in einem Monat soll kein
    dauerhaftes Budget vorschlagen."""
    existing_category_ids = {b.category_id for b in get_budgets(db, space_id)}
    cutoff = date.today() - timedelta(days=months * 31)

    rows = (
        db.query(models.Transaction)
        .join(models.Account)
        .filter(
            models.Account.space_id == space_id,
            models.Transaction.category_id.isnot(None),
            models.Transaction.is_transfer.is_(False),
            models.Transaction.amount < 0,
            models.Transaction.date >= cutoff,
        )
        .all()
    )
    by_category: dict[int, list[models.Transaction]] = {}
    for t in rows:
        by_category.setdefault(t.category_id, []).append(t)

    categories = {c.id: c for c in db.query(models.Category).filter(models.Category.type == models.CategoryType.ausgabe).all()}
    suggestions = []
    for category_id, txs in by_category.items():
        if category_id in existing_category_ids or category_id not in categories:
            continue
        distinct_months = {(t.date.year, t.date.month) for t in txs}
        if len(distinct_months) < 2 or len(txs) < 3:
            continue
        total = sum(abs(t.amount) for t in txs)
        avg_monthly = total / len(distinct_months)
        suggested = round((avg_monthly * 1.1) / 5) * 5
        suggestions.append({
            "category_id": category_id, "category_name": categories[category_id].name,
            "suggested_limit": float(suggested), "months_used": len(distinct_months),
            "avg_monthly_spend": round(avg_monthly, 2),
        })
    suggestions.sort(key=lambda s: -s["avg_monthly_spend"])
    return suggestions


def budget_progress(db: Session, space_id: int, year: int, month: int | None = None):
    budgets = get_budgets(db, space_id)
    result = []
    months_factor = 1 if month else 12

    # Hochrechnung nur sinnvoll für den Monat, der gerade läuft - bei einem
    # abgeschlossenen oder zukünftigen Monat gibt es kein "aktuelles Tempo".
    today = date.today()
    is_current_month = month == today.month and year == today.year
    days_in_month = calendar.monthrange(year, month)[1] if month else None
    days_elapsed = today.day if is_current_month else None

    for b in budgets:
        query = (
            db.query(func.coalesce(func.sum(models.Transaction.amount), 0.0))
            .join(models.Account)
            .filter(
                models.Account.space_id == space_id,
                models.Transaction.category_id == b.category_id,
                extract("year", models.Transaction.date) == year,
            )
        )
        if month:
            query = query.filter(extract("month", models.Transaction.date) == month)
        spent = abs(min(0.0, query.scalar() or 0.0))
        limit = round(b.monthly_limit * months_factor, 2)

        projected = None
        if is_current_month and days_elapsed:
            projected = round(spent / days_elapsed * days_in_month, 2)

        result.append(
            schemas.BudgetProgress(
                category_id=b.category_id,
                category_name=b.category.name if b.category else "Unbekannt",
                limit=limit,
                spent=round(spent, 2),
                remaining=round(limit - spent, 2),
                percent=round((spent / limit * 100) if limit else 0.0, 1),
                projected_total=projected,
            )
        )
    return sorted(result, key=lambda r: r.percent, reverse=True)


def set_receipt(db: Session, transaction_id: int, space_id: int, filename: str | None):
    db_transaction = get_transaction(db, transaction_id, space_id)
    if db_transaction:
        db_transaction.receipt_filename = filename
        db.commit()
        db.refresh(db_transaction)
    return db_transaction


# ---------- Holdings (Investments) ----------
def get_holdings(db: Session, space_id: int):
    return (
        db.query(models.Holding)
        .filter(models.Holding.space_id == space_id)
        .order_by(models.Holding.name)
        .all()
    )


def get_holding(db: Session, holding_id: int, space_id: int):
    return (
        db.query(models.Holding)
        .filter(models.Holding.id == holding_id, models.Holding.space_id == space_id)
        .first()
    )


def find_holding_by_symbol(db: Session, space_id: int, asset_type, symbol: str) -> models.Holding | None:
    """Sucht eine bestehende Position mit demselben Symbol (gross-/klein-
    schreibungsunabhaengig) - dieselbe Logik, die main.py schon beim Beleg-
    Chat-Import und beim CSV-Import nutzt, hier als gemeinsamer Helfer auch
    fuer die manuelle "Neue Position"-Eingabe (siehe main.create_holding),
    damit ein zweiter Kauf derselben Aktie dort als weiterer Vorgang an die
    bestehende Position gehaengt wird statt eine zweite, doppelte Zeile
    anzulegen."""
    symbol_lower = symbol.strip().lower()
    return next(
        (h for h in get_holdings(db, space_id) if h.asset_type == asset_type and h.symbol.lower() == symbol_lower),
        None,
    )


def create_holding(db: Session, data: schemas.HoldingCreate, space_id: int):
    holding = models.Holding(**data.model_dump(), space_id=space_id)
    db.add(holding)
    db.flush()
    if holding.quantity:
        db.add(models.HoldingLot(
            holding_id=holding.id,
            date=holding.purchase_date or date.today(),
            type=models.LotType.kauf,
            quantity=holding.quantity,
            price_per_unit=holding.purchase_price,
        ))
    db.commit()
    db.refresh(holding)
    return holding


def update_holding(db: Session, holding_id: int, space_id: int, data: schemas.HoldingUpdate):
    holding = get_holding(db, holding_id, space_id)
    if not holding:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(holding, key, value)
    db.commit()
    db.refresh(holding)
    return holding


def delete_holding(db: Session, holding_id: int, space_id: int):
    holding = get_holding(db, holding_id, space_id)
    if holding:
        db.delete(holding)
        db.commit()
    return holding


RISK_LEVELS = {
    "krypto": "hoch",
    "aktie": "mittel-hoch",
    "etf": "mittel",
    "anleihe": "niedrig",
    "sonstiges": "unbekannt",
}


def holding_out(h: models.Holding) -> schemas.HoldingOut:
    current = h.current_price if h.current_price is not None else h.purchase_price
    purchase_value = round(h.quantity * h.purchase_price, 2)
    current_value = round(h.quantity * current, 2)
    gain_abs = round(current_value - purchase_value, 2)
    gain_pct = round((gain_abs / purchase_value * 100) if purchase_value else 0.0, 2)
    return schemas.HoldingOut(
        id=h.id,
        asset_type=h.asset_type,
        name=h.name,
        symbol=h.symbol,
        sector=h.sector,
        risk_level=RISK_LEVELS.get(h.asset_type.value if hasattr(h.asset_type, "value") else h.asset_type, "unbekannt"),
        quantity=h.quantity,
        purchase_price=h.purchase_price,
        purchase_date=h.purchase_date,
        current_price=h.current_price,
        price_updated_at=h.price_updated_at,
        purchase_value=purchase_value,
        current_value=current_value,
        gain_abs=gain_abs,
        gain_pct=gain_pct,
        lot_count=len(h.lots),
    )


# ---------- Holding-Lots (einzelne Käufe/Verkäufe) ----------
def recompute_holding_from_lots(db: Session, holding: models.Holding):
    """Leitet Stückzahl und durchschnittlichen Einstandspreis aus den Lots ab
    (Durchschnittskostenmethode: ein Verkauf reduziert die Stückzahl zum aktuellen
    Durchschnittspreis, unabhängig davon welches konkrete Lot verkauft wurde)."""
    lots = sorted(holding.lots, key=lambda l: (l.date, l.id))
    qty, total_cost, first_date = 0.0, 0.0, None
    for lot in lots:
        if lot.type in (models.LotType.kauf, models.LotType.staking):
            if first_date is None or (lot.date and lot.date < first_date):
                first_date = lot.date
            qty += lot.quantity
            total_cost += lot.quantity * lot.price_per_unit
        elif lot.type == models.LotType.verkauf:
            if qty > 0:
                avg_cost = total_cost / qty
                sell_qty = min(lot.quantity, qty)
                total_cost -= sell_qty * avg_cost
                qty -= sell_qty
        # dividende: reine Ertragsbuchung, wirkt sich nicht auf Bestand/Einstand aus
    holding.quantity = round(max(qty, 0.0), 8)
    holding.purchase_price = round(total_cost / qty, 6) if qty > 0 else 0.0
    holding.purchase_date = first_date


def get_lots(db: Session, holding_id: int, space_id: int):
    holding = get_holding(db, holding_id, space_id)
    if not holding:
        return None
    return sorted(holding.lots, key=lambda l: (l.date, l.id))


def get_lot(db: Session, lot_id: int, holding_id: int, space_id: int):
    holding = get_holding(db, holding_id, space_id)
    if not holding:
        return None
    return db.query(models.HoldingLot).filter(
        models.HoldingLot.id == lot_id, models.HoldingLot.holding_id == holding_id
    ).first()


def create_lot(db: Session, holding_id: int, space_id: int, data: schemas.HoldingLotCreate):
    holding = get_holding(db, holding_id, space_id)
    if not holding:
        return None
    lot = models.HoldingLot(holding_id=holding_id, **data.model_dump())
    db.add(lot)
    db.flush()
    db.refresh(holding)
    recompute_holding_from_lots(db, holding)
    db.commit()
    db.refresh(lot)
    return lot


def update_lot(db: Session, lot_id: int, holding_id: int, space_id: int, data: schemas.HoldingLotUpdate):
    lot = get_lot(db, lot_id, holding_id, space_id)
    if not lot:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(lot, key, value)
    db.flush()
    holding = get_holding(db, holding_id, space_id)
    recompute_holding_from_lots(db, holding)
    db.commit()
    db.refresh(lot)
    return lot


def delete_lot(db: Session, lot_id: int, holding_id: int, space_id: int):
    lot = get_lot(db, lot_id, holding_id, space_id)
    if not lot:
        return None
    db.delete(lot)
    db.flush()
    holding = get_holding(db, holding_id, space_id)
    recompute_holding_from_lots(db, holding)
    db.commit()
    return lot


# ---------- Diversifikation & Risiko ----------
def portfolio_diversification(db: Session, space_id: int) -> schemas.DiversificationOut:
    holdings = get_holdings(db, space_id)
    by_type: dict[str, float] = {}
    by_sector: dict[str, float] = {}
    by_position: dict[str, float] = {}
    by_region: dict[str, float] = {}
    by_currency: dict[str, float] = {}
    total = 0.0
    currency_total = 0.0
    for h in holdings:
        current = h.current_price if h.current_price is not None else h.purchase_price
        value = h.quantity * current
        if value <= 0:
            continue
        total += value
        type_label = h.asset_type.value if hasattr(h.asset_type, "value") else h.asset_type
        by_type[type_label] = by_type.get(type_label, 0.0) + value
        sector_label = h.sector or "Nicht zugeordnet"
        by_sector[sector_label] = by_sector.get(sector_label, 0.0) + value
        by_position[h.name] = by_position.get(h.name, 0.0) + value
        region_label = h.country or "Nicht zugeordnet"
        by_region[region_label] = by_region.get(region_label, 0.0) + value
        # Krypto ist bewusst außen vor - keine "Währung" im klassischen Sinn.
        if type_label != "krypto":
            currency_label = h.currency or "Unbekannt"
            by_currency[currency_label] = by_currency.get(currency_label, 0.0) + value
            currency_total += value

    def slices(d: dict[str, float], basis: float | None = None) -> list[schemas.DiversificationSlice]:
        denom = total if basis is None else basis
        return sorted(
            [
                schemas.DiversificationSlice(
                    label=k, value=round(v, 2), percent=round((v / denom * 100) if denom else 0.0, 1)
                )
                for k, v in d.items()
            ],
            key=lambda s: s.value, reverse=True,
        )

    risk_flags: list[schemas.RiskFlag] = []
    if total > 0:
        for h in holdings:
            current = h.current_price if h.current_price is not None else h.purchase_price
            value = h.quantity * current
            share = value / total * 100
            if share >= 40:
                risk_flags.append(schemas.RiskFlag(
                    level="hoch",
                    message=f"{h.name} macht {share:.0f}% deines Portfolios aus - hohe Klumpenrisiko-Gefahr.",
                ))
        krypto_share = by_type.get("krypto", 0.0) / total * 100
        if krypto_share >= 50:
            risk_flags.append(schemas.RiskFlag(
                level="hoch",
                message=f"{krypto_share:.0f}% deines Portfolios steckt in Krypto - hohe Schwankungsbreite.",
            ))
        if len(holdings) <= 2 and total > 0:
            risk_flags.append(schemas.RiskFlag(
                level="mittel",
                message="Nur wenige Positionen im Portfolio - wenig Streuung.",
            ))

    return schemas.DiversificationOut(
        by_asset_type=slices(by_type),
        by_sector=slices(by_sector),
        by_position=slices(by_position),
        by_region=slices(by_region),
        by_currency=slices(by_currency, basis=currency_total),
        risk_flags=risk_flags,
    )


def compute_volatility(db: Session, asset_type: str, symbol: str) -> float | None:
    """Annualisierte Volatilität (Standardabweichung der täglichen Log-Renditen über
    das letzte Jahr, hochgerechnet auf ein Jahr) in Prozent. None, wenn zu wenig
    Kursdaten vorliegen. Nutzt denselben Tages-Cache wie der 1J-Chart."""
    try:
        points = get_cached_history(db, asset_type, symbol, "1y")
    except Exception:
        return None
    closes = [p[1] for p in points if p[1] > 0]
    if len(closes) < 10:
        return None
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    if len(returns) < 5:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    return round((variance ** 0.5) * (252 ** 0.5) * 100, 1)


def portfolio_volatility(db: Session, space_id: int) -> schemas.VolatilityOut:
    holdings = get_holdings(db, space_id)
    result = []
    for h in holdings:
        asset_type = h.asset_type.value if hasattr(h.asset_type, "value") else h.asset_type
        if asset_type in ("anleihe", "sonstiges"):
            continue
        result.append(schemas.HoldingVolatility(
            holding_id=h.id, name=h.name, volatility_pct=compute_volatility(db, asset_type, h.symbol),
        ))
    return schemas.VolatilityOut(holdings=result)


# ---------- Dividenden ----------
def get_cached_dividends(db: Session, symbol: str) -> list[tuple[str, float]]:
    """Wie get_cached_history, aber für Dividendenzahlungen (eigener Cache-Eintrag
    über asset_type='dividend' als Unterscheidungsmerkmal, einmal täglich aktualisiert)."""
    row = (
        db.query(models.PriceHistoryCache)
        .filter_by(asset_type="dividend", symbol=symbol, range_key="dividends")
        .first()
    )
    if row and (datetime.utcnow() - row.fetched_at) < CACHE_TTL:
        return json.loads(row.data_json)
    try:
        points = prices.fetch_dividends(symbol)
    except Exception:
        if row:
            return json.loads(row.data_json)
        raise
    payload = json.dumps(points)
    if row:
        row.data_json = payload
        row.fetched_at = datetime.utcnow()
    else:
        db.add(models.PriceHistoryCache(
            asset_type="dividend", symbol=symbol, range_key="dividends",
            fetched_at=datetime.utcnow(), data_json=payload,
        ))
    db.commit()
    return points


def holding_dividends(db: Session, holding: models.Holding) -> schemas.HoldingDividendsOut:
    asset_type = holding.asset_type.value if hasattr(holding.asset_type, "value") else holding.asset_type
    history: list[schemas.DividendPayment] = []
    annual_rate_per_share = 0.0
    if asset_type in ("aktie", "etf"):
        try:
            div_points = get_cached_dividends(db, holding.symbol)
        except Exception:
            div_points = []
        lots = sorted(holding.lots, key=lambda l: (l.date, l.id))
        cutoff = date.today() - timedelta(days=365)
        for d, amount_per_share in div_points:
            d_date = date.fromisoformat(d)
            qty, _ = _position_at(lots, d_date)
            if qty <= 0:
                continue
            history.append(schemas.DividendPayment(
                date=d, amount_per_share=amount_per_share, quantity=qty, total=round(qty * amount_per_share, 2),
            ))
            if d_date >= cutoff:
                annual_rate_per_share += amount_per_share

    annual_income = round(annual_rate_per_share * holding.quantity, 2)
    return schemas.HoldingDividendsOut(
        holding_id=holding.id, name=holding.name, symbol=holding.symbol,
        history=history,
        annual_rate_per_share=round(annual_rate_per_share, 4),
        annual_income_estimate=annual_income,
        forecast_1y=annual_income,
        forecast_5y=round(annual_income * 5, 2),
        forecast_10y=round(annual_income * 10, 2),
    )


def portfolio_dividends(db: Session, space_id: int) -> schemas.PortfolioDividendsOut:
    holdings = get_holdings(db, space_id)
    per_holding = [holding_dividends(db, h) for h in holdings]
    per_holding = [h for h in per_holding if h.history or h.annual_rate_per_share]

    by_year: dict[int, float] = {}
    for h in per_holding:
        for payment in h.history:
            year = int(payment.date[:4])
            by_year[year] = round(by_year.get(year, 0.0) + payment.total, 2)

    total_annual = round(sum(h.annual_income_estimate for h in per_holding), 2)
    return schemas.PortfolioDividendsOut(
        total_annual_income_estimate=total_annual,
        forecast_1y=total_annual,
        forecast_5y=round(total_annual * 5, 2),
        forecast_10y=round(total_annual * 10, 2),
        by_year=[schemas.YearlyDividendPoint(year=y, total=v) for y, v in sorted(by_year.items())],
        holdings=per_holding,
    )


def estimate_next_dividends(db: Session, space_id: int) -> list[dict]:
    """Schätzt je Position den nächsten Zahlungstermin aus dem Abstand der
    letzten Zahlungen (z.B. quartalsweise alle ~91 Tage) - Yahoo liefert nur
    VERGANGENE Zahlungstermine, keine offizielle Ankündigung künftiger. Bewusst
    als Schätzung behandelt (im Aufrufer klar so kommuniziert), nicht als
    Zusage - Unternehmen können Termine verschieben oder Dividenden aussetzen,
    anders als eine Bank-Lastschrift also spürbar unsicherer als
    detect_recurring_transactions."""
    results = []
    for h in get_holdings(db, space_id):
        if h.asset_type not in (models.AssetType.aktie, models.AssetType.etf):
            continue
        try:
            div_points = get_cached_dividends(db, h.symbol)
        except Exception:
            continue
        if len(div_points) < 2:
            continue

        dated = sorted((date.fromisoformat(d), amt) for d, amt in div_points)
        dates = [d for d, _ in dated]
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        # nur die juengsten Abstaende - ein Wechsel von jaehrlich auf
        # quartalsweise (oder umgekehrt) soll nicht von alten Abstaenden verwaesert werden.
        recent_gaps = gaps[-4:]
        avg_gap = sum(recent_gaps) / len(recent_gaps)
        if avg_gap < 25:
            continue  # zu unregelmaessig/haeufig fuer eine sinnvolle Schaetzung

        last_date, last_amount_per_share = dated[-1]
        next_estimate = last_date + timedelta(days=round(avg_gap))
        while next_estimate < date.today():
            next_estimate += timedelta(days=round(avg_gap))

        qty, _ = _position_at(sorted(h.lots, key=lambda l: (l.date, l.id)), date.today())
        if qty <= 0:
            continue

        results.append({
            "holding_id": h.id,
            "name": h.name,
            "symbol": h.symbol,
            "estimated_date": next_estimate,
            "estimated_amount": round(qty * last_amount_per_share, 2),
        })

    results.sort(key=lambda r: r["estimated_date"])
    return results


def evaluate_dividend_reminders(db: Session, space_id: int, days_before: int = 7) -> list[dict]:
    """Läuft täglich (siehe main._check_daily_alerts): gibt Positionen zurück,
    deren geschätzter nächster Dividendentermin jetzt in den nächsten
    `days_before` Tagen liegt und für GENAU diesen Termin noch nicht erinnert
    wurde. next_dividend_notified_for verhindert eine tägliche Wiederholung,
    solange derselbe geschätzte Termin bevorsteht - verschiebt sich die
    Schätzung nach der nächsten echten Zahlung, wird wieder frisch erinnert."""
    due = []
    today = date.today()
    for est in estimate_next_dividends(db, space_id):
        holding = db.get(models.Holding, est["holding_id"])
        if not holding:
            continue
        days_left = (est["estimated_date"] - today).days
        if 0 <= days_left <= days_before and holding.next_dividend_notified_for != est["estimated_date"]:
            holding.next_dividend_notified_for = est["estimated_date"]
            due.append(est)
    db.commit()
    return due


# ---------- KI-Assistent: fehlende Belege ----------
def transactions_missing_receipt(db: Session, space_id: int, min_amount: float = 0.0):
    return (
        db.query(models.Transaction)
        .join(models.Account)
        .filter(
            models.Account.space_id == space_id,
            models.Transaction.receipt_filename.is_(None),
            models.Transaction.amount < 0,
            func.abs(models.Transaction.amount) >= min_amount,
        )
        .order_by(models.Transaction.date.desc())
        .all()
    )


# ---------- Kurshistorie & Portfolio-Verlauf ----------
def holding_history(db: Session, holding_id: int, space_id: int, range_key: str) -> schemas.HoldingHistoryOut | None:
    holding = get_holding(db, holding_id, space_id)
    if not holding:
        return None
    asset_type = holding.asset_type.value if hasattr(holding.asset_type, "value") else holding.asset_type
    raw_points = get_cached_history(db, asset_type, holding.symbol, range_key)
    lots = sorted(holding.lots, key=lambda l: (l.date, l.id))
    return schemas.HoldingHistoryOut(
        holding=holding_out(holding),
        points=[schemas.HoldingHistoryPoint(date=d, price=p) for d, p in raw_points],
        lots=[
            schemas.HoldingLotOut(
                id=l.id, date=l.date, type=l.type, quantity=l.quantity,
                price_per_unit=l.price_per_unit, notes=l.notes,
            )
            for l in lots
        ],
    )


def _position_at(lots: list[models.HoldingLot], target_date: date) -> tuple[float, float]:
    """Gehaltene Stückzahl und Einstandswert (Summe der Anschaffungskosten der
    verbliebenen Stückzahl, Durchschnittskostenmethode) zu einem Stichtag."""
    qty, total_cost = 0.0, 0.0
    for lot in lots:
        if lot.date and lot.date <= target_date:
            if lot.type in (models.LotType.kauf, models.LotType.staking):
                qty += lot.quantity
                total_cost += lot.quantity * lot.price_per_unit
            elif lot.type == models.LotType.verkauf and qty > 0:
                avg_cost = total_cost / qty
                sell_qty = min(lot.quantity, qty)
                total_cost -= sell_qty * avg_cost
                qty -= sell_qty
    return max(qty, 0.0), max(total_cost, 0.0)


def portfolio_history(db: Session, space_id: int, range_key: str) -> schemas.PortfolioHistoryOut:
    holdings = get_holdings(db, space_id)
    series_by_holding = {}
    partial = False
    for h in holdings:
        if not h.lots:
            continue
        asset_type = h.asset_type.value if hasattr(h.asset_type, "value") else h.asset_type
        try:
            points = get_cached_history(db, asset_type, h.symbol, range_key)
        except Exception:
            partial = True
            continue
        if not points:
            continue
        series_by_holding[h.id] = {
            "prices_by_date": dict(points),
            "dates": [p[0] for p in points],
            "lots": sorted(h.lots, key=lambda l: (l.date, l.id)),
        }

    if not series_by_holding:
        return schemas.PortfolioHistoryOut(points=[], partial=partial)

    all_dates = sorted({d for s in series_by_holding.values() for d in s["dates"]})
    last_price: dict[int, float | None] = {hid: None for hid in series_by_holding}
    result_points = []
    for d in all_dates:
        d_date = date.fromisoformat(d)
        total_value, total_invested = 0.0, 0.0
        for hid, s in series_by_holding.items():
            if d in s["prices_by_date"]:
                last_price[hid] = s["prices_by_date"][d]
            price = last_price[hid]
            qty, cost = _position_at(s["lots"], d_date)
            total_invested += cost
            if price is not None:
                total_value += qty * price
        return_pct = round((total_value - total_invested) / total_invested * 100, 2) if total_invested else None
        result_points.append(schemas.PortfolioHistoryPoint(
            date=d, value=round(total_value, 2), invested=round(total_invested, 2), return_pct=return_pct,
        ))

    return schemas.PortfolioHistoryOut(points=result_points, partial=partial)


def net_worth(db: Session, space_id: int) -> schemas.NetWorthOut:
    accounts = get_accounts(db, space_id)
    accounts_total = round(sum(account_balance(db, a) for a in accounts), 2)
    holdings = get_holdings(db, space_id)
    investments_total = round(
        sum(h.quantity * (h.current_price if h.current_price is not None else h.purchase_price) for h in holdings),
        2,
    )
    # Offene Restschulden mindern das Vermögen (Nettovermögen). Der Bruttowert
    # bleibt als gross_total erhalten, damit beides im UI sichtbar ist.
    debts_total = round(sum(max(0.0, d.current_balance) for d in get_debts(db, space_id)), 2)
    gross_total = round(accounts_total + investments_total, 2)
    return schemas.NetWorthOut(
        accounts_total=accounts_total,
        investments_total=investments_total,
        debts_total=debts_total,
        gross_total=gross_total,
        total=round(gross_total - debts_total, 2),
    )


def build_digest(
    db: Session, space_id: int,
    home_coords: tuple[float, float] | None = None, ors_api_key: str | None = None,
    since: datetime | None = None, transfers_marked: int = 0,
) -> str:
    """Baut die Telegram-Statusmeldung fuer den wiederkehrenden Digest (siehe
    main._scheduled_digest) - bewusst reine Auswertung, veraendert nirgends
    einen "notified"/"reminded"-Zustand wie die evaluate_*-Funktionen, damit
    sich Digest und die separaten Sofort-Warnungen nicht gegenseitig
    beeinflussen. Das Entschlüsseln von ors_api_key passiert bewusst schon in
    main.py (kein bank_sync-Import hier, sonst zirkulärer Import mit crud)."""
    nw = net_worth(db, space_id)
    lines = [f"📊 Kies-Update ({datetime.now().strftime('%H:%M')})", ""]
    verlauf = ""
    # Vergleich zur vorherigen DIGEST-NACHRICHT (Space.last_digest_net_worth),
    # nicht zum taeglichen NetWorthSnapshot - der Digest laeuft mehrmals
    # taeglich (siehe main.DIGEST_HOURS), ein Tages-Snapshot waere fuer
    # "seit der letzten Meldung" zu grob. main._scheduled_digest schreibt
    # last_digest_net_worth erst NACH erfolgreichem Versand fort.
    space = db.query(models.Space).filter(models.Space.id == space_id).first()
    if space and space.last_digest_net_worth is not None:
        delta = round(nw.total - space.last_digest_net_worth, 2)
        if delta:
            pfeil = "📈" if delta > 0 else "📉"
            verlauf = f" ({pfeil} {delta:+.2f} EUR zur letzten Nachricht)"
    lines.append(f"Nettovermögen: {nw.total:.2f} EUR{verlauf}")
    lines.append(
        f"Konten: {nw.accounts_total:.2f} EUR · Investments: {nw.investments_total:.2f} EUR · "
        f"Schulden: {nw.debts_total:.2f} EUR"
    )

    negative = [a for a in get_accounts(db, space_id) if account_balance(db, a) < 0]
    if negative:
        namen = ", ".join(f"„{a.name}“" for a in negative)
        lines.append(f"\n⚠️ Im Minus: {namen}")

    if since:
        neu_kategorisiert = (
            db.query(models.Transaction)
            .join(models.Account)
            .filter(models.Account.space_id == space_id, models.Transaction.categorized_at > since)
            .count()
        )
        if neu_kategorisiert:
            lines.append(f"\n✅ {neu_kategorisiert} Buchung(en) seit dem letzten Update automatisch kategorisiert.")
        if transfers_marked:
            lines.append(f"🔁 {transfers_marked} interne Umbuchung(en) erkannt und markiert.")

    forecast = cashflow_forecast(db, space_id, horizon_days=7)
    upcoming = forecast.upcoming_events[:5]
    if upcoming:
        lines.append("\n📅 Fällig in den nächsten 7 Tagen:")
        for e in upcoming:
            lines.append(f"- {e.date.strftime('%d.%m.')}: {e.description or '–'} ({e.amount:.2f} EUR)")

    events = get_upcoming_calendar_events(db, days=3)
    if events:
        lines.append("\n🗓 Termine (nächste 3 Tage):")
        for ev in events[:5]:
            zeit = "ganztägig" if ev.all_day else ev.start.strftime("%d.%m. %H:%M")
            ort = f" @ {ev.location}" if ev.location else ""
            fahrzeit = ""
            # Nur fuer Termine der naechsten 24h berechnen (sonst taeglich
            # wiederholte Anfragen fuer laengst noch nicht relevante Termine)
            # und nur mit Ort+Koordinaten+eingerichteter Anbindung.
            if (
                home_coords and ors_api_key and not ev.all_day and ev.lat and ev.lon
                and ev.start <= datetime.utcnow() + timedelta(hours=24)
            ):
                try:
                    minuten = travel_time.travel_time_minutes(ors_api_key, home_coords, (ev.lat, ev.lon))
                except Exception:
                    minuten = None
                if minuten is not None:
                    fahrzeit = f" · 🚗 ~{minuten} Min ab Zuhause"
            lines.append(f"- {zeit}: {ev.title}{ort}{fahrzeit}")

    # Lokaler Import statt am Modulanfang - goals.py importiert seinerseits
    # crud, ein Import ganz oben wuerde einen Zirkelbezug erzeugen.
    from . import goals as goals_module
    open_goals = [g for g in get_goals(db, space_id) if g.status == models.GoalStatus.open and g.trigger]
    nah_dran = []
    for g in open_goals:
        result = goals_module.evaluate_metric(db, g)
        if result.value is None:
            continue
        percent = goals_module.progress_percent(result.value, result.threshold, result.comparison)
        if percent >= 80:
            nah_dran.append((g, percent))
    if nah_dran:
        nah_dran.sort(key=lambda x: -x[1])
        lines.append("\n🎯 Fast geschafft:")
        for g, percent in nah_dran[:3]:
            lines.append(f"- „{g.title}“: {percent:.0f}%")

    offen = (
        db.query(models.Transaction)
        .join(models.Account)
        .filter(models.Account.space_id == space_id, models.Transaction.category_id.is_(None),
                models.Transaction.is_transfer.is_(False))
        .count()
    )
    if offen:
        lines.append(f"\n🗂 {offen} Buchung(en) noch unkategorisiert - läuft automatisch weiter im Hintergrund.")

    dupes = find_duplicate_transactions(db, space_id)
    if dupes:
        lines.append(f"\n🔁 {len(dupes)} mögliche doppelte Buchung(en) gefunden - im Buchungen-Tab prüfbar.")

    return "\n".join(lines)


def record_net_worth_snapshot(db: Session, space_id: int) -> None:
    """Schreibt einen Nettovermoegen-Snapshot fuer heute, falls noch keiner
    existiert - idempotent, damit ein Neustart des Schedulers am selben Tag
    keinen doppelten Eintrag erzeugt (siehe UniqueConstraint am Modell)."""
    today = date.today()
    existing = (
        db.query(models.NetWorthSnapshot)
        .filter(models.NetWorthSnapshot.space_id == space_id, models.NetWorthSnapshot.date == today)
        .first()
    )
    if existing:
        return
    nw = net_worth(db, space_id)
    db.add(models.NetWorthSnapshot(
        space_id=space_id, date=today,
        accounts_total=nw.accounts_total, investments_total=nw.investments_total,
        debts_total=nw.debts_total, total=nw.total,
    ))
    db.commit()


def net_worth_history(db: Session, space_id: int, days: int = 365) -> list[models.NetWorthSnapshot]:
    start = date.today() - timedelta(days=days)
    return (
        db.query(models.NetWorthSnapshot)
        .filter(models.NetWorthSnapshot.space_id == space_id, models.NetWorthSnapshot.date >= start)
        .order_by(models.NetWorthSnapshot.date)
        .all()
    )


# ---------- Schulden ----------
def get_debts(db: Session, space_id: int):
    return (
        db.query(models.Debt)
        .filter(models.Debt.space_id == space_id)
        .order_by(models.Debt.status, models.Debt.name)
        .all()
    )


def get_debt(db: Session, debt_id: int, space_id: int):
    return (
        db.query(models.Debt)
        .filter(models.Debt.id == debt_id, models.Debt.space_id == space_id)
        .first()
    )


def recompute_debt_from_payments(db: Session, debt: models.Debt):
    """Leitet Restschuld und Status aus dem Zahlungs-Ledger ab - analog zu
    recompute_holding_from_lots. Muss nach jeder Änderung an Zahlungen oder an
    Betrag/Zinssatz des Kredits laufen."""
    debt.current_balance = debts.current_balance(debt)
    debt.status = models.DebtStatus.paid_off if debt.current_balance <= 0 else models.DebtStatus.active
    db.commit()
    db.refresh(debt)
    return debt


def create_debt(db: Session, data: schemas.DebtCreate, space_id: int):
    db_debt = models.Debt(**data.model_dump(), space_id=space_id, current_balance=data.original_amount)
    db.add(db_debt)
    db.commit()
    db.refresh(db_debt)
    return db_debt


def update_debt(db: Session, debt_id: int, space_id: int, data: schemas.DebtUpdate):
    db_debt = get_debt(db, debt_id, space_id)
    if not db_debt:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(db_debt, key, value)
    db.commit()
    # Betrag/Zinssatz beeinflussen die Aufteilung aller Zahlungen.
    return recompute_debt_from_payments(db, db_debt)


def delete_debt(db: Session, debt_id: int, space_id: int):
    db_debt = get_debt(db, debt_id, space_id)
    if db_debt:
        db.delete(db_debt)
        db.commit()
    return db_debt


def get_debt_payment(db: Session, payment_id: int, debt_id: int, space_id: int):
    if not get_debt(db, debt_id, space_id):
        return None
    return (
        db.query(models.DebtPayment)
        .filter(models.DebtPayment.id == payment_id, models.DebtPayment.debt_id == debt_id)
        .first()
    )


def create_debt_payment(db: Session, debt_id: int, space_id: int, data: schemas.DebtPaymentCreate):
    debt = get_debt(db, debt_id, space_id)
    if not debt:
        return None
    payment = models.DebtPayment(debt_id=debt_id, **data.model_dump())
    db.add(payment)
    db.commit()
    recompute_debt_from_payments(db, debt)
    db.refresh(payment)
    return payment


def update_debt_payment(db: Session, payment_id: int, debt_id: int, space_id: int, data: schemas.DebtPaymentUpdate):
    payment = get_debt_payment(db, payment_id, debt_id, space_id)
    if not payment:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(payment, key, value)
    db.commit()
    recompute_debt_from_payments(db, get_debt(db, debt_id, space_id))
    db.refresh(payment)
    return payment


def delete_debt_payment(db: Session, payment_id: int, debt_id: int, space_id: int):
    payment = get_debt_payment(db, payment_id, debt_id, space_id)
    if payment:
        db.delete(payment)
        db.commit()
        recompute_debt_from_payments(db, get_debt(db, debt_id, space_id))
    return payment


def debt_summary(db: Session, space_id: int) -> schemas.DebtSummaryOut:
    all_debts = get_debts(db, space_id)
    active = [d for d in all_debts if d.status == models.DebtStatus.active]
    return schemas.DebtSummaryOut(
        total_balance=round(sum(max(0.0, d.current_balance) for d in all_debts), 2),
        total_original=round(sum(d.original_amount for d in all_debts), 2),
        total_interest_paid=round(sum(debts.total_interest_paid(d) for d in all_debts), 2),
        total_fees_paid=round(sum(debts.total_fees_paid(d) for d in all_debts), 2),
        # Tatsächliche Belastung: Rate plus laufende Nebenkosten
        monthly_burden=round(sum((d.monthly_payment or 0.0) + debts.monthly_side_costs(d) for d in active), 2),
        active_count=len(active),
        paid_off_count=len(all_debts) - len(active),
    )


# ---------- Bank-Verbindungen (FinTS) ----------
def get_bank_connections(db: Session, space_id: int):
    return db.query(models.BankConnection).filter(models.BankConnection.space_id == space_id).all()


def get_bank_connection(db: Session, connection_id: int, space_id: int):
    return (
        db.query(models.BankConnection)
        .filter(models.BankConnection.id == connection_id, models.BankConnection.space_id == space_id)
        .first()
    )


def get_all_bank_connections(db: Session):
    return db.query(models.BankConnection).all()


def create_bank_connection(db: Session, space_id: int, name: str, blz: str, fints_url: str, login: str, pin_encrypted: str, account_id: int, iban: str):
    conn = models.BankConnection(
        space_id=space_id, name=name, blz=blz, fints_url=fints_url, login=login,
        pin_encrypted=pin_encrypted, account_id=account_id, iban=iban,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def delete_bank_connection(db: Session, connection_id: int, space_id: int):
    conn = get_bank_connection(db, connection_id, space_id)
    if conn:
        db.delete(conn)
        db.commit()
    return conn


# ---------- Bitvavo-Verbindungen ----------
def get_bitvavo_connections(db: Session, space_id: int):
    return db.query(models.BitvavoConnection).filter(models.BitvavoConnection.space_id == space_id).all()


def get_bitvavo_connection(db: Session, connection_id: int, space_id: int):
    return (
        db.query(models.BitvavoConnection)
        .filter(models.BitvavoConnection.id == connection_id, models.BitvavoConnection.space_id == space_id)
        .first()
    )


def get_all_bitvavo_connections(db: Session):
    return db.query(models.BitvavoConnection).all()


def create_bitvavo_connection(db: Session, space_id: int, name: str, api_key_encrypted: str, api_secret_encrypted: str):
    conn = models.BitvavoConnection(
        space_id=space_id, name=name,
        api_key_encrypted=api_key_encrypted, api_secret_encrypted=api_secret_encrypted,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def delete_bitvavo_connection(db: Session, connection_id: int, space_id: int):
    conn = get_bitvavo_connection(db, connection_id, space_id)
    if conn:
        db.delete(conn)
        db.commit()
    return conn


# ---------- PayPal-Verbindungen ----------
def get_paypal_connections(db: Session, space_id: int):
    return db.query(models.PayPalConnection).filter(models.PayPalConnection.space_id == space_id).all()


def get_paypal_connection(db: Session, connection_id: int, space_id: int):
    return (
        db.query(models.PayPalConnection)
        .filter(models.PayPalConnection.id == connection_id, models.PayPalConnection.space_id == space_id)
        .first()
    )


def get_all_paypal_connections(db: Session):
    return db.query(models.PayPalConnection).all()


def create_paypal_connection(db: Session, space_id: int, account_id: int, name: str, client_id_encrypted: str, client_secret_encrypted: str):
    conn = models.PayPalConnection(
        space_id=space_id, account_id=account_id, name=name,
        client_id_encrypted=client_id_encrypted, client_secret_encrypted=client_secret_encrypted,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def delete_paypal_connection(db: Session, connection_id: int, space_id: int):
    conn = get_paypal_connection(db, connection_id, space_id)
    if conn:
        db.delete(conn)
        db.commit()
    return conn


# ---------- Enable-Banking-Verbindungen ----------
def get_enablebanking_connections(db: Session, space_id: int):
    return db.query(models.EnableBankingConnection).filter(models.EnableBankingConnection.space_id == space_id).all()


def get_enablebanking_connection(db: Session, connection_id: int, space_id: int):
    return (
        db.query(models.EnableBankingConnection)
        .filter(models.EnableBankingConnection.id == connection_id, models.EnableBankingConnection.space_id == space_id)
        .first()
    )


def get_enablebanking_connection_by_state(db: Session, state: str):
    return db.query(models.EnableBankingConnection).filter(models.EnableBankingConnection.state == state).first()


def get_all_enablebanking_connections(db: Session):
    return db.query(models.EnableBankingConnection).all()


def create_enablebanking_connection(db: Session, space_id: int, account_id: int, aspsp_name: str, aspsp_country: str, state: str):
    conn = models.EnableBankingConnection(
        space_id=space_id, account_id=account_id,
        aspsp_name=aspsp_name, aspsp_country=aspsp_country, state=state,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def delete_enablebanking_connection(db: Session, connection_id: int, space_id: int):
    conn = get_enablebanking_connection(db, connection_id, space_id)
    if conn:
        db.delete(conn)
        db.commit()
    return conn


# ---------- To-Dos ----------
def get_todos(db: Session, include_done: bool = True):
    q = db.query(models.Todo).filter(models.Todo.pending_delete.is_(False))
    if not include_done:
        q = q.filter(models.Todo.done.is_(False))
    return q.order_by(models.Todo.done, models.Todo.due_date.is_(None), models.Todo.due_date, models.Todo.created_at).all()


def get_todo(db: Session, todo_id: int):
    return db.query(models.Todo).filter(models.Todo.id == todo_id, models.Todo.pending_delete.is_(False)).first()


def create_todo(db: Session, title: str, due_date=None):
    todo = models.Todo(uid=radicale_sync.new_uid(), title=title, due_date=due_date)
    db.add(todo)
    db.commit()
    db.refresh(todo)
    return todo


def update_todo(db: Session, todo: models.Todo, title=None, done=None, due_date=None):
    if title is not None:
        todo.title = title
    if done is not None and done != todo.done:
        todo.done = done
        # Zeitpunkt des Abhakens merken (bzw. beim Zurücknehmen wieder
        # löschen) - Grundlage für die automatische Aufräumung nach 2 Tagen.
        todo.completed_at = datetime.utcnow() if done else None
    if due_date is not None:
        todo.due_date = due_date
    db.commit()
    db.refresh(todo)
    return todo


def complete_todo_by_name(db: Session, name_query: str):
    """Hakt ein offenes To-Do über einen (Teil-)Namen ab - fürs Telegram-
    Kommando /erledigt, analog zu set_balance_by_name. Gibt (todo, error)
    zurück: error ist None bei Erfolg, sonst ein Text zum direkten
    Zurücksenden (kein Treffer / mehrdeutig)."""
    open_todos = get_todos(db, include_done=False)
    q = name_query.strip().lower()
    if not q:
        # Ein leerer Suchbegriff waere Teilstring von jedem Titel und wuerde
        # sonst bei genau einem offenen To-Do dieses ohne echten Treffer
        # abhaken - lieber explizit "kein Treffer" als das.
        return None, "Kein Suchbegriff angegeben."
    matches = [t for t in open_todos if q in t.title.lower()]
    if not matches:
        namen = ", ".join(t.title for t in open_todos) or "keine offenen To-Dos"
        return None, f"Nichts mit „{name_query}“ gefunden. Offen: {namen}"
    if len(matches) > 1:
        namen = ", ".join(t.title for t in matches)
        return None, f"„{name_query}“ ist nicht eindeutig, passt auf: {namen}. Bitte genauer benennen."
    todo = update_todo(db, matches[0], done=True)
    return todo, None


def cleanup_old_done_todos(db: Session, days: int = 2) -> int:
    """Erledigte To-Dos verschwinden 2 Tage, nachdem sie abgehakt wurden, von
    selbst - abgehakt heißt hier "erledigt, kann weg", nicht "soll dauerhaft
    als Liste stehen bleiben". Löschung läuft über denselben pending_delete-
    Weg wie eine manuelle Löschung, damit sie beim nächsten Sync auch auf dem
    Radicale-Server verschwindet."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    old = (
        db.query(models.Todo)
        .filter(models.Todo.done.is_(True), models.Todo.completed_at.isnot(None),
                models.Todo.completed_at < cutoff, models.Todo.pending_delete.is_(False))
        .all()
    )
    for todo in old:
        todo.pending_delete = True
    if old:
        db.commit()
    return len(old)


def get_upcoming_calendar_events(db: Session, days: int = 7, limit: int = 20) -> list[models.CalendarEvent]:
    now = datetime.utcnow()
    cutoff = now + timedelta(days=days)
    return (
        db.query(models.CalendarEvent)
        .filter(models.CalendarEvent.start >= now, models.CalendarEvent.start <= cutoff)
        .order_by(models.CalendarEvent.start)
        .limit(limit)
        .all()
    )


def detect_calendar_conflicts(db: Session, days: int = 14) -> list[dict]:
    """Findet sich zeitlich überschneidende Termine in den nächsten `days`
    Tagen - reine Auswertung der ohnehin geladenen Termine, kein Ändern.
    Ganztägige Termine werden bewusst ausgeklammert (die überschneiden sich
    fast immer mit irgendwas, ohne dass das ein echtes Problem wäre). Termine
    ohne Ende gelten für den Vergleich als 30 Minuten lang - eine Annahme nur
    für diese Prüfung, nicht gespeichert."""
    now = datetime.utcnow()
    cutoff = now + timedelta(days=days)
    events = (
        db.query(models.CalendarEvent)
        .filter(
            models.CalendarEvent.pending_delete.is_(False),
            models.CalendarEvent.all_day.is_(False),
            models.CalendarEvent.start >= now,
            models.CalendarEvent.start <= cutoff,
        )
        .order_by(models.CalendarEvent.start)
        .all()
    )

    def effective_end(ev):
        return ev.end or (ev.start + timedelta(minutes=30))

    conflicts = []
    for i in range(len(events)):
        a = events[i]
        a_end = effective_end(a)
        for j in range(i + 1, len(events)):
            b = events[j]
            if b.start >= a_end:
                break  # nach Start sortiert - ab hier kann nichts mehr ueberlappen
            conflicts.append({
                "event_a_id": a.id, "event_a_title": a.title, "event_a_start": a.start,
                "event_b_id": b.id, "event_b_title": b.title, "event_b_start": b.start,
            })
    return conflicts


def delete_todo(db: Session, todo: models.Todo):
    # Erst zum Löschen markieren, damit der nächste Sync die Löschung noch auf
    # den Server übertragen kann - direktes db.delete() würde die Radicale-
    # Ressource verwaist zurücklassen.
    todo.pending_delete = True
    db.commit()


def get_calendar_events(db: Session, start: datetime, end: datetime) -> list[models.CalendarEvent]:
    return (
        db.query(models.CalendarEvent)
        .filter(
            models.CalendarEvent.pending_delete.is_(False),
            models.CalendarEvent.start >= start,
            models.CalendarEvent.start <= end,
        )
        .order_by(models.CalendarEvent.start)
        .all()
    )


def get_calendar_event(db: Session, event_id: int):
    return (
        db.query(models.CalendarEvent)
        .filter(models.CalendarEvent.id == event_id, models.CalendarEvent.pending_delete.is_(False))
        .first()
    )


def create_calendar_event(db: Session, title, start, end, location, all_day, calendar_url):
    event = models.CalendarEvent(
        uid=radicale_sync.new_uid(), title=title, start=start, end=end,
        location=location, all_day=all_day, calendar_url=calendar_url,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def update_calendar_event(db: Session, event: models.CalendarEvent, title=None, start=None, end=None, location=None, all_day=None):
    if title is not None:
        event.title = title
    if start is not None:
        event.start = start
    if end is not None:
        event.end = end
    if location is not None:
        event.location = location or None
    if all_day is not None:
        event.all_day = all_day
    event.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(event)
    return event


def cancel_calendar_event_by_name(db: Session, name_query: str):
    """Sagt einen zukünftigen Termin über einen (Teil-)Namen ab - fürs
    Telegram-Kommando /termin_absagen, analog zu set_balance_by_name/
    complete_todo_by_name. Gibt (event, error) zurück: error ist None bei
    Erfolg, sonst ein Text zum direkten Zurücksenden (kein Treffer /
    mehrdeutig)."""
    upcoming = get_upcoming_calendar_events(db, days=365, limit=1000)
    q = name_query.strip().lower()
    if not q:
        # Siehe complete_todo_by_name: ein leerer Suchbegriff waere sonst
        # Teilstring von jedem Titel und wuerde bei genau einem anstehenden
        # Termin diesen ohne echten Treffer absagen.
        return None, "Kein Suchbegriff angegeben."
    matches = [e for e in upcoming if q in e.title.lower()]
    if not matches:
        namen = ", ".join(e.title for e in upcoming[:10]) or "keine anstehenden Termine"
        return None, f"Nichts mit „{name_query}“ gefunden. Anstehend: {namen}"
    if len(matches) > 1:
        namen = ", ".join(e.title for e in matches)
        return None, f"„{name_query}“ ist nicht eindeutig, passt auf: {namen}. Bitte genauer benennen."
    event = matches[0]
    delete_calendar_event(db, event)
    return event, None


def delete_calendar_event(db: Session, event: models.CalendarEvent):
    # Wie bei Todo: erst markieren, damit der nächste Sync die Löschung noch
    # auf den Server überträgt, statt die Radicale-Ressource verwaist zurück-
    # zulassen. Ein Termin ohne calendar_url (nie synchronisiert) kann direkt
    # gelöscht werden.
    if event.calendar_url and event.href:
        event.pending_delete = True
        db.commit()
    else:
        db.delete(event)
        db.commit()


# ---------- eBay-Verbindungen ----------
def get_ebay_connections(db: Session, space_id: int):
    return db.query(models.EbayConnection).filter(models.EbayConnection.space_id == space_id).all()


def get_ebay_connection(db: Session, connection_id: int, space_id: int):
    return (
        db.query(models.EbayConnection)
        .filter(models.EbayConnection.id == connection_id, models.EbayConnection.space_id == space_id)
        .first()
    )


def get_ebay_connection_by_state(db: Session, state: str):
    return db.query(models.EbayConnection).filter(models.EbayConnection.state == state).first()


def get_all_ebay_connections(db: Session):
    return db.query(models.EbayConnection).all()


def create_ebay_connection(db: Session, space_id: int, account_id: int, state: str):
    conn = models.EbayConnection(space_id=space_id, account_id=account_id, state=state)
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def delete_ebay_connection(db: Session, connection_id: int, space_id: int):
    conn = get_ebay_connection(db, connection_id, space_id)
    if conn:
        db.delete(conn)
        db.commit()
    return conn


# ---------- Ziele ----------
def _goal_visible_filter(space_id: int):
    """Ziele des aktiven Bereichs plus bereichsübergreifende (space_id NULL)."""
    return (models.Goal.space_id == space_id) | (models.Goal.space_id.is_(None))


def get_goals(db: Session, space_id: int):
    return (
        db.query(models.Goal)
        .filter(_goal_visible_filter(space_id))
        .order_by(models.Goal.status, models.Goal.target_date.is_(None), models.Goal.target_date, models.Goal.id)
        .all()
    )


def get_goal(db: Session, goal_id: int, space_id: int):
    return (
        db.query(models.Goal)
        .filter(models.Goal.id == goal_id, _goal_visible_filter(space_id))
        .first()
    )


def get_open_auto_goals(db: Session):
    """Für den täglichen Auswertungsjob - bereichsunabhängig, da er global läuft."""
    return (
        db.query(models.Goal)
        .filter(
            models.Goal.status == models.GoalStatus.open,
            models.Goal.goal_type == models.GoalType.auto_financial,
        )
        .all()
    )


def _apply_trigger(db: Session, goal: models.Goal, data: schemas.GoalTriggerIn | None):
    """Legt die 1:1-Auswertungsregel an bzw. aktualisiert sie. Bei manuellen Zielen
    wird eine evtl. vorhandene Regel entfernt, damit kein Karteileichen-Trigger bleibt."""
    if goal.goal_type != models.GoalType.auto_financial or data is None:
        if goal.trigger:
            db.delete(goal.trigger)
            goal.trigger = None
        return
    trigger = goal.trigger or models.GoalTrigger(goal_id=goal.id)
    trigger.metric_type = data.metric_type
    trigger.comparison = data.comparison
    trigger.threshold_value = data.threshold_value
    trigger.scope_account_id = data.scope_account_id
    trigger.scope_asset_type = data.scope_asset_type
    trigger.scope_category_id = data.scope_category_id
    trigger.scope_debt_id = data.scope_debt_id
    trigger.evaluation_window_months = data.evaluation_window_months
    if goal.trigger is None:
        db.add(trigger)
        goal.trigger = trigger


def create_goal(db: Session, data: schemas.GoalCreate, space_id: int):
    goal = models.Goal(
        space_id=None if data.all_spaces else space_id,
        title=data.title,
        description=data.description,
        category=data.category,
        goal_type=data.goal_type,
        target_date=data.target_date,
        predecessor_goal_id=data.predecessor_goal_id,
        status=models.GoalStatus.open,
    )
    db.add(goal)
    db.flush()  # goal.id für den Trigger
    _apply_trigger(db, goal, data.trigger)
    db.commit()
    db.refresh(goal)
    return goal


def update_goal(db: Session, goal_id: int, space_id: int, data: schemas.GoalUpdate):
    goal = get_goal(db, goal_id, space_id)
    if not goal:
        return None
    fields = data.model_dump(exclude_unset=True, exclude={"trigger", "all_spaces"})
    for key, value in fields.items():
        setattr(goal, key, value)
    if data.all_spaces is not None:
        goal.space_id = None if data.all_spaces else space_id
    if "status" in fields:
        if goal.status == models.GoalStatus.completed and goal.completed_at is None:
            goal.completed_at = datetime.utcnow()
        elif goal.status == models.GoalStatus.open:
            goal.completed_at = None
            goal.completion_seen = True
    if data.trigger is not None or (data.goal_type is not None and data.goal_type != models.GoalType.auto_financial):
        _apply_trigger(db, goal, data.trigger)
    db.commit()
    db.refresh(goal)
    return goal


def delete_goal(db: Session, goal_id: int, space_id: int):
    goal = get_goal(db, goal_id, space_id)
    if goal:
        db.delete(goal)
        db.commit()
    return goal


def set_goal_completed(db: Session, goal: models.Goal, completed: bool):
    """Manuelles Abhaken bzw. Zurücksetzen. `completion_seen` bleibt True, weil der
    Nutzer die Änderung ja selbst ausgelöst hat - die Badge ist nur für automatische
    Abschlüsse gedacht."""
    if completed:
        goal.status = models.GoalStatus.completed
        goal.completed_at = datetime.utcnow()
    else:
        goal.status = models.GoalStatus.open
        goal.completed_at = None
    goal.completion_seen = True
    db.commit()
    db.refresh(goal)
    return goal


def mark_goals_seen(db: Session, space_id: int) -> int:
    goals = (
        db.query(models.Goal)
        .filter(_goal_visible_filter(space_id), models.Goal.completion_seen.is_(False))
        .all()
    )
    for g in goals:
        g.completion_seen = True
    db.commit()
    return len(goals)


def get_goal_progress_points(db: Session, goal_id: int):
    return (
        db.query(models.GoalProgress)
        .filter(models.GoalProgress.goal_id == goal_id)
        .order_by(models.GoalProgress.timestamp)
        .all()
    )


# ---------- Dashboard ----------
def dashboard_summary(db: Session, space_id: int, year: int, month: int | None = None, business_only: bool = False):
    """`business_only` treibt den Geschäftlich-Tab: identische Auswertung, nur auf
    Konten mit is_business=True eingeschränkt - Geschäftliches ist bei einem
    Einzelunternehmer kein eigener Bereich, sondern nur ein Filter."""
    query = (
        db.query(models.Transaction)
        .join(models.Account)
        .filter(
            models.Account.space_id == space_id,
            extract("year", models.Transaction.date) == year,
            models.Transaction.is_transfer.is_(False),
        )
    )
    if business_only:
        query = query.filter(models.Account.is_business.is_(True))
    if month:
        query = query.filter(extract("month", models.Transaction.date) == month)
    transactions = query.all()

    total_income = round(sum(t.amount for t in transactions if t.amount > 0), 2)
    total_expense = round(sum(t.amount for t in transactions if t.amount < 0), 2)

    by_cat: dict[int | None, float] = {}
    cat_names: dict[int | None, str] = {}
    for t in transactions:
        if t.amount >= 0:
            continue  # Dashboard-Kategorien nur für Ausgaben
        key = t.category_id
        by_cat[key] = by_cat.get(key, 0.0) + t.amount
        if key is None:
            cat_names[key] = "Ohne Kategorie"
        elif key not in cat_names:
            cat = get_category(db, key)
            cat_names[key] = cat.name if cat else "Unbekannt"

    by_category = [
        schemas.CategorySummary(
            category_id=k, category_name=cat_names[k], total=round(v, 2)
        )
        for k, v in sorted(by_cat.items(), key=lambda x: x[1])
    ]

    accounts = get_accounts(db, space_id)
    if business_only:
        accounts = [a for a in accounts if a.is_business]
    account_balances = []
    for acc in accounts:
        bal = account_balance(db, acc)
        account_balances.append(
            schemas.AccountOut(
                id=acc.id,
                name=acc.name,
                type=acc.type,
                initial_balance=acc.initial_balance,
                is_business=acc.is_business,
                created_at=acc.created_at,
                current_balance=bal,
            )
        )

    return schemas.DashboardSummary(
        year=year,
        month=month,
        total_income=total_income,
        total_expense=total_expense,
        balance=round(total_income + total_expense, 2),
        by_category=by_category,
        account_balances=account_balances,
        # Budgets sind kategoriebasiert und nicht nach Konto trennbar - im
        # Geschäftlich-Filter bewusst leer statt einer irreführenden Mischung.
        budgets=[] if business_only else budget_progress(db, space_id, year, month),
    )


# Eigener Name, wie er bei internen Umbuchungen als Empfaenger/Sender auftaucht
# (Kies ist Single-User) - siehe Ausschluss in top_expense_recipients.
OWN_NAME_PATTERN = "tim stubbe"


def top_expense_recipients(db: Session, space_id: int, year: int, month: int | None = None, limit: int = 10) -> list[dict]:
    """Wo das Geld tatsaechlich hingeht, konkret statt nur nach Kategorie -
    "Rewe: 450 EUR" ist oft aussagekraeftiger als "Lebensmittel: 1200 EUR" ueber
    fuenf verschiedene Laeden verteilt. Gruppiert nach derselben normalisierten
    Beschreibung wie die Abo-Erkennung (_normalize_description), damit
    "REWE SAGT DANKE 12345" und "Rewe Sagt Danke 67890" zusammenfallen."""
    query = (
        db.query(models.Transaction)
        .join(models.Account)
        .filter(
            models.Account.space_id == space_id,
            extract("year", models.Transaction.date) == year,
            models.Transaction.is_transfer.is_(False),
            models.Transaction.amount < 0,
        )
    )
    if month:
        query = query.filter(extract("month", models.Transaction.date) == month)

    groups: dict[str, dict] = {}
    for t in query.all():
        key = _normalize_description(t.description) or "(ohne Beschreibung)"
        # Interne Umbuchungen zwischen eigenen Konten tauchen als eigener Name
        # auf (z.B. "Tim Stubbe" als Empfaenger), auch wenn is_transfer aus
        # anderen Gruenden nicht gesetzt ist (z.B. schon kategorisiert, bevor
        # die Umbuchungs-Erkennung lief) - fuer "wo geht mein Geld hin" ist das
        # kein echter Ausgabe-Empfaenger und stoert nur.
        if OWN_NAME_PATTERN and OWN_NAME_PATTERN in key:
            continue
        g = groups.setdefault(key, {"label": t.description or "Ohne Beschreibung", "total": 0.0, "count": 0})
        g["total"] += t.amount
        g["count"] += 1

    results = [
        {"description": g["label"], "total": round(abs(g["total"]), 2), "count": g["count"]}
        for g in groups.values()
    ]
    results.sort(key=lambda r: -r["total"])
    return results[:limit]


def monthly_flow_trend(db: Session, space_id: int, months: int = 6) -> list[dict]:
    """Einnahmen/Ausgaben je Monat der letzten `months` Monate (aktueller Monat
    eingeschlossen) - fuer kleine Trend-Sparklines auf dem Hub, keine
    tiefergehende Auswertung wie dashboard_summary."""
    today = date.today()
    start_year, start_month = today.year, today.month - (months - 1)
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    start = date(start_year, start_month, 1)

    rows = (
        db.query(models.Transaction)
        .join(models.Account)
        .filter(
            models.Account.space_id == space_id,
            models.Transaction.date >= start,
            models.Transaction.is_transfer.is_(False),
        )
        .all()
    )

    buckets: dict[tuple[int, int], dict[str, float]] = {}
    y, m = start_year, start_month
    for _ in range(months):
        buckets[(y, m)] = {"income": 0.0, "expense": 0.0}
        m += 1
        if m > 12:
            m, y = 1, y + 1
    for t in rows:
        key = (t.date.year, t.date.month)
        bucket = buckets.get(key)
        if not bucket:
            continue
        if t.amount > 0:
            bucket["income"] += t.amount
        else:
            bucket["expense"] += t.amount

    return [
        {"year": y, "month": m, "income": round(v["income"], 2), "expense": round(v["expense"], 2)}
        for (y, m), v in sorted(buckets.items())
    ]


def category_spending_trend(db: Session, space_id: int, months: int = 6) -> dict:
    """Ausgaben je Kategorie und Monat der letzten `months` Monate (aktueller
    Monat eingeschlossen) - fürs Trend-Chart im Kategorien-Tab, eine Linie
    pro Kategorie. Nur Ausgaben (analog zu dashboard_summary), Kategorien
    ohne Buchung in diesem Zeitraum tauchen gar nicht erst auf."""
    today = date.today()
    start_year, start_month = today.year, today.month - (months - 1)
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    start = date(start_year, start_month, 1)

    month_keys = []
    y, m = start_year, start_month
    for _ in range(months):
        month_keys.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1

    txs = (
        db.query(models.Transaction)
        .join(models.Account)
        .filter(
            models.Account.space_id == space_id,
            models.Transaction.date >= start,
            models.Transaction.amount < 0,
            models.Transaction.is_transfer.is_(False),
        )
        .all()
    )

    cat_totals: dict[int, dict[tuple, float]] = {}
    cat_names: dict[int, str] = {}
    for t in txs:
        if not t.category_id:
            continue
        cat_totals.setdefault(t.category_id, {})
        key = (t.date.year, t.date.month)
        cat_totals[t.category_id][key] = cat_totals[t.category_id].get(key, 0.0) + t.amount
        if t.category_id not in cat_names:
            cat = get_category(db, t.category_id)
            cat_names[t.category_id] = cat.name if cat else "Unbekannt"

    series = [
        {
            "category_id": cat_id,
            "category_name": cat_names[cat_id],
            "points": [round(abs(totals.get(mk, 0.0)), 2) for mk in month_keys],
        }
        for cat_id, totals in cat_totals.items()
    ]
    series.sort(key=lambda s: -sum(s["points"]))
    return {"months": [f"{y:04d}-{m:02d}" for y, m in month_keys], "series": series}


def _year_transactions(db: Session, space_id: int, year: int):
    start, end = date(year, 1, 1), date(year, 12, 31)
    return (
        db.query(models.Transaction)
        .join(models.Account)
        .filter(
            models.Account.space_id == space_id,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
            models.Transaction.is_transfer.is_(False),
        )
        .all()
    )


def year_review(db: Session, space_id: int, year: int) -> dict:
    """Jahresrueckblick - reine Auswertung bereits vorhandener Daten, keine neue
    Datenerfassung. 'Vermoegensentwicklung' bewusst nur als Investment-Rendite
    der letzten 12 Monate (dafuer gibt es echte Historie ueber portfolio_history),
    NICHT als Netto-Vermoegensverlauf - dafuer fehlt eine Snapshot-Historie
    (siehe Begruendung bei den Hub-Sparklines, die aus demselben Grund keine
    Nettovermoegen-Kurve zeigen)."""
    transactions = _year_transactions(db, space_id, year)
    total_income = round(sum(t.amount for t in transactions if t.amount > 0), 2)
    total_expense = round(sum(t.amount for t in transactions if t.amount < 0), 2)
    saved = round(total_income + total_expense, 2)
    savings_rate = round(saved / total_income * 100, 1) if total_income else None

    expenses = [t for t in transactions if t.amount < 0]
    biggest = None
    if expenses:
        t = min(expenses, key=lambda x: x.amount)
        cat = get_category(db, t.category_id) if t.category_id else None
        biggest = {
            "name": t.description or "Ohne Beschreibung",
            "amount": round(abs(t.amount), 2),
            "date": t.date.isoformat(),
            "category_name": cat.name if cat else None,
        }

    by_cat_total: dict[int | None, float] = {}
    by_cat_count: dict[int | None, int] = {}
    cat_names: dict[int | None, str] = {}
    for t in expenses:
        key = t.category_id
        by_cat_total[key] = by_cat_total.get(key, 0.0) + t.amount
        by_cat_count[key] = by_cat_count.get(key, 0) + 1
        if key is None:
            cat_names[key] = "Ohne Kategorie"
        elif key not in cat_names:
            cat = get_category(db, key)
            cat_names[key] = cat.name if cat else "Unbekannt"

    top_category = None
    if by_cat_total:
        key = min(by_cat_total, key=lambda k: by_cat_total[k])
        top_category = {"name": cat_names[key], "total": round(abs(by_cat_total[key]), 2), "count": by_cat_count[key]}

    most_frequent_category = None
    if by_cat_count:
        key = max(by_cat_count, key=lambda k: by_cat_count[k])
        most_frequent_category = {"name": cat_names[key], "count": by_cat_count[key], "total": round(abs(by_cat_total[key]), 2)}

    month_counts: dict[int, int] = {}
    monthly_points = []
    for m in range(1, 13):
        m_income = round(sum(t.amount for t in transactions if t.amount > 0 and t.date.month == m), 2)
        m_expense = round(sum(t.amount for t in transactions if t.amount < 0 and t.date.month == m), 2)
        m_count = sum(1 for t in transactions if t.date.month == m)
        month_counts[m] = m_count
        monthly_points.append({"year": year, "month": m, "income": m_income, "expense": m_expense})

    busiest_month = None
    if any(month_counts.values()):
        m = max(month_counts, key=lambda k: month_counts[k])
        busiest_month = {"month": m, "count": month_counts[m]}

    prev_transactions = _year_transactions(db, space_id, year - 1)
    prev_income = round(sum(t.amount for t in prev_transactions if t.amount > 0), 2)
    prev_expense = round(sum(t.amount for t in prev_transactions if t.amount < 0), 2)
    income_change_pct = round((total_income - prev_income) / prev_income * 100, 1) if prev_income else None
    expense_change_pct = (
        round((abs(total_expense) - abs(prev_expense)) / abs(prev_expense) * 100, 1) if prev_expense else None
    )

    investment_return_pct = None
    try:
        history = portfolio_history(db, space_id, "1J")
        if history.points:
            last = history.points[-1]
            if last.return_pct is not None:
                investment_return_pct = last.return_pct
    except Exception:
        pass

    return {
        "year": year,
        "total_income": total_income,
        "total_expense": total_expense,
        "saved": saved,
        "savings_rate": savings_rate,
        "transaction_count": len(transactions),
        "biggest_expense": biggest,
        "top_category": top_category,
        "most_frequent_category": most_frequent_category,
        "busiest_month": busiest_month,
        "income_change_pct": income_change_pct,
        "expense_change_pct": expense_change_pct,
        "investment_return_pct": investment_return_pct,
        "net_worth_now": net_worth(db, space_id).total,
        "monthly_points": monthly_points,
    }


# ---------- Business-Projekte (Nebenprojekte) ----------
def _enrich_business_project(db: Session, project: models.BusinessProject) -> models.BusinessProject:
    """Setzt die nicht in der Tabelle gespeicherten Anzeige-Felder (offene
    Punkte, Konto-Name, Einnahmen) - gemeinsam genutzt von allen Funktionen,
    die ein BusinessProject nach außen geben, damit keine davon vergisst,
    eines der Felder zu befüllen."""
    project.open_issue_count = (
        db.query(models.BusinessIssue)
        .filter(models.BusinessIssue.project_id == project.id, models.BusinessIssue.resolved.is_(False))
        .count()
    )
    project.account_name = None
    project.income_this_month = 0.0
    project.income_total = 0.0
    if project.account_id:
        account = db.query(models.Account).filter(models.Account.id == project.account_id).first()
        if account:
            project.account_name = account.name
            month_start = date.today().replace(day=1)
            # Nur Einnahmen (positive Betraege), keine Umbuchungen - eine
            # interne Umbuchung auf das verknuepfte Konto ist kein Verdienst
            # des Projekts.
            base_query = (
                db.query(func.sum(models.Transaction.amount))
                .filter(
                    models.Transaction.account_id == project.account_id,
                    models.Transaction.amount > 0,
                    models.Transaction.is_transfer.is_(False),
                )
            )
            project.income_total = base_query.scalar() or 0.0
            project.income_this_month = base_query.filter(models.Transaction.date >= month_start).scalar() or 0.0
    return project


def get_business_projects(db: Session, include_inactive: bool = False) -> list[models.BusinessProject]:
    query = db.query(models.BusinessProject)
    if not include_inactive:
        query = query.filter(models.BusinessProject.active.is_(True))
    projects = query.order_by(models.BusinessProject.name).all()
    for p in projects:
        _enrich_business_project(db, p)
    return projects


def get_business_project(db: Session, project_id: int) -> models.BusinessProject | None:
    return db.query(models.BusinessProject).filter(models.BusinessProject.id == project_id).first()


def create_business_project(db: Session, data: schemas.BusinessProjectCreate) -> models.BusinessProject:
    project = models.BusinessProject(
        name=data.name, description=data.description, check_interval_days=data.check_interval_days,
        account_id=data.account_id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return _enrich_business_project(db, project)


def update_business_project(db: Session, project: models.BusinessProject, data: schemas.BusinessProjectUpdate) -> models.BusinessProject:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return _enrich_business_project(db, project)


def mark_business_project_checked(db: Session, project: models.BusinessProject) -> models.BusinessProject:
    project.last_checked_at = datetime.utcnow()
    db.commit()
    db.refresh(project)
    return _enrich_business_project(db, project)


def _business_issue_out(issue: models.BusinessIssue) -> schemas.BusinessIssueOut:
    return schemas.BusinessIssueOut(
        id=issue.id, project_id=issue.project_id,
        project_name=issue.project.name if issue.project else None,
        title=issue.title, notes=issue.notes, resolved=issue.resolved,
        created_at=issue.created_at, resolved_at=issue.resolved_at,
    )


def get_business_issues(db: Session, project_id: int | None = None, include_resolved: bool = False) -> list[schemas.BusinessIssueOut]:
    query = db.query(models.BusinessIssue)
    if project_id:
        query = query.filter(models.BusinessIssue.project_id == project_id)
    if not include_resolved:
        query = query.filter(models.BusinessIssue.resolved.is_(False))
    rows = query.order_by(models.BusinessIssue.created_at.desc()).all()
    return [_business_issue_out(r) for r in rows]


def create_business_issue(db: Session, project_id: int, title: str, notes: str | None = None) -> schemas.BusinessIssueOut:
    issue = models.BusinessIssue(project_id=project_id, title=title, notes=notes)
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return _business_issue_out(issue)


def resolve_business_issue(db: Session, issue: models.BusinessIssue) -> schemas.BusinessIssueOut:
    issue.resolved = True
    issue.resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(issue)
    return _business_issue_out(issue)


def find_business_project_by_name(db: Session, name_query: str) -> tuple[models.BusinessProject | None, str | None]:
    """Sucht ein aktives Projekt per (Teil-)Name - fürs Telegram-Freitext-
    Anlegen eines offenen Punkts, analog zu complete_todo_by_name. Gibt
    (projekt, error) zurück: error ist None bei Erfolg, sonst ein Text zum
    direkten Zurücksenden (kein Treffer / mehrdeutig)."""
    q = name_query.strip().lower()
    if not q:
        return None, "Kein Projektname angegeben."
    projects = db.query(models.BusinessProject).filter(models.BusinessProject.active.is_(True)).all()
    matches = [p for p in projects if q in p.name.lower()]
    if not matches:
        namen = ", ".join(p.name for p in projects) or "noch keine Projekte angelegt"
        return None, f"Kein Projekt mit „{name_query}“ gefunden. Vorhanden: {namen}"
    if len(matches) > 1:
        namen = ", ".join(p.name for p in matches)
        return None, f"„{name_query}“ ist nicht eindeutig, passt auf: {namen}. Bitte genauer benennen."
    return matches[0], None


def find_open_business_issue(db: Session, project_id: int, title_query: str) -> tuple[models.BusinessIssue | None, str | None]:
    """Wie find_business_project_by_name, aber für einen offenen Punkt
    innerhalb eines Projekts (zum Abhaken per Telegram)."""
    q = title_query.strip().lower()
    if not q:
        return None, "Kein Stichwort angegeben."
    open_issues = (
        db.query(models.BusinessIssue)
        .filter(models.BusinessIssue.project_id == project_id, models.BusinessIssue.resolved.is_(False))
        .all()
    )
    matches = [i for i in open_issues if q in i.title.lower()]
    if not matches:
        namen = ", ".join(i.title for i in open_issues) or "keine offenen Punkte"
        return None, f"Nichts mit „{title_query}“ gefunden. Offen: {namen}"
    if len(matches) > 1:
        namen = ", ".join(i.title for i in matches)
        return None, f"„{title_query}“ ist nicht eindeutig, passt auf: {namen}. Bitte genauer benennen."
    return matches[0], None


# ---------- Leben (persönliche Lebensbereiche) ----------
LIFE_AREA_HISTORY_DAYS = 30


def _life_area_streak_and_history(db: Session, area_id: int, days: int = LIFE_AREA_HISTORY_DAYS) -> tuple[list[str], int]:
    """Liefert (Tage mit mind. einem Check-in der letzten `days` Tage als
    ISO-Strings, aktuelle Streak-Länge) für die visuelle Historie im Frontend
    (Nutzerwunsch: Konsequenz sichtbar machen, nicht nur eine Liste). Die
    Streak zählt rückwärts ab heute - hat der Nutzer heute noch nicht
    eingecheckt, aber gestern schon, bricht die Streak dadurch noch nicht ab
    (Kulanz bis Tagesende, wie bei den gängigen Streak-Apps)."""
    since = date.today() - timedelta(days=days - 1)
    rows = (
        db.query(func.date(models.LifeCheckIn.created_at))
        .filter(
            models.LifeCheckIn.area_id == area_id,
            models.LifeCheckIn.created_at >= datetime.combine(since, datetime.min.time()),
        )
        .distinct()
        .all()
    )
    checkin_days = {r[0] for r in rows}

    streak = 0
    cursor = date.today()
    if cursor.isoformat() not in checkin_days:
        cursor -= timedelta(days=1)
    while cursor.isoformat() in checkin_days:
        streak += 1
        cursor -= timedelta(days=1)

    return sorted(checkin_days), streak


def get_life_areas(db: Session, include_inactive: bool = False) -> list[models.LifeArea]:
    query = db.query(models.LifeArea)
    if not include_inactive:
        query = query.filter(models.LifeArea.active.is_(True))
    areas = query.order_by(models.LifeArea.name).all()
    for a in areas:
        a.checkin_days_30, a.streak_days = _life_area_streak_and_history(db, a.id)
    return areas


def get_life_area(db: Session, area_id: int) -> models.LifeArea | None:
    area = db.query(models.LifeArea).filter(models.LifeArea.id == area_id).first()
    if area:
        area.checkin_days_30, area.streak_days = _life_area_streak_and_history(db, area.id)
    return area


def create_life_area(db: Session, data: schemas.LifeAreaCreate) -> models.LifeArea:
    # Dieselbe Begrenzung wie update_life_area/create_life_checkin - ohne das
    # könnte ein direkter POST-Aufruf (z.B. Tippfehler) den Fortschritt
    # außerhalb 0-100 anlegen und die Balken-Darstellung verzerren.
    progress = max(0, min(100, data.progress_percent)) if data.progress_percent is not None else None
    area = models.LifeArea(
        name=data.name, description=data.description, target_date=data.target_date,
        progress_percent=progress, check_interval_days=data.check_interval_days,
    )
    db.add(area)
    db.commit()
    db.refresh(area)
    area.checkin_days_30, area.streak_days = _life_area_streak_and_history(db, area.id)
    return area


def update_life_area(db: Session, area: models.LifeArea, data: schemas.LifeAreaUpdate) -> models.LifeArea:
    for key, value in data.model_dump(exclude_unset=True).items():
        # Dieselbe Begrenzung wie create_life_checkin - ohne das könnte ein
        # direktes PATCH (z.B. Tippfehler) den Fortschritt außerhalb 0-100
        # setzen, was die Balken-Darstellung im Frontend verzerren würde.
        if key == "progress_percent" and value is not None:
            value = max(0, min(100, value))
        setattr(area, key, value)
    db.commit()
    db.refresh(area)
    area.checkin_days_30, area.streak_days = _life_area_streak_and_history(db, area.id)
    return area


def _life_checkin_out(checkin: models.LifeCheckIn) -> schemas.LifeCheckInOut:
    return schemas.LifeCheckInOut(
        id=checkin.id, area_id=checkin.area_id,
        area_name=checkin.area.name if checkin.area else None,
        note=checkin.note, created_at=checkin.created_at,
    )


def get_life_checkins(db: Session, area_id: int | None = None, limit: int = 50) -> list[schemas.LifeCheckInOut]:
    query = db.query(models.LifeCheckIn)
    if area_id:
        query = query.filter(models.LifeCheckIn.area_id == area_id)
    rows = query.order_by(models.LifeCheckIn.created_at.desc()).limit(limit).all()
    return [_life_checkin_out(r) for r in rows]


def create_life_checkin(db: Session, area_id: int, note: str, progress_percent: int | None = None) -> schemas.LifeCheckInOut:
    checkin = models.LifeCheckIn(area_id=area_id, note=note)
    db.add(checkin)
    area = db.query(models.LifeArea).filter(models.LifeArea.id == area_id).first()
    if area:
        area.last_checked_at = datetime.utcnow()
        if progress_percent is not None:
            area.progress_percent = max(0, min(100, progress_percent))
    db.commit()
    db.refresh(checkin)
    return _life_checkin_out(checkin)


def find_life_area_by_name(db: Session, name_query: str) -> tuple[models.LifeArea | None, str | None]:
    """Sucht einen aktiven Lebensbereich per (Teil-)Name - fürs Telegram-
    Freitext-Check-in, analog zu find_business_project_by_name."""
    q = name_query.strip().lower()
    if not q:
        return None, "Kein Bereichsname angegeben."
    areas = db.query(models.LifeArea).filter(models.LifeArea.active.is_(True)).all()
    matches = [a for a in areas if q in a.name.lower()]
    if not matches:
        namen = ", ".join(a.name for a in areas) or "noch keine Lebensbereiche angelegt"
        return None, f"Kein Lebensbereich mit „{name_query}“ gefunden. Vorhanden: {namen}"
    if len(matches) > 1:
        namen = ", ".join(a.name for a in matches)
        return None, f"„{name_query}“ ist nicht eindeutig, passt auf: {namen}. Bitte genauer benennen."
    return matches[0], None


# ---------- Wunschliste ----------
def get_wishlist_items(db: Session, include_inactive: bool = False) -> list[models.WishlistItem]:
    query = db.query(models.WishlistItem)
    if not include_inactive:
        query = query.filter(models.WishlistItem.active.is_(True))
    return query.order_by(models.WishlistItem.created_at.desc()).all()


def get_wishlist_item(db: Session, item_id: int) -> models.WishlistItem | None:
    return db.query(models.WishlistItem).filter(models.WishlistItem.id == item_id).first()


def create_wishlist_item(db: Session, data: schemas.WishlistItemCreate) -> models.WishlistItem:
    item = models.WishlistItem(
        name=data.name, category=data.category, target_price=data.target_price, url=data.url,
        notes=data.notes, check_interval_days=data.check_interval_days,
        auto_check_enabled=data.auto_check_enabled,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_wishlist_item(db: Session, item: models.WishlistItem, data: schemas.WishlistItemUpdate) -> models.WishlistItem:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


def mark_wishlist_item_checked(db: Session, item: models.WishlistItem) -> models.WishlistItem:
    item.last_checked_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return item


def find_wishlist_item_by_name(db: Session, name_query: str) -> tuple[models.WishlistItem | None, str | None]:
    """Analog zu find_business_project_by_name/find_life_area_by_name."""
    q = name_query.strip().lower()
    if not q:
        return None, "Kein Name angegeben."
    items = db.query(models.WishlistItem).filter(
        models.WishlistItem.active.is_(True), models.WishlistItem.purchased.is_(False),
    ).all()
    matches = [i for i in items if q in i.name.lower()]
    if not matches:
        namen = ", ".join(i.name for i in items) or "noch nichts auf der Wunschliste"
        return None, f"Nichts mit „{name_query}“ auf der Wunschliste gefunden. Vorhanden: {namen}"
    if len(matches) > 1:
        namen = ", ".join(i.name for i in matches)
        return None, f"„{name_query}“ ist nicht eindeutig, passt auf: {namen}. Bitte genauer benennen."
    return matches[0], None


# ---------- Heute-Übersicht ----------
def day_balance(db: Session, space_id: int, day: date) -> schemas.TodayBalance:
    """Einnahmen/Ausgaben genau eines Tages. Umbuchungen zwischen eigenen
    Konten bleiben außen vor - dieselbe Regel wie im Dashboard, sonst würde
    ein Übertrag den Tag künstlich als „viel bewegt" erscheinen lassen."""
    rows = (
        db.query(models.Transaction.amount)
        .join(models.Account)
        .filter(
            models.Account.space_id == space_id,
            models.Transaction.date == day,
            models.Transaction.is_transfer.is_(False),
        )
        .all()
    )
    income = sum(a for (a,) in rows if a > 0)
    expense = sum(a for (a,) in rows if a < 0)
    return schemas.TodayBalance(
        income=round(income, 2), expense=round(expense, 2),
        balance=round(income + expense, 2), transaction_count=len(rows),
    )


# ---------- Kontextbezogene Notizen ----------
def get_notes(db: Session, entity_type: str, entity_id: int) -> list[models.Note]:
    return (
        db.query(models.Note)
        .filter(models.Note.entity_type == entity_type, models.Note.entity_id == entity_id)
        .order_by(models.Note.created_at.desc())
        .all()
    )


def create_note(db: Session, data: schemas.NoteCreate) -> models.Note:
    note = models.Note(entity_type=data.entity_type, entity_id=data.entity_id, text=data.text)
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def delete_note(db: Session, note_id: int) -> bool:
    note = db.query(models.Note).filter(models.Note.id == note_id).first()
    if not note:
        return False
    db.delete(note)
    db.commit()
    return True


def search_notes(db: Session, q: str, limit: int = 30) -> list[models.Note]:
    return (
        db.query(models.Note)
        .filter(models.Note.text.ilike(f"%{q}%"))
        .order_by(models.Note.created_at.desc())
        .limit(limit)
        .all()
    )
