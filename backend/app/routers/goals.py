"""Ziel-Endpunkte (Konten/Buchungen-Auswertung, Meilensteine, Fortschritt).

Vierter Schritt der Code-Modularisierung (siehe ROADMAP.md), nach
routers/investments.py, routers/tax_endpoints.py und routers/debts.py. Reine
Verschiebung ohne Verhaltensänderung. `app/goals.py` (Auswertungslogik für
automatisch messbare Ziele) bleibt unverändert und wird hier importiert -
`app.goals` und `app.routers.goals` sind unterschiedliche Modulpfade, keine
Kollision.

`goal_out` ist hier bewusst OHNE führenden Unterstrich (anders als die
anderen internen `_x_out`-Helfer in den übrigen Routern) - main.py braucht
sie weiterhin für die Ziele-Auswertung im `/today`-Endpunkt (Hub-Fokus-View),
ist also kein rein modul-internes Detail mehr."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, crud, auth, goals
from ..database import get_db

goals_router = APIRouter(prefix="/api")


def goal_out(db: Session, goal: models.Goal, evaluate: bool = True) -> schemas.GoalOut:
    """Baut die Ausgabe eines Ziels und rechnet bei auto_financial den Stand live
    (analog net_worth/budget_progress) - so ist der Fortschritt sofort aktuell und
    nicht erst nach dem nächtlichen Job."""
    out = schemas.GoalOut.model_validate(goal)
    out.predecessor_title = goal.predecessor.title if goal.predecessor else None
    if goal.goal_type != models.GoalType.auto_financial or not goal.trigger:
        return out

    result = goals.evaluate_goal(db, goal) if evaluate else goals.evaluate_metric(db, goal)
    out.status = goal.status
    out.completed_at = goal.completed_at
    out.completion_seen = goal.completion_seen
    out.metric_label = result.label
    out.value_unit = result.unit
    out.target_value = result.threshold
    out.evaluation_error = result.error
    if result.value is not None:
        out.current_value = result.value
        out.progress_percent = goals.progress_percent(result.value, result.threshold, result.comparison)
    return out


@goals_router.get("/goals", response_model=List[schemas.GoalOut])
def list_goals(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    result = [goal_out(db, g) for g in crud.get_goals(db, space_id)]
    db.commit()  # evtl. automatisch erreichte Ziele festschreiben
    return result


@goals_router.post("/goals", response_model=schemas.GoalOut)
def create_goal(data: schemas.GoalCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if data.goal_type == models.GoalType.auto_financial and data.trigger is None:
        raise HTTPException(400, "Für ein automatisch messbares Ziel wird eine Auswertungsregel benötigt")
    if data.predecessor_goal_id and not crud.get_goal(db, data.predecessor_goal_id, space_id):
        raise HTTPException(400, "Das gewählte Vorgänger-Ziel existiert nicht")
    goal = crud.create_goal(db, data, space_id)
    out = goal_out(db, goal)
    db.commit()
    return out


@goals_router.put("/goals/{goal_id}", response_model=schemas.GoalOut)
def update_goal(goal_id: int, data: schemas.GoalUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if data.predecessor_goal_id:
        if data.predecessor_goal_id == goal_id:
            raise HTTPException(400, "Ein Ziel kann nicht sein eigener Vorgänger sein")
        if not crud.get_goal(db, data.predecessor_goal_id, space_id):
            raise HTTPException(400, "Das gewählte Vorgänger-Ziel existiert nicht")
    goal = crud.update_goal(db, goal_id, space_id, data)
    if not goal:
        raise HTTPException(404, "Ziel nicht gefunden")
    out = goal_out(db, goal)
    db.commit()
    return out


@goals_router.delete("/goals/{goal_id}")
def delete_goal(goal_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not crud.delete_goal(db, goal_id, space_id):
        raise HTTPException(404, "Ziel nicht gefunden")
    return {"ok": True}


@goals_router.post("/goals/{goal_id}/complete", response_model=schemas.GoalCompleteResult)
def complete_goal(goal_id: int, completed: bool = True, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    goal = crud.get_goal(db, goal_id, space_id)
    if not goal:
        raise HTTPException(404, "Ziel nicht gefunden")
    if goal.goal_type == models.GoalType.auto_financial:
        raise HTTPException(400, "Automatisch messbare Ziele werden nicht von Hand abgehakt")
    crud.set_goal_completed(db, goal, completed)
    return schemas.GoalCompleteResult(
        ok=True,
        goal=goal_out(db, goal, evaluate=False),
        message="Ziel abgehakt." if completed else "Ziel wieder geöffnet.",
    )


@goals_router.post("/goals/mark-seen")
def mark_goals_seen(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return {"ok": True, "marked": crud.mark_goals_seen(db, space_id)}


@goals_router.get("/goals/{goal_id}/progress", response_model=List[schemas.GoalProgressPoint])
def goal_progress(goal_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not crud.get_goal(db, goal_id, space_id):
        raise HTTPException(404, "Ziel nicht gefunden")
    return crud.get_goal_progress_points(db, goal_id)
