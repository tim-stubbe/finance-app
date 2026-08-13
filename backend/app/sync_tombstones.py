"""Generisches Lösch-Protokoll für den Offline-Sync des nativen macOS-Clients.

Fast alle Löschungen in dieser App sind Hard Deletes (siehe crud.py: 21+
delete_*-Funktionen plus diverse db.delete()-Aufrufe, keine Tombstones). Ohne
ein Protokoll wäre eine Löschung für einen zweiten Client zwischen zwei
Sync-Läufen unsichtbar. Statt jede dieser Stellen einzeln anzufassen, hängt
sich dieses Modul per SQLAlchemy-Session-Event global ein - das deckt jede
zukünftige Löschung automatisch mit ab, ohne dass crud.py etwas davon weiß.

Wird per Seiteneffekt-Import in main.py aktiviert (registriert die Listener
beim Import, kein expliziter Aufruf nötig)."""

from datetime import datetime
from sqlalchemy import event
from sqlalchemy.orm import Session
from . import models

# Welche Entitäten tombstoned werden - deckungsgleich mit sync_registry.py,
# hier bewusst als eigene Liste gehalten statt von dort importiert, damit
# dieses Modul (frueh beim App-Start aktiv) nicht von der groesseren Registry
# abhaengt.
TOMBSTONE_ENTITY_TYPES = {
    "Space", "Account", "Category", "Budget", "Trip", "Holding", "HoldingLot",
    "Transaction", "Debt", "DebtPayment", "Goal", "GoalTrigger", "GoalProgress",
    "AlertRule", "Todo", "CalendarEvent", "ContractReminder", "ReturnDeadline",
    "NetWorthSnapshot", "BusinessProject", "BusinessIssue", "LifeArea",
    "LifeCheckIn", "WishlistItem", "AccountBalanceLog", "CreditCardBill",
}

# Kind-Tabellen ohne eigene space_id-Spalte - space_id wird ueber die
# Parent-Relationship aufgeloest (muss VOR dem Flush passieren, siehe unten -
# bei Kaskaden-Loeschungen kann die Relationship danach bereits expired sein).
# Zweiter Wert None = der Parent selbst ist global (kein space_id), dann
# bleibt space_id auf dem Tombstone ebenfalls NULL.
#
# Bekannte Lücke (Phase 1, siehe Plan): ReturnDeadline (zwei Hops über
# Transaction->Account) sowie AccountBalanceLog/CreditCardBill (eines von
# account_id/debt_id gesetzt) bekommen space_id=NULL auf dem Tombstone. Das
# ist ein reines Anzeige-/Filter-Detail, kein Korrektheitsproblem der
# Löschung selbst - die App ist in der Praxis Single-Space (siehe auth.py),
# ein Client ohne mehrere Spaces ignoriert space_id ohnehin.
_PARENT_ATTR = {
    "HoldingLot": ("holding", "space_id"),
    "DebtPayment": ("debt", "space_id"),
    "GoalTrigger": ("goal", "space_id"),
    "GoalProgress": ("goal", "space_id"),
    "Transaction": ("account", "space_id"),
    "BusinessIssue": ("project", None),
    "LifeCheckIn": ("area", None),
}


def _resolve_space_id(obj):
    if hasattr(obj, "space_id"):
        return obj.space_id
    parent_attr, parent_space_attr = _PARENT_ATTR.get(type(obj).__name__, (None, None))
    if parent_attr and parent_space_attr:
        parent = getattr(obj, parent_attr, None)
        return getattr(parent, parent_space_attr, None) if parent else None
    return None


@event.listens_for(Session, "before_flush")
def _capture_tombstones(session, flush_context, instances):
    """Erfasst die zu loeschenden Objekte VOR dem Flush - zu diesem Zeitpunkt
    sind kaskadierte Kind-Objekte (cascade="all, delete-orphan") bereits in
    session.deleted (SQLAlchemy cascadet beim session.delete()-Aufruf sofort,
    nicht erst beim Flush) und ihre Parent-Relationships noch vollstaendig
    geladen/nicht expired."""
    pending = []
    for obj in session.deleted:
        entity_type = type(obj).__name__
        if entity_type not in TOMBSTONE_ENTITY_TYPES:
            continue
        pending.append({
            "entity_type": entity_type,
            "entity_id": obj.id,
            "space_id": _resolve_space_id(obj),
        })
    if pending:
        session.info.setdefault("_pending_tombstones", []).extend(pending)


@event.listens_for(Session, "after_flush")
def _write_tombstones(session, flush_context):
    """Schreibt die in before_flush gesammelten Tombstones - erst hier statt
    direkt in before_flush, weil session.add() waehrend before_flush selbst
    noch am laufenden Flush-Plan teilnehmen wuerde; after_flush ist der von
    SQLAlchemy vorgesehene Ort fuer genau dieses Audit-Trail-Muster."""
    pending = session.info.pop("_pending_tombstones", None)
    if not pending:
        return
    now = datetime.utcnow()
    for item in pending:
        session.add(models.SyncTombstone(
            entity_type=item["entity_type"], entity_id=item["entity_id"],
            space_id=item["space_id"], deleted_at=now,
        ))
