import calendar
import hashlib
import re
import unicodedata
from datetime import date, datetime, timedelta
from statistics import median
from sqlalchemy import func, extract
from sqlalchemy.orm import Session
from . import models, schemas, debts, travel_time
# Investments-Domäne (Holdings/Lots, Diversifikation, Dividenden, Kurshistorie)
# lebt seit der crud.py-Modularisierung in crud_investments.py (siehe dort) -
# hier zurückimportiert, damit jeder bestehende crud.holding_out(...)-Aufruf
# in main.py/routers/ unverändert weiterfunktioniert. net_worth (unten in
# dieser Datei) ruft z.B. get_holdings auf - genau dafür der Rückimport.
from .crud_investments import (
    get_cached_history, get_holdings, get_holding, find_holding_by_symbol,
    create_holding, update_holding, delete_holding, holding_out,
    recompute_holding_from_lots, get_lots, get_lot, create_lot, update_lot,
    delete_lot, portfolio_diversification, compute_volatility, portfolio_volatility,
    get_cached_dividends, holding_dividends, portfolio_dividends,
    estimate_next_dividends, evaluate_dividend_reminders, holding_history,
    portfolio_history, refresh_price_history_cache, get_savings_plans,
)
# To-Dos & Kalender (inkl. RRULE-Expansion) lebt in crud_todos.py -
# get_upcoming_calendar_events wird unten von build_digest gebraucht.
from .crud_todos import (
    get_todos, get_todo, create_todo, update_todo, complete_todo_by_name,
    cleanup_old_done_todos, get_upcoming_calendar_events, detect_calendar_conflicts,
    delete_todo, get_calendar_events, get_calendar_event, create_calendar_event,
    update_calendar_event, cancel_calendar_event_by_name, delete_calendar_event,
)
# Externe Konten-Verbindungen (FinTS, Bitvavo, PayPal, Enable Banking, eBay)
# leben in crud_connections.py - reines CRUD ohne Abhängigkeiten zu anderen
# crud.py-Domänen, hier nur zurückimportiert für unveränderte Aufrufstile.
from .crud_connections import (
    get_bank_connections, get_bank_connection, get_all_bank_connections,
    create_bank_connection, delete_bank_connection,
    get_bitvavo_connections, get_bitvavo_connection, get_all_bitvavo_connections,
    create_bitvavo_connection, delete_bitvavo_connection,
    get_paypal_connections, get_paypal_connection, get_all_paypal_connections,
    create_paypal_connection, delete_paypal_connection,
    get_enablebanking_connections, get_enablebanking_connection,
    get_enablebanking_connection_by_state, get_all_enablebanking_connections,
    create_enablebanking_connection, delete_enablebanking_connection,
    get_ebay_connections, get_ebay_connection, get_ebay_connection_by_state,
    get_all_ebay_connections, create_ebay_connection, delete_ebay_connection,
)
# Ziele leben in crud_goals.py - get_goals wird unten vom KI-Assistent-Belege-
# Check (fehlende-Belege-Erkennung) innerhalb dieser Datei selbst gebraucht.
from .crud_goals import (
    get_goals, get_goal, get_open_auto_goals, create_goal, update_goal,
    delete_goal, set_goal_completed, mark_goals_seen, get_goal_progress_points,
)
# Business-Projekte, Leben (persönliche Lebensbereiche) und Wunschliste leben
# in crud_life_areas.py - _life_area_streak_and_history wird von main.py
# direkt (crud._life_area_streak_and_history) gebraucht.
from .crud_life_areas import (
    get_business_projects, get_business_project, create_business_project,
    update_business_project, mark_business_project_checked, get_business_issues,
    create_business_issue, resolve_business_issue, find_business_project_by_name,
    find_open_business_issue, _life_area_streak_and_history, get_life_areas,
    get_life_area, create_life_area, update_life_area, get_life_checkins,
    create_life_checkin, find_life_area_by_name, get_wishlist_items,
    get_wishlist_item, create_wishlist_item, update_wishlist_item,
    mark_wishlist_item_checked, find_wishlist_item_by_name,
)
# Notizen, Zeiterfassung, People/CRM-Light, Leseliste und Gesundheits-
# Grunddaten leben in crud_misc.py - search_notes wird unten von der
# Globalen Suche innerhalb dieser Datei selbst gebraucht.
from .crud_misc import (
    get_notes, create_note, delete_note, search_notes,
    get_time_entries, get_running_time_entry, start_time_entry, stop_time_entry,
    create_manual_time_entry, delete_time_entry, project_time_summaries,
    get_contacts, create_contact, update_contact, delete_contact, touch_contact,
    get_media_items, create_media_item, update_media_item, delete_media_item,
    get_health_metrics, create_health_metric, delete_health_metric,
)
# Trips und KI-Review-Queue (Kategorisierungsvorschläge) leben in
# crud_trips_review.py - reines, voneinander unabhängiges CRUD.
from .crud_trips_review import (
    get_trips, get_trip, create_trip, update_trip, delete_trip, trip_summary,
    get_pending_category_suggestions, decide_category_suggestion,
)
from .crud_routines import (
    get_routines, create_routine, update_routine, delete_routine,
    toggle_routine_item, get_due_routines,
)
from .crud_vehicle import (
    get_or_create_vehicle, vehicle_out, update_vehicle, set_vehicle_model_3d,
    get_fuel_entries, create_fuel_entry, get_fuel_entry, update_fuel_entry,
    delete_fuel_entry, fuel_summary,
    get_vehicle_goals, create_vehicle_goal, get_vehicle_goal, update_vehicle_goal,
    delete_vehicle_goal,
)
from .crud_smarthome import (
    get_smarthome_aliases, create_smarthome_alias, delete_smarthome_alias,
    log_smarthome_action, get_smarthome_actions,
    get_floorplan, save_floorplan,
    get_automation_drafts, set_automation_draft_status, delete_automation_draft,
)
from .crud_meals import (
    get_recipes, get_recipe, create_recipe, update_recipe, delete_recipe,
    get_meal_plan, set_meal_plan_entry, clear_meal_plan_entry, shopping_list,
)

