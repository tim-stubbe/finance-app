"""Auswertung von Zielen ("Ziele"-Modul).

Automatisch messbare Ziele (`auto_financial`) werden gegen bestehende Kennzahlen
der App gerechnet - Vermögen, Kontostand, Depotwert, Sparrate, Kategoriesumme.
Die Berechnung passiert live beim Abruf (wie net_worth/budget_progress auch),
zusätzlich schreibt der tägliche Job in main.py Verlaufspunkte für den Graphen.

Manuelle Meilensteine (`manual`) haben keine Trigger und werden nur vom Nutzer
abgehakt - hier steckt bewusst keine Logik, damit später auch nicht-finanzielle
Lebensbereiche ohne Schemaänderung darüber laufen können.
"""

from datetime import date, datetime
from typing import NamedTuple, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models, crud


class MetricResult(NamedTuple):
    value: Optional[float]
    # "eur" oder "months" - bestimmt, wie das Frontend den Wert formatiert.
    unit: str
    # Schwelle/Vergleich, gegen die der Fortschritt gerechnet wird. Weicht bei
    # savings_rate von der Trigger-Schwelle ab (dort zählt die Monatsserie).
    threshold: float
    comparison: models.GoalComparison
    label: str
    error: Optional[str]


ASSET_TYPE_LABELS = {
    "aktie": "Aktien",
    "etf": "ETFs",
    "anleihe": "Anleihen",
    "krypto": "Krypto",
    "sonstiges": "Sonstiges",
}


def space_ids_for_goal(db: Session, goal: models.Goal) -> list[int]:
    """Ein Ziel ohne space_id gilt bereichsübergreifend - dessen Metriken werden
    dann über alle Bereiche summiert."""
    if goal.space_id is not None:
        return [goal.space_id]
    return [s.id for s in crud.get_spaces(db)]


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def _prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _net_for_month(db: Session, space_ids: list[int], year: int, month: int) -> float:
    start, end = _month_bounds(year, month)
    total = (
        db.query(func.coalesce(func.sum(models.Transaction.amount), 0.0))
        .join(models.Account)
        .filter(
            models.Account.space_id.in_(space_ids),
            models.Transaction.date >= start,
            models.Transaction.date < end,
        )
        .scalar()
    )
    return round(total or 0.0, 2)


def _savings_streak(db: Session, space_ids: list[int], threshold: float,
                    comparison: models.GoalComparison, window: int) -> int:
    """Zählt, wie viele *abgeschlossene* Monate in Folge (rückwärts ab dem letzten
    vollen Monat) die Netto-Sparrate die Schwelle erfüllt. Der laufende Monat wird
    ausgelassen, weil er noch unvollständig ist und die Serie sonst ständig reißt."""
    today = date.today()
    year, month = _prev_month(today.year, today.month)
    streak = 0
    # Höchstens bis zum Fenster zählen - mehr braucht die Fortschrittsanzeige nicht.
    for _ in range(window):
        net = _net_for_month(db, space_ids, year, month)
        ok = net >= threshold if comparison == models.GoalComparison.gte else net <= threshold
        if not ok:
            break
        streak += 1
        year, month = _prev_month(year, month)
    return streak


