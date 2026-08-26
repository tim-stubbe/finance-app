"""Ziele (Goals, inkl. automatischer Finanz-Trigger) - vierter Schritt der
crud.py-Modularisierung (siehe ROADMAP.md), analog zu crud_connections.py.
Reine Verschiebung ohne Verhaltensänderung.

crud.py importiert alle hier definierten Namen zurück (get_goals wird z.B.
vom KI-Assistent-Belege-Check innerhalb von crud.py selbst gebraucht),
damit jeder bestehende `crud.get_goals(...)`-Aufrufstil in main.py/
routers/ unverändert weiterfunktioniert."""

from datetime import datetime

from sqlalchemy.orm import Session

from . import models, schemas


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