CACHE_TTL = timedelta(hours=24)


def _merchant_key(description: str | None) -> str:
    """Grobe Gegenstellen-Kennung aus einer Buchungsbeschreibung - erste ein
    bis zwei alphanumerische "Wörter" (Bank-Buchungstexte beginnen fast immer
    mit dem Händlernamen, z.B. "REWE SAGT DANKE 123456", "PAYPAL *SPOTIFY") -
    ignoriert reine Zahlen/Referenznummern als eigenes Wort, die würden sonst
    Buchungen desselben Händlers künstlich auseinanderreißen. Für "Lernen aus
    Korrekturen" (Spezifikation Abschnitt K) - dieselbe Normalisierung beim
    Loggen einer Korrektur (siehe update_transaction) und beim späteren
    Anwenden einer daraus gelernten Regel (siehe ai_auto._apply_learned_rules)."""
    if not description:
        return ""
    words = [w for w in re.findall(r"[a-zA-ZäöüÄÖÜß]+", description) if len(w) >= 3]
    return " ".join(words[:2]).lower()


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


def find_account_by_name(db: Session, space_id: int, name_query: str) -> tuple[models.Account | None, str | None]:
    """Gleiches (Teil-)Namens-Matching wie set_balance_by_name (accounts-
    Teil), als eigene Funktion für die schnelle Ausgabe per Telegram (siehe
    telegram_bot._handle_expense_command, Spezifikationspunkt D "einheitliche
    Absichten") - bewusst KEIN Rateversuch bei Mehrdeutigkeit, das Konto für
    eine Geldbuchung ist genauso wenig verhandelbar wie der Betrag selbst."""
    accounts = get_accounts(db, space_id)
    q = name_query.strip().lower()
    matches = [a for a in accounts if q in a.name.lower()]
    if not matches:
        namen = ", ".join(a.name for a in accounts)
        return None, f"Kein Konto mit „{name_query}“ gefunden. Vorhanden: {namen}"
    if len(matches) > 1:
        namen = ", ".join(a.name for a in matches)
        return None, f"„{name_query}“ ist nicht eindeutig, passt auf: {namen}. Bitte genauer benennen."
    return matches[0], None


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
    all_categories = db.query(models.Category).all()
    category_names = {c.id: c.name for c in all_categories}
    # Bugfix (live gemeldet, 2026-08-28): eine Einnahmen-Kategorie (type=
    # einnahme, z.B. "Sonstige Einnahmen") konnte trotzdem "Ausgaben-
    # Ausreißer" auslösen, wenn genug negativ vorzeichnete Buchungen darin
    # landeten (z.B. Korrekturen/nicht als Umbuchung erkannte Transfers) -
    # die alte Prüfung schaute nur auf das Vorzeichen der Monatssumme, nie
    # auf category.type. Ein "Ausgaben-Ausreißer" ergibt für eine explizit
    # als Einnahme markierte Kategorie konzeptionell keinen Sinn und war
    # live nachweislich irreführend (siehe Beispiel "Sonstige Einnahmen").
    expense_category_ids = {c.id for c in all_categories if c.type == models.CategoryType.ausgabe}
    cat_ids = {cid for cid, _, _ in by_cat_month.keys() if cid in expense_category_ids}

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
        # "Lernen aus Korrekturen" (Spezifikation Abschnitt K) - nur echte
        # Korrekturen zaehlen (vorherige Kategorie war schon gesetzt), keine
        # Erstzuordnung eines bisher unkategorisierten Postens.
        if db_transaction.category_id is not None:
            merchant_key = _merchant_key(db_transaction.description)
            if merchant_key:
                db.add(models.CategoryCorrection(merchant_key=merchant_key, new_category_id=changes["category_id"]))
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


