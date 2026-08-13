"""Entity-Registry für den Offline-Sync des nativen macOS-Clients (siehe
sync.py). Bündelt pro synchronisierbarer Tabelle, was Pull/Push brauchen:

- `model`: fürs Pull-Serialisieren. Pull fragt direkt per `db.query(model)` ab
  (nicht über die uneinheitlich signaturierten `crud.get_*`-Funktionen) und
  serialisiert über die reinen Tabellenspalten (sync._serialize_row), NICHT
  über die bestehenden `schemas.*Out`-Klassen - die sind fast durchgängig
  angereicherte UI-Projektionen (z.B. BudgetOut.category_name,
  TripOut.total_spent, DebtOut.paid_off_percent), keine 1:1-Abbildung der
  Tabelle, und wären als Sync-Payload sowohl unvollständig (fehlende rohe FKs)
  als auch unnötig teuer (Berechnungen, die ein Offline-Client so nicht
  braucht - er kennt die referenzierten Objekte ja selbst lokal).
- `create_fn`/`update_fn`/`delete_fn`: fürs Push-Anwenden. crud.py hat für
  jede Entität eine ANDERE Signatur gewachsen (manche nehmen ein
  `schemas.XCreate`-Objekt, manche einzelne Positionsargumente; manche
  `update_x(db, id, space_id, data)`, andere `update_x(db, <bereits gefetchtes
  Objekt>, data)`) - diese Adapter normalisieren das auf eine einheitliche
  Form (db, space_id, data: dict) -> Objekt, indem sie die jeweils passende
  crud.py-Funktion mit den richtigen Feldern aufrufen, GENAU wie es die
  entsprechenden main.py-REST-Endpunkte auch tun (keine neue Business-Logik,
  nur Verdrahtung).

Bewusst NICHT alle 34 Modelle: Verbindungs-Tabellen mit verschlüsselten
Zugangsdaten (BankConnection, BitvavoConnection, PayPalConnection,
EnableBankingConnection, EbayConnection) sind ausgeschlossen - ein Offline-
Client soll keine Kopie von Bank-/Broker-Credentials im lokalen Speicher
halten. Ebenso ausgeschlossen: reine Caches/interne Dedupe-Tabellen
(PriceHistoryCache, NotifiedAnomaly, MailAttachment, ImmichQualityFlag,
BasiszinsRate) und Settings (Singleton mit Secrets, nicht pro-Client-Daten).

Manche Entitäten sind bewusst PULL-ONLY (kein create_fn/update_fn/delete_fn):
- Space, NetWorthSnapshot, AccountBalanceLog, CreditCardBill, GoalProgress:
  werden nicht direkt vom Nutzer angelegt/bearbeitet (System-generiert bzw.
  seltene Einrichtung), ein Offline-Client braucht sie nur lesend.
- GoalTrigger: 1:1-Teil von Goal, wird nur über create_goal/update_goal
  mitgeschrieben (siehe crud._apply_trigger), keine eigene crud-Funktion.

Manche Entitäten haben kein delete_fn, weil die App dafür bewusst
Soft-Delete über ein `active`/Status-Feld statt Hard-Delete verwendet
(BusinessProject, LifeArea, WishlistItem: `active=False` per Update;
BusinessIssue: `resolved=True` per Update) - eine Löschung über den Sync ist
für diese Entitäten schlicht ein normaler Update-Push, kein eigener
Delete-Op. LifeCheckIn ist bewusst nur create (Tagebuch-Eintrag, kein
bearbeitbarer/löschbarer Zustand, siehe models.LifeCheckIn-Docstring)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from sqlalchemy.orm import Session

from . import models, schemas, crud


@dataclass
class SyncEntity:
    model: type
    space_scoped: bool
    # Reihenfolge-Abhängigkeit fürs Push (Parent zuerst) - Name der Entität
    # im Registry-dict, nicht die Spalte selbst.
    depends_on: Optional[str] = None
    create_fn: Optional[Callable] = None
    update_fn: Optional[Callable] = None
    delete_fn: Optional[Callable] = None


def _get_or_404(db, model, entity_id, name):
    obj = db.query(model).filter(model.id == entity_id).first()
    if not obj:
        raise ValueError(f"{name} {entity_id} nicht gefunden")
    return obj


# ---------- Adapter: normalisieren crud.py-Aufrufe auf (db, space_id, data) ----------

def _create_account(db, space_id, data):
    return crud.create_account(db, schemas.AccountCreate(**data), space_id)


def _update_account(db, space_id, entity_id, data):
    return crud.update_account(db, entity_id, space_id, schemas.AccountUpdate(**data))


def _delete_account(db, space_id, entity_id):
    crud.delete_account(db, entity_id, space_id)


def _create_category(db, space_id, data):
    return crud.create_category(db, schemas.CategoryCreate(**data))


def _update_category(db, space_id, entity_id, data):
    return crud.update_category(db, entity_id, schemas.CategoryUpdate(**data))


def _delete_category(db, space_id, entity_id):
    crud.delete_category(db, entity_id)


def _create_budget(db, space_id, data):
    return crud.upsert_budget(db, space_id, schemas.BudgetCreate(**data))


def _update_budget(db, space_id, entity_id, data):
    # Budget hat keine eigene ID im Sinn des Nutzers (UniqueConstraint auf
    # space_id+category_id) - entity_id ist hier die category_id, upsert
    # deckt Create UND Update gleichermaßen ab (siehe crud.upsert_budget).
    return crud.upsert_budget(db, space_id, schemas.BudgetCreate(**data))


def _delete_budget(db, space_id, entity_id):
    crud.delete_budget(db, space_id, entity_id)


def _create_trip(db, space_id, data):
    return crud.create_trip(db, schemas.TripCreate(**data), space_id)


def _update_trip(db, space_id, entity_id, data):
    return crud.update_trip(db, entity_id, space_id, schemas.TripUpdate(**data))


def _delete_trip(db, space_id, entity_id):
    crud.delete_trip(db, entity_id, space_id)


def _create_holding(db, space_id, data):
    return crud.create_holding(db, schemas.HoldingCreate(**data), space_id)


def _update_holding(db, space_id, entity_id, data):
    return crud.update_holding(db, entity_id, space_id, schemas.HoldingUpdate(**data))


def _delete_holding(db, space_id, entity_id):
    crud.delete_holding(db, entity_id, space_id)


def _create_holding_lot(db, space_id, data):
    holding_id = data["holding_id"]
    return crud.create_lot(db, holding_id, space_id, schemas.HoldingLotCreate(**data))


def _update_holding_lot(db, space_id, entity_id, data):
    holding_id = data["holding_id"]
    return crud.update_lot(db, entity_id, holding_id, space_id, schemas.HoldingLotUpdate(**data))


def _delete_holding_lot(db, space_id, entity_id):
    lot = _get_or_404(db, models.HoldingLot, entity_id, "HoldingLot")
    crud.delete_lot(db, entity_id, lot.holding_id, space_id)


def _create_transaction(db, space_id, data):
    return crud.create_transaction(db, schemas.TransactionCreate(**data))


def _update_transaction(db, space_id, entity_id, data):
    return crud.update_transaction(db, entity_id, space_id, schemas.TransactionUpdate(**data))


def _delete_transaction(db, space_id, entity_id):
    crud.delete_transaction(db, entity_id, space_id)


def _create_debt(db, space_id, data):
    return crud.create_debt(db, schemas.DebtCreate(**data), space_id)


def _update_debt(db, space_id, entity_id, data):
    return crud.update_debt(db, entity_id, space_id, schemas.DebtUpdate(**data))


def _delete_debt(db, space_id, entity_id):
    crud.delete_debt(db, entity_id, space_id)


def _create_debt_payment(db, space_id, data):
    debt_id = data["debt_id"]
    return crud.create_debt_payment(db, debt_id, space_id, schemas.DebtPaymentCreate(**data))


def _update_debt_payment(db, space_id, entity_id, data):
    debt_id = data["debt_id"]
    return crud.update_debt_payment(db, entity_id, debt_id, space_id, schemas.DebtPaymentUpdate(**data))


def _delete_debt_payment(db, space_id, entity_id):
    payment = _get_or_404(db, models.DebtPayment, entity_id, "DebtPayment")
    crud.delete_debt_payment(db, entity_id, payment.debt_id, space_id)


def _create_goal(db, space_id, data):
    return crud.create_goal(db, schemas.GoalCreate(**data), space_id)


def _update_goal(db, space_id, entity_id, data):
    return crud.update_goal(db, entity_id, space_id, schemas.GoalUpdate(**data))


def _delete_goal(db, space_id, entity_id):
    crud.delete_goal(db, entity_id, space_id)


def _create_alert_rule(db, space_id, data):
    return crud.create_alert_rule(db, space_id, schemas.AlertRuleCreate(**data))


def _update_alert_rule(db, space_id, entity_id, data):
    rule = _get_or_404(db, models.AlertRule, entity_id, "AlertRule")
    return crud.update_alert_rule(db, rule, schemas.AlertRuleUpdate(**data))


def _delete_alert_rule(db, space_id, entity_id):
    rule = _get_or_404(db, models.AlertRule, entity_id, "AlertRule")
    crud.delete_alert_rule(db, rule)


def _create_todo(db, space_id, data):
    c = schemas.TodoCreate(**data)
    return crud.create_todo(db, c.title, c.due_date)


def _update_todo(db, space_id, entity_id, data):
    todo = _get_or_404(db, models.Todo, entity_id, "Todo")
    u = schemas.TodoUpdate(**data)
    return crud.update_todo(db, todo, u.title, u.done, u.due_date)


def _delete_todo(db, space_id, entity_id):
    todo = _get_or_404(db, models.Todo, entity_id, "Todo")
    crud.delete_todo(db, todo)


def _create_calendar_event(db, space_id, data):
    c = schemas.CalendarEventCreate(**data)
    return crud.create_calendar_event(db, c.title, c.start, c.end, c.location, c.all_day, c.calendar_url)


def _update_calendar_event(db, space_id, entity_id, data):
    event = _get_or_404(db, models.CalendarEvent, entity_id, "CalendarEvent")
    u = schemas.CalendarEventUpdate(**data)
    return crud.update_calendar_event(db, event, u.title, u.start, u.end, u.location, u.all_day)


def _delete_calendar_event(db, space_id, entity_id):
    event = _get_or_404(db, models.CalendarEvent, entity_id, "CalendarEvent")
    crud.delete_calendar_event(db, event)


def _create_contract_reminder(db, space_id, data):
    return crud.create_contract_reminder(db, space_id, schemas.ContractReminderCreate(**data))


def _update_contract_reminder(db, space_id, entity_id, data):
    return crud.update_contract_reminder(db, entity_id, space_id, schemas.ContractReminderUpdate(**data))


def _delete_contract_reminder(db, space_id, entity_id):
    crud.delete_contract_reminder(db, entity_id, space_id)


def _create_return_deadline(db, space_id, data):
    return crud.create_return_deadline(db, space_id, schemas.ReturnDeadlineCreate(**data))


def _update_return_deadline(db, space_id, entity_id, data):
    return crud.update_return_deadline(db, entity_id, space_id, schemas.ReturnDeadlineUpdate(**data))


def _delete_return_deadline(db, space_id, entity_id):
    crud.delete_return_deadline(db, entity_id, space_id)


def _create_business_project(db, space_id, data):
    return crud.create_business_project(db, schemas.BusinessProjectCreate(**data))


def _update_business_project(db, space_id, entity_id, data):
    project = _get_or_404(db, models.BusinessProject, entity_id, "BusinessProject")
    return crud.update_business_project(db, project, schemas.BusinessProjectUpdate(**data))


def _create_business_issue(db, space_id, data):
    c = schemas.BusinessIssueCreate(**data)
    return crud.create_business_issue(db, c.project_id, c.title, c.notes)


def _update_business_issue(db, space_id, entity_id, data):
    # Kein generisches Update - Issues werden nur ab-/wieder aufgehakt.
    issue = _get_or_404(db, models.BusinessIssue, entity_id, "BusinessIssue")
    if data.get("resolved"):
        return crud.resolve_business_issue(db, issue)
    raise ValueError("BusinessIssue unterstützt nur resolved=true per Sync-Update")


def _create_life_area(db, space_id, data):
    return crud.create_life_area(db, schemas.LifeAreaCreate(**data))


def _update_life_area(db, space_id, entity_id, data):
    area = _get_or_404(db, models.LifeArea, entity_id, "LifeArea")
    return crud.update_life_area(db, area, schemas.LifeAreaUpdate(**data))


def _create_life_checkin(db, space_id, data):
    c = schemas.LifeCheckInCreate(**data)
    return crud.create_life_checkin(db, c.area_id, c.note, c.progress_percent)


def _create_wishlist_item(db, space_id, data):
    return crud.create_wishlist_item(db, schemas.WishlistItemCreate(**data))


def _update_wishlist_item(db, space_id, entity_id, data):
    item = _get_or_404(db, models.WishlistItem, entity_id, "WishlistItem")
    return crud.update_wishlist_item(db, item, schemas.WishlistItemUpdate(**data))


SYNC_REGISTRY: dict[str, SyncEntity] = {
    "Space": SyncEntity(models.Space, space_scoped=False),
    "Account": SyncEntity(
        models.Account, space_scoped=True,
        create_fn=_create_account, update_fn=_update_account, delete_fn=_delete_account,
    ),
    "Category": SyncEntity(
        models.Category, space_scoped=False,
        create_fn=_create_category, update_fn=_update_category, delete_fn=_delete_category,
    ),
    "Budget": SyncEntity(
        models.Budget, space_scoped=True,
        create_fn=_create_budget, update_fn=_update_budget, delete_fn=_delete_budget,
    ),
    "Trip": SyncEntity(
        models.Trip, space_scoped=True,
        create_fn=_create_trip, update_fn=_update_trip, delete_fn=_delete_trip,
    ),
    "Holding": SyncEntity(
        models.Holding, space_scoped=True,
        create_fn=_create_holding, update_fn=_update_holding, delete_fn=_delete_holding,
    ),
    "HoldingLot": SyncEntity(
        models.HoldingLot, space_scoped=True, depends_on="Holding",
        create_fn=_create_holding_lot, update_fn=_update_holding_lot, delete_fn=_delete_holding_lot,
    ),
    "Transaction": SyncEntity(
        models.Transaction, space_scoped=True, depends_on="Account",
        create_fn=_create_transaction, update_fn=_update_transaction, delete_fn=_delete_transaction,
    ),
    "Debt": SyncEntity(
        models.Debt, space_scoped=True,
        create_fn=_create_debt, update_fn=_update_debt, delete_fn=_delete_debt,
    ),
    "DebtPayment": SyncEntity(
        models.DebtPayment, space_scoped=True, depends_on="Debt",
        create_fn=_create_debt_payment, update_fn=_update_debt_payment, delete_fn=_delete_debt_payment,
    ),
    "Goal": SyncEntity(
        models.Goal, space_scoped=True,
        create_fn=_create_goal, update_fn=_update_goal, delete_fn=_delete_goal,
    ),
    "GoalTrigger": SyncEntity(models.GoalTrigger, space_scoped=False),
    "GoalProgress": SyncEntity(models.GoalProgress, space_scoped=False),
    "AlertRule": SyncEntity(
        models.AlertRule, space_scoped=True,
        create_fn=_create_alert_rule, update_fn=_update_alert_rule, delete_fn=_delete_alert_rule,
    ),
    "Todo": SyncEntity(
        models.Todo, space_scoped=False,
        create_fn=_create_todo, update_fn=_update_todo, delete_fn=_delete_todo,
    ),
    "CalendarEvent": SyncEntity(
        models.CalendarEvent, space_scoped=False,
        create_fn=_create_calendar_event, update_fn=_update_calendar_event, delete_fn=_delete_calendar_event,
    ),
    "ContractReminder": SyncEntity(
        models.ContractReminder, space_scoped=True, depends_on="Account",
        create_fn=_create_contract_reminder, update_fn=_update_contract_reminder, delete_fn=_delete_contract_reminder,
    ),
    "ReturnDeadline": SyncEntity(
        models.ReturnDeadline, space_scoped=True, depends_on="Transaction",
        create_fn=_create_return_deadline, update_fn=_update_return_deadline, delete_fn=_delete_return_deadline,
    ),
    "NetWorthSnapshot": SyncEntity(models.NetWorthSnapshot, space_scoped=True),
    "BusinessProject": SyncEntity(
        models.BusinessProject, space_scoped=False,
        create_fn=_create_business_project, update_fn=_update_business_project,
    ),
    "BusinessIssue": SyncEntity(
        models.BusinessIssue, space_scoped=False, depends_on="BusinessProject",
        create_fn=_create_business_issue, update_fn=_update_business_issue,
    ),
    "LifeArea": SyncEntity(
        models.LifeArea, space_scoped=False,
        create_fn=_create_life_area, update_fn=_update_life_area,
    ),
    "LifeCheckIn": SyncEntity(
        models.LifeCheckIn, space_scoped=False, depends_on="LifeArea",
        create_fn=_create_life_checkin,
    ),
    "WishlistItem": SyncEntity(
        models.WishlistItem, space_scoped=False,
        create_fn=_create_wishlist_item, update_fn=_update_wishlist_item,
    ),
    "AccountBalanceLog": SyncEntity(models.AccountBalanceLog, space_scoped=False),
    "CreditCardBill": SyncEntity(models.CreditCardBill, space_scoped=False),
}