def evaluate_metric(db: Session, goal: models.Goal) -> MetricResult:
    trigger = goal.trigger
    if trigger is None:
        return MetricResult(None, "eur", 0.0, models.GoalComparison.gte, "", "Keine Auswertungsregel hinterlegt")

    space_ids = space_ids_for_goal(db, goal)
    scope_note = "" if goal.space_id is not None else " (alle Bereiche)"
    metric = trigger.metric_type

    if metric == models.GoalMetricType.net_worth:
        value = round(sum(crud.net_worth(db, sid).total for sid in space_ids), 2)
        return MetricResult(value, "eur", trigger.threshold_value, trigger.comparison,
                            f"Gesamtvermögen{scope_note}", None)

    if metric == models.GoalMetricType.account_balance:
        account = db.query(models.Account).filter(models.Account.id == trigger.scope_account_id).first()
        if not account or account.space_id not in space_ids:
            return MetricResult(None, "eur", trigger.threshold_value, trigger.comparison,
                                "Kontostand", "Das hinterlegte Konto existiert nicht mehr")
        return MetricResult(crud.account_balance(db, account), "eur", trigger.threshold_value,
                            trigger.comparison, f"Kontostand: {account.name}", None)

    if metric == models.GoalMetricType.investment_value:
        total = 0.0
        for sid in space_ids:
            for h in crud.get_holdings(db, sid):
                if trigger.scope_asset_type and h.asset_type != trigger.scope_asset_type:
                    continue
                price = h.current_price if h.current_price is not None else h.purchase_price
                total += h.quantity * price
        asset_label = ASSET_TYPE_LABELS.get(
            trigger.scope_asset_type.value if trigger.scope_asset_type else "", "alle Anlageklassen"
        )
        return MetricResult(round(total, 2), "eur", trigger.threshold_value, trigger.comparison,
                            f"Depotwert: {asset_label}{scope_note}", None)

    if metric == models.GoalMetricType.debt_balance:
        debt = db.query(models.Debt).filter(models.Debt.id == trigger.scope_debt_id).first()
        if not debt or debt.space_id not in space_ids:
            return MetricResult(None, "eur", trigger.threshold_value, trigger.comparison,
                                "Restschuld", "Der hinterlegte Kredit existiert nicht mehr")
        return MetricResult(max(0.0, debt.current_balance), "eur", trigger.threshold_value,
                            trigger.comparison, f"Restschuld: {debt.name}", None)

    if metric == models.GoalMetricType.savings_rate:
        window = trigger.evaluation_window_months or 1
        streak = _savings_streak(db, space_ids, trigger.threshold_value, trigger.comparison, window)
        direction = "mind." if trigger.comparison == models.GoalComparison.gte else "höchstens"
        return MetricResult(
            float(streak), "months", float(window), models.GoalComparison.gte,
            f"Monate in Folge mit {direction} {trigger.threshold_value:.0f} € Sparrate{scope_note}", None,
        )

    if metric == models.GoalMetricType.custom_category_sum:
        category = crud.get_category(db, trigger.scope_category_id) if trigger.scope_category_id else None
        if not category:
            return MetricResult(None, "eur", trigger.threshold_value, trigger.comparison,
                                "Kategoriesumme", "Die hinterlegte Kategorie existiert nicht mehr")
        query = (
            db.query(func.coalesce(func.sum(func.abs(models.Transaction.amount)), 0.0))
            .join(models.Account)
            .filter(
                models.Account.space_id.in_(space_ids),
                models.Transaction.category_id == category.id,
            )
        )
        window_note = ""
        if trigger.evaluation_window_months:
            today = date.today()
            year, month = today.year, today.month
            for _ in range(trigger.evaluation_window_months - 1):
                year, month = _prev_month(year, month)
            query = query.filter(models.Transaction.date >= date(year, month, 1))
            window_note = f", letzte {trigger.evaluation_window_months} Monate"
        value = round(query.scalar() or 0.0, 2)
        return MetricResult(value, "eur", trigger.threshold_value, trigger.comparison,
                            f"Summe Kategorie „{category.name}“{window_note}{scope_note}", None)

    return MetricResult(None, "eur", trigger.threshold_value, trigger.comparison, "",
                        f"Unbekannte Metrik: {metric}")



def is_reached(value: float, threshold: float, comparison: models.GoalComparison) -> bool:
    if comparison == models.GoalComparison.gte:
        return value >= threshold
    return value <= threshold


def progress_percent(value: float, threshold: float, comparison: models.GoalComparison) -> float:
    """0-100. Bei "höchstens"-Zielen ist das notgedrungen eine Heuristik: ohne
    bekannten Startwert wird das Verhältnis Ziel/Ist als Annäherung genutzt."""
    if is_reached(value, threshold, comparison):
        return 100.0
    if comparison == models.GoalComparison.gte:
        if threshold <= 0:
            return 0.0
        return max(0.0, min(100.0, round(value / threshold * 100, 1)))
    if value <= 0 or threshold <= 0:
        return 0.0
    return max(0.0, min(100.0, round(threshold / value * 100, 1)))



def evaluate_goal(db: Session, goal: models.Goal) -> MetricResult:
    """Wertet ein Ziel aus und hakt es bei Erreichen automatisch ab.
    Committet nicht - das übernimmt der Aufrufer."""
    result = evaluate_metric(db, goal)
    if result.value is None or goal.status != models.GoalStatus.open:
        return result
    if is_reached(result.value, result.threshold, result.comparison):
        goal.status = models.GoalStatus.completed
        goal.completed_at = datetime.utcnow()
        goal.completion_seen = False
    return result



def record_progress_snapshot(db: Session, goal: models.Goal, value: float) -> None:
    db.add(models.GoalProgress(goal_id=goal.id, timestamp=datetime.utcnow(), current_value=value))