# Schwelle fuer "haengt zu lange" - Todos ohne Faelligkeitsdatum, Business-
# Issues, siehe get_hanging_items. Business/Leben/Wunschliste-Ueberfaelligkeit
# haben bereits eigene, schaerfere Schwellen (check_interval_days je Eintrag)
# und werden hier bewusst NICHT erneut mit dieser groben Konstante geprueft.
HANGING_TODO_NO_DATE_DAYS = 14
HANGING_BUSINESS_ISSUE_DAYS = 14


def get_hanging_items(db: Session) -> dict:
    """"Was hängt schon zu lange?" (Spezifikation Abschnitt E) - bewusst KEIN
    zweites Projektmanagement-System, sondern eine reine Zusammenstellung
    bestehender Daten für /haengt (telegram_bot.py) und den Morgen-Briefing-
    Kurzhinweis (siehe build_morning_briefing). Todos/Business-Projekte sind
    bereichsübergreifend (kein space_id, siehe models.Todo/BusinessProject),
    deshalb kein space_id-Parameter, analog zu _scheduled_evening_review.

    Lebensbereiche/Wunschliste bewusst NICHT hier erneut geprüft - die haben
    schon eigene tägliche Erinnerungen (main._scheduled_life_check_reminder/
    _scheduled_wishlist_reminder) mit eigenen, pro Eintrag konfigurierbaren
    Schwellen (check_interval_days) - eine zweite, gröbere Prüfung hier würde
    nur denselben Zustand doppelt melden (Leitprinzip 5: nicht doppelt nerven).
    Todos ohne Datum sind dagegen eine echte Lücke: die werden bisher NIRGENDS
    proaktiv gemeldet, nur passiv in der normalen To-Do-Liste sichtbar."""
    now = datetime.utcnow()
    today = date.today()

    todos_no_date = [
        t for t in db.query(models.Todo)
        .filter(models.Todo.done.is_(False), models.Todo.due_date.is_(None))
        .all()
        if t.created_at and (now - t.created_at).days >= HANGING_TODO_NO_DATE_DAYS
    ]
    todos_overdue = [
        t for t in db.query(models.Todo)
        .filter(models.Todo.done.is_(False), models.Todo.due_date.isnot(None), models.Todo.due_date < today)
        .all()
    ]
    business_issues = [
        i for i in db.query(models.BusinessIssue).filter(models.BusinessIssue.resolved.is_(False)).all()
        if i.created_at and (now - i.created_at).days >= HANGING_BUSINESS_ISSUE_DAYS
    ]
    return {
        "todos_no_date": todos_no_date,
        "todos_overdue": todos_overdue,
        "business_issues": business_issues,
    }


def get_recent_sync_errors(db: Session, settings: models.Settings, hours: int = 24) -> list[dict]:
    """Fehler-Log für die Einstellungen (vorgemerkte Idee, siehe Obsidian-
    Notiz "Kies - Offene Punkte") - aggregiert die bereits vorhandenen
    last_sync_status-Felder ALLER Verbindungsarten (Bank/Bitvavo/PayPal/
    Enable Banking/eBay/Scalable) zu einer Liste, statt eine neue Tabelle +
    Schreib-Hooks an jeder Sync-Stelle einzuführen - bewusst risikoarm
    gehalten (rein lesend, kein neuer Schreibpfad), da diese Funktion ohne
    Live-Rücksprache entstanden ist. `settings` wird wie überall sonst in
    crud.py vom Aufrufer übergeben statt hier selbst geladen (crud.py holt
    Settings nirgends selbst, das bleibt Aufgabe von auth.get_or_create_
    settings beim Router/Scheduler). Dieselbe Konvention wie
    sync_all_connections: die get_all_*-Funktionen sind nicht nach Space
    gefiltert (Verbindungen sind bei diesem Single-User-System ohnehin
    faktisch global relevant)."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    errors = []

    def _add(source: str, name: str, status: str | None, at: datetime | None):
        if status and status.startswith("Fehler") and at and at >= cutoff:
            errors.append({"source": source, "name": name, "status": status, "at": at})

    for c in get_all_bank_connections(db):
        _add("Bank (FinTS)", c.name, c.last_sync_status, c.last_sync_at)
    for c in get_all_bitvavo_connections(db):
        _add("Bitvavo", c.name, c.last_sync_status, c.last_sync_at)
    for c in get_all_paypal_connections(db):
        _add("PayPal", c.name, c.last_sync_status, c.last_sync_at)
    for c in get_all_enablebanking_connections(db):
        _add("Enable Banking", c.aspsp_name, c.last_sync_status, c.last_sync_at)
    for c in get_all_ebay_connections(db):
        _add("eBay", c.ebay_username or "eBay", c.last_sync_status, c.last_sync_at)
    if settings.scalable_enabled:
        _add("Scalable Capital", "Scalable Capital", settings.scalable_last_sync_status, settings.scalable_last_sync_at)

    errors.sort(key=lambda e: e["at"], reverse=True)
    return errors


def build_hanging_summary(db: Session) -> str:
    """Telegram-Text für /haengt (telegram_bot.py) - reine Textdarstellung von
    get_hanging_items(), plus Lebensbereiche/Wunschliste auf Zuruf (die eigenen
    proaktiven täglichen Erinnerungen bleiben unverändert, siehe dortige
    Docstrings - hier nur zusätzlich als Pull-Übersicht auf einen Blick)."""
    items = get_hanging_items(db)
    lines = ["🕸 Was hängt:"]
    if items["todos_no_date"]:
        lines.append(f"\n📝 {len(items['todos_no_date'])} To-Do(s) ohne Datum seit {HANGING_TODO_NO_DATE_DAYS}+ Tagen:")
        for t in items["todos_no_date"][:8]:
            lines.append(f"- „{t.title}“")
    if items["todos_overdue"]:
        lines.append(f"\n⏰ {len(items['todos_overdue'])} überfällige(s) To-Do(s):")
        for t in items["todos_overdue"][:8]:
            lines.append(f"- „{t.title}“ (fällig {t.due_date.strftime('%d.%m.%Y')})")
    if items["business_issues"]:
        lines.append(f"\n📋 {len(items['business_issues'])} offene(r) Projekt-Punkt(e) seit {HANGING_BUSINESS_ISSUE_DAYS}+ Tagen.")

    now = datetime.utcnow()
    areas = db.query(models.LifeArea).filter(
        models.LifeArea.active.is_(True), models.LifeArea.check_interval_days.isnot(None),
    ).all()
    overdue_areas = [
        a for a in areas
        if (a.last_checked_at or a.created_at) and (now - (a.last_checked_at or a.created_at)).days >= a.check_interval_days
    ]
    if overdue_areas:
        lines.append("\n🎯 Check-in überfällig: " + ", ".join(f"„{a.name}“" for a in overdue_areas) + ".")

    overdue_wishlist = [
        w for w in db.query(models.WishlistItem).filter(
            models.WishlistItem.active.is_(True), models.WishlistItem.purchased.is_(False),
            models.WishlistItem.check_interval_days.isnot(None),
        ).all()
        if (now - (w.last_checked_at or w.created_at)).days >= w.check_interval_days
    ]
    if overdue_wishlist:
        lines.append(f"\n🛒 {len(overdue_wishlist)} Wunschlisten-Eintrag/Einträge überfällig zur Prüfung.")

    if len(lines) == 1:
        return "🕸 Nichts hängt gerade - alles im grünen Bereich. 👍"
    return "\n".join(lines)


def build_morning_briefing(
    db: Session, space_id: int,
    home_coords: tuple[float, float] | None = None, ors_api_key: str | None = None,
) -> str | None:
    """Morgen-Briefing (Spezifikation Abschnitt A) - EIN kompakter Ping am
    Morgen, klar abgegrenzt vom 3-stündlichen Digest (main.build_digest, dort
    volle Nettovermögen-Aufschlüsselung + 3-Tage-Kalenderausblick + Ziele +
    Dubletten) und vom taeglichen Abend-Review (nur Lebensbereiche/Projekte/
    Wunschliste). Bewusst NUR: heutige Termine, faellige/ueberfaellige Todos,
    EINE knappe Finanzzeile (Vergleich zu GESTERN, nicht die volle Aufteilung),
    nahe Fristen, und ein Kurzhinweis auf Todos ohne Datum (Details via
    /haengt) - kein Fortschritts-Duplikat der bereits separat laufenden
    Lebensbereich-/Projekt-/Wunschlisten-Erinnerungen (siehe get_hanging_items-
    Docstring).

    Nutzt dieselben Bausteine wie main.today_overview (/api/today, Hub "Heute"-
    Tab) fuer Termine/Todos/Fristen, statt die Abfragen zu duplizieren - baut
    aber einen eigenen, kompakten Telegram-Text statt der vollen JSON-Struktur.

    Gibt None zurueck, wenn wirklich nichts Relevantes ansteht - main.
    _scheduled_morning_briefing entscheidet anhand von
    settings.morning_briefing_send_empty, ob dann trotzdem eine (leere)
    Meldung rausgeht oder ganz geschwiegen wird (Default: schweigen)."""
    today = date.today()
    day_start = datetime.combine(today, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    lines = [f"☀️ Guten Morgen ({today.strftime('%d.%m.%Y')}):"]
    has_content = False

    # Reise-Modus (Spezifikation Abschnitt H) - gleiche Erkennung wie /today
    # (main.today_overview: active_trip), hier zusätzlich im Briefing erwähnt.
    for t in get_trips(db, space_id):
        if t.start_date and t.end_date and t.start_date <= today <= t.end_date:
            trip = trip_summary(db, t)
            has_content = True
            if trip.budget:
                lines.append(
                    f"\n✈️ Reise „{trip.name}“ läuft: {trip.total_spent:.2f} von {trip.budget:.2f} EUR Budget "
                    f"ausgegeben."
                )
            else:
                lines.append(
                    f"\n✈️ Reise „{trip.name}“ läuft: {trip.total_spent:.2f} EUR bisher ({trip.transaction_count} "
                    f"Buchung(en))."
                )
            if trip.missing_receipts_count:
                lines.append(
                    f"📎 {trip.missing_receipts_count} Ausgabe(n) auf der Reise noch ohne Beleg."
                )
            break  # zwei gleichzeitig aktive Trips sind ein Datenfehler, nicht vorgesehen (wie in /today)

    raw_events = get_calendar_events(db, day_start, day_end)
    if raw_events:
        has_content = True
        lines.append("\n🗓 Heute:")
        for ev in sorted(raw_events, key=lambda e: (not e.all_day, e.start))[:8]:
            zeit = "ganztägig" if ev.all_day else ev.start.strftime("%H:%M")
            ort = f" @ {ev.location}" if ev.location else ""
            fahrzeit = ""
            if (
                home_coords and ors_api_key and not ev.all_day and ev.lat and ev.lon
                and ev.start >= datetime.utcnow()
            ):
                try:
                    minuten = travel_time.travel_time_minutes(ors_api_key, home_coords, (ev.lat, ev.lon))
                except Exception:
                    minuten = None
                if minuten is not None:
                    leave_at = (ev.start - timedelta(minutes=minuten)).strftime("%H:%M")
                    fahrzeit = f" · 🚗 ~{minuten} Min, losfahren ca. {leave_at}"
            lines.append(f"- {zeit}: {ev.title}{ort}{fahrzeit}")

    todos_today = [t for t in get_todos(db, include_done=False) if t.due_date and t.due_date <= today]
    if todos_today:
        has_content = True
        todos_today.sort(key=lambda t: t.due_date)
        lines.append("\n✅ Fällig/überfällig:")
        for t in todos_today[:8]:
            marker = " (überfällig)" if t.due_date < today else ""
            lines.append(f"- „{t.title}“{marker}")

    yesterday = today - timedelta(days=1)
    nw = net_worth(db, space_id)
    snap_yesterday = (
        db.query(models.NetWorthSnapshot)
        .filter(models.NetWorthSnapshot.space_id == space_id, models.NetWorthSnapshot.date == yesterday)
        .first()
    )
    if snap_yesterday:
        delta = round(nw.total - snap_yesterday.total, 2)
        if delta:
            has_content = True
            pfeil = "📈" if delta > 0 else "📉"
            lines.append(f"\n💰 Nettovermögen: {nw.total:.2f} EUR ({pfeil} {delta:+.2f} EUR seit gestern)")

    deadlines: list[str] = []
    for r in get_contract_reminders(db, space_id):
        if r.days_until_reminder <= 3:
            deadlines.append(f"- „{r.label}“ (Kündigungsfrist beginnt in {r.days_until_reminder} Tag(en))")
    for d in get_return_deadlines(db, space_id):
        if not d.returned and d.days_left <= 3:
            deadlines.append(f"- „{d.transaction_description or 'Rückgabe'}“ (noch {d.days_left} Tag(e))")
    if deadlines:
        has_content = True
        lines.append("\n⏳ Fristen (nächste 3 Tage):")
        lines.extend(deadlines[:5])

    hanging = get_hanging_items(db)
    n_hanging = len(hanging["todos_no_date"])
    if n_hanging:
        has_content = True
        lines.append(f"\n📝 {n_hanging} To-Do(s) ohne Datum seit {HANGING_TODO_NO_DATE_DAYS}+ Tagen - Details via /haengt.")

    if not has_content:
        return None
    return "\n".join(lines)


# ---------- Jarvis-Vorschläge (Spezifikation Abschnitt B) ----------
# Bewusst ein EINZELNER offener Vorschlag zur Zeit (main._scheduled_
# suggestion_check erzeugt nie einen zweiten, solange einer pending ist) -
# hält den Telegram-Dialog eindeutig ("worauf bezieht sich /ok gerade"),
# ohne IDs im Chat nennen zu müssen. Weitere Kandidaten warten einfach bis
# zur nächsten Prüfung.
def get_pending_suggestion(db: Session) -> models.AssistantSuggestion | None:
    return (
        db.query(models.AssistantSuggestion)
        .filter(models.AssistantSuggestion.status == models.AssistantSuggestionStatus.pending)
        .order_by(models.AssistantSuggestion.created_at)
        .first()
    )


def create_suggestion_if_new(db: Session, kind: str, ref_id: int, title: str) -> models.AssistantSuggestion | None:
    """Legt einen neuen Vorschlag an, AUSSER es gibt für (kind, ref_id) schon
    einen (UNIQUE-Constraint, siehe models.AssistantSuggestion) - dann nur bei
    status=snoozed UND abgelaufenem snoozed_until reaktivieren (erneut als
    pending melden), sonst None (bereits entschieden oder noch snoozed,
    keine Wiedervorlage - Leitprinzip: einmal abgelehnt heißt nicht täglich
    wieder gefragt)."""
    existing = (
        db.query(models.AssistantSuggestion)
        .filter(models.AssistantSuggestion.kind == kind, models.AssistantSuggestion.ref_id == ref_id)
        .first()
    )
    if existing:
        if (
            existing.status == models.AssistantSuggestionStatus.snoozed
            and existing.snoozed_until and existing.snoozed_until <= date.today()
        ):
            existing.status = models.AssistantSuggestionStatus.pending
            existing.title = title
            existing.snoozed_until = None
            existing.decided_at = None
            db.commit()
            return existing
        return None
    suggestion = models.AssistantSuggestion(kind=kind, ref_id=ref_id, title=title)
    db.add(suggestion)
    db.commit()
    return suggestion


def decide_pending_suggestion(db: Session, decision: str) -> tuple[models.AssistantSuggestion | None, str]:
    """Verarbeitet /ok, /später oder /verwerfen (telegram_bot.py) auf den
    aktuell einzigen offenen Vorschlag. Gibt (Vorschlag-oder-None, Antworttext)
    zurück - der Vorschlag wird auch bei "kein offener Vorschlag" nicht
    gebraucht, nur der Text für die Telegram-Antwort.

    /ok führt bei kind="todo_no_date" eine konkrete, sichere Aktion aus
    (Fälligkeitsdatum auf heute setzen - "terminieren" statt "streichen",
    da ein automatisches Löschen ohne expliziten Nutzerwunsch zu riskant
    wäre, siehe Leitprinzip 2 "bei Geld/irreversiblen Aktionen nie still
    raten"). Weitere `kind`-Werte bräuchten hier jeweils ihre eigene
    Ausführung, sobald es sie gibt."""
    suggestion = get_pending_suggestion(db)
    if not suggestion:
        return None, "Gerade kein offener Vorschlag."

    if decision == "accept":
        suggestion.status = models.AssistantSuggestionStatus.accepted
        suggestion.decided_at = datetime.utcnow()
        result = f"✓ Übernommen: „{suggestion.title}“."
        if suggestion.kind == "todo_no_date" and suggestion.ref_id:
            todo = db.query(models.Todo).filter(models.Todo.id == suggestion.ref_id).first()
            if todo and not todo.done:
                todo.due_date = date.today()
                result = f"✓ „{todo.title}“ auf heute terminiert."
        elif suggestion.kind == "category_rule" and suggestion.ref_id:
            rule = db.query(models.CategoryRule).filter(models.CategoryRule.id == suggestion.ref_id).first()
            if rule:
                rule.active = True
                # Rueckwirkend auf bisher UNKATEGORISIERTE Buchungen anwenden -
                # bereits kategorisierte (auch die urspruenglich falschen, die
                # zur Korrektur gefuehrt haben) bleiben unangetastet, keine
                # stille Masse-Aenderung an bestaetigten Buchungen.
                matches = (
                    db.query(models.Transaction)
                    .filter(models.Transaction.category_id.is_(None), models.Transaction.description.isnot(None))
                    .all()
                )
                n = 0
                for t in matches:
                    if _merchant_key(t.description) == rule.pattern:
                        t.category_id = rule.category_id
                        t.categorized_at = datetime.utcnow()
                        n += 1
                result = f"✓ Regel angelegt (Muster „{rule.pattern}“) - {n} bestehende Buchung(en) direkt zugeordnet."
        db.commit()
        return suggestion, result

    if decision == "snooze":
        suggestion.status = models.AssistantSuggestionStatus.snoozed
        suggestion.snoozed_until = date.today() + timedelta(days=7)
        suggestion.decided_at = datetime.utcnow()
        db.commit()
        return suggestion, "🔁 Ok, melde mich in 7 Tagen wieder, falls dann immer noch offen."

    suggestion.status = models.AssistantSuggestionStatus.rejected
    suggestion.decided_at = datetime.utcnow()
    # Bugfix (Selbst-Review, Nacht 27./28.08.): den Regel-Entwurf hier NICHT
    # löschen - er bleibt als inaktiver "schon mal abgelehnt"-Marker stehen.
    # check_for_learnable_correction_pattern() prüft "already" ohne active-
    # Filter, findet also genau diesen Entwurf und schlägt das Muster nicht
    # erneut vor. Würde der Entwurf gelöscht (frühere Version), verlor das
    # System jede Spur der Ablehnung - beim nächsten Lauf mit weiterhin
    # erfülltem Schwellwert kam prompt ein NEUER Entwurf mit neuer ref_id
    # (create_suggestion_if_new dedupliziert nur über (kind, ref_id), eine
    # frische ref_id kann nie kollidieren) und der Nutzer wurde trotz
    # "wird nicht nochmal vorgeschlagen" erneut gefragt.
    db.commit()
    return suggestion, "Verworfen - wird nicht nochmal vorgeschlagen."


CATEGORY_RULE_LEARN_THRESHOLD = 3


def check_for_learnable_correction_pattern(db: Session) -> models.AssistantSuggestion | None:
    """"Lernen aus Korrekturen" (Spezifikation Abschnitt K) - findet ein
    (Gegenstelle, Zielkategorie)-Muster, das mindestens CATEGORY_RULE_LEARN_
    THRESHOLD-mal manuell korrigiert wurde (siehe update_transaction), für
    das es aber noch KEINE Regel und KEINEN (auch abgelehnten) Vorschlag
    gibt, legt dafür einen DRAFT models.CategoryRule an (active=False, wird
    erst bei Bestätigung scharf, siehe decide_pending_suggestion) und stellt
    ihn als AssistantSuggestion zur Bestätigung - Wiederverwendung derselben
    Vorschlags-Warteschlange wie Punkt B, kein zweites System.

    Nur EIN Muster pro Aufruf (main._scheduled_suggestion_check ruft das
    bereits nur auf, wenn kein anderer Vorschlag pending ist, siehe dort -
    "höchstens ein Vorschlag zur Zeit" gilt für JEDE Vorschlagsart)."""
    rows = (
        db.query(
            models.CategoryCorrection.merchant_key, models.CategoryCorrection.new_category_id,
            func.count().label("n"),
        )
        .group_by(models.CategoryCorrection.merchant_key, models.CategoryCorrection.new_category_id)
        .having(func.count() >= CATEGORY_RULE_LEARN_THRESHOLD)
        .all()
    )
    for merchant_key, new_category_id, n in rows:
        already = db.query(models.CategoryRule).filter_by(pattern=merchant_key, category_id=new_category_id).first()
        if already:
            continue
        category = db.query(models.Category).filter(models.Category.id == new_category_id).first()
        if not category:
            continue
        draft = models.CategoryRule(pattern=merchant_key, category_id=new_category_id, active=False)
        db.add(draft)
        db.flush()  # id verfuegbar, ohne die Suggestion-Erstellung schon zu committen
        title = f"Buchungen mit „{merchant_key}“ {n}x manuell auf „{category.name}“ korrigiert - Regel anlegen?"
        suggestion = create_suggestion_if_new(db, kind="category_rule", ref_id=draft.id, title=title)
        if suggestion:
            db.commit()
            return suggestion
        db.rollback()  # zu diesem Muster existiert schon ein (ggf. abgelehnter) Vorschlag - Entwurf verwerfen
    return None


def get_category_rules(db: Session) -> list[models.CategoryRule]:
    """Nur AKTIVE (bestätigte) Regeln - Entwürfe (active=False) sind reine
    Zwischenzustände während ein Vorschlag noch offen ist, siehe
    check_for_learnable_correction_pattern. Für die Transparenz-Ansicht in
    den Einstellungen (Spezifikation Abschnitt K: "transparent, abschaltbar")."""
    return (
        db.query(models.CategoryRule)
        .filter(models.CategoryRule.active.is_(True))
        .order_by(models.CategoryRule.created_at.desc())
        .all()
    )


def delete_category_rule(db: Session, rule_id: int) -> bool:
    rule = db.query(models.CategoryRule).filter(models.CategoryRule.id == rule_id).first()
    if not rule:
        return False
    db.delete(rule)
    db.commit()
    return True


def get_recent_suggestions(db: Session, limit: int = 20) -> list[models.AssistantSuggestion]:
    """"Was Jarvis getan hat" (Spezifikation Abschnitt J) - kein separates
    Log-System, die Vorschlags-Tabelle selbst ist die Aktivitätsspur (Status +
    Zeitstempel reichen aus, siehe models.AssistantSuggestion-Docstring)."""
    return (
        db.query(models.AssistantSuggestion)
        .order_by(models.AssistantSuggestion.created_at.desc())
        .limit(limit)
        .all()
    )


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


# ---------- Globale Suche ----------
# Bündelt die bestehenden Teil-Suchen (Belege, Notizen) und ergänzt sie um
# weitere durchsuchbare Entitäten - bewusst EIN Endpunkt statt eines eigenen
# Suchindex (SQLite FTS5 wäre für die hier übliche Datenmenge eines
# Einzelnutzers unnötiger Overhead, siehe search_receipts-Docstring). Jede
# Kategorie liefert nur wenige Treffer (limit_per_type), damit die
# Befehlspalette nicht von einer einzelnen Entität überflutet wird.
def global_search(db: Session, space_id: int, q: str, limit_per_type: int = 6) -> list[schemas.GlobalSearchResult]:
    like = f"%{q.strip()}%"
    results: list[schemas.GlobalSearchResult] = []

    txs = (
        db.query(models.Transaction)
        .join(models.Account)
        .filter(
            models.Account.space_id == space_id,
            (models.Transaction.description.ilike(like)) | (models.Transaction.notes.ilike(like)),
        )
        .order_by(models.Transaction.date.desc())
        .limit(limit_per_type)
        .all()
    )
    for t in txs:
        results.append(schemas.GlobalSearchResult(
            entity_type="transaction", id=t.id, label=t.description or "Buchung",
            sublabel=f"{t.date.isoformat()} · {t.amount:.2f} €", tab="transactions",
        ))

    goals = (
        db.query(models.Goal)
        .filter(models.Goal.title.ilike(like), (models.Goal.space_id == space_id) | (models.Goal.space_id.is_(None)))
        .limit(limit_per_type)
        .all()
    )
    for g in goals:
        results.append(schemas.GlobalSearchResult(
            entity_type="goal", id=g.id, label=g.title,
            sublabel=g.category, tab="schweiz" if (g.category or "").lower().startswith("schweiz") else "goals",
        ))

    projects = db.query(models.BusinessProject).filter(models.BusinessProject.name.ilike(like)).limit(limit_per_type).all()
    for p in projects:
        results.append(schemas.GlobalSearchResult(entity_type="business_project", id=p.id, label=p.name, tab="projects"))

    contacts = (
        db.query(models.Contact)
        .filter((models.Contact.name.ilike(like)) | (models.Contact.notes.ilike(like)))
        .limit(limit_per_type)
        .all()
    )
    for c in contacts:
        results.append(schemas.GlobalSearchResult(entity_type="contact", id=c.id, label=c.name, sublabel=c.notes, tab="life"))

    media = db.query(models.MediaItem).filter(models.MediaItem.title.ilike(like)).limit(limit_per_type).all()
    for m in media:
        results.append(schemas.GlobalSearchResult(
            entity_type="media", id=m.id, label=m.title, sublabel=m.media_type, tab="life",
        ))

    notes = search_notes(db, q, limit=limit_per_type)
    for n in notes:
        results.append(schemas.GlobalSearchResult(
            entity_type="note", id=n.id, label=n.text[:80], sublabel="Notiz",
            tab=NOTE_ENTITY_JUMP_TAB.get(n.entity_type, "hub"),
        ))

    receipts = search_receipts(db, space_id, q, limit=limit_per_type)
    for r in receipts:
        results.append(schemas.GlobalSearchResult(
            entity_type="receipt", id=r.id, label=r.description or "Beleg",
            sublabel=f"Beleg · {r.date.isoformat()}", tab="transactions",
        ))

    return results


# Muss zur Frontend-Konstante NOTE_ENTITY_JUMP in frontend/js/notizen.js
# passen - dort steht dieselbe Zuordnung fürs manuelle Notizen-Modal, hier
# für die Suchergebnisse.
NOTE_ENTITY_JUMP_TAB = {
    "goal": "goals", "todo": "goals", "business_project": "projects", "life_area": "life", "schweiz": "schweiz",
}
