"""Budgets (Kategorie-Limits) + eigene Alarm-Regeln (Sofort-Alarme).

Neunter Schritt der Code-Modularisierung (siehe ROADMAP.md), nach
investments/tax/debts/goals/trips/wishlist/personal/business_life. Beide
Domänen leben hier zusammen, weil sie inhaltlich verwandt sind (nutzer-
definierte Schwellwerte/Grenzen) und im selben main.py-Abschnitt standen.
Reine Verschiebung ohne Verhaltensänderung."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, crud, auth
from ..database import get_db

budgets_alerts_router = APIRouter(prefix="/api")


# ---------------- Budgets ----------------
@budgets_alerts_router.get("/budgets", response_model=List[schemas.BudgetOut])
def list_budgets(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    budgets = crud.get_budgets(db, space_id)
    return [
        schemas.BudgetOut(
            id=b.id, category_id=b.category_id,
            category_name=b.category.name if b.category else "Unbekannt",
            monthly_limit=b.monthly_limit,
        )
        for b in budgets
    ]


@budgets_alerts_router.get("/budgets/suggestions", response_model=List[schemas.BudgetSuggestionOut])
def get_budget_suggestions(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.suggest_budgets(db, space_id)


@budgets_alerts_router.post("/budgets", response_model=schemas.BudgetOut)
def save_budget(data: schemas.BudgetCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not crud.get_category(db, data.category_id):
        raise HTTPException(400, "Kategorie existiert nicht")
    b = crud.upsert_budget(db, space_id, data)
    return schemas.BudgetOut(
        id=b.id, category_id=b.category_id,
        category_name=b.category.name if b.category else "Unbekannt",
        monthly_limit=b.monthly_limit,
    )


@budgets_alerts_router.delete("/budgets/{category_id}")
def remove_budget(category_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    b = crud.delete_budget(db, space_id, category_id)
    if not b:
        raise HTTPException(404, "Budget nicht gefunden")
    return {"ok": True}


# ---------------- Eigene Regeln (Sofort-Alarme) ----------------
@budgets_alerts_router.get("/alert-rules", response_model=List[schemas.AlertRuleOut])
def list_alert_rules(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.get_alert_rules(db, space_id)


@budgets_alerts_router.post("/alert-rules", response_model=schemas.AlertRuleOut)
def create_alert_rule(data: schemas.AlertRuleCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if data.rule_type in (schemas.AlertRuleType.category_spend_above, schemas.AlertRuleType.category_deviation) and not data.category_id:
        raise HTTPException(400, "Diese Regel braucht eine Kategorie")
    if data.rule_type == schemas.AlertRuleType.account_balance_below and not data.account_id:
        raise HTTPException(400, "Diese Regel braucht ein Konto")
    if data.rule_type == schemas.AlertRuleType.goal_progress_above:
        if not data.goal_id:
            raise HTTPException(400, "Diese Regel braucht ein Ziel")
        goal = db.query(models.Goal).filter(models.Goal.id == data.goal_id).first()
        if not goal:
            raise HTTPException(404, "Ziel nicht gefunden")
        # Nur automatisch messbare Ziele haben ueberhaupt einen Fortschritt -
        # ein manueller Meilenstein ist entweder abgehakt oder nicht, da gaebe
        # es nichts zu ueberwachen (lieber hier klar ablehnen, als eine Regel
        # anzulegen, die nie ausloest).
        if goal.goal_type != models.GoalType.auto_financial or not goal.trigger:
            raise HTTPException(400, "Nur automatisch messbare Ziele haben einen Fortschritt in Prozent")
    return crud.create_alert_rule(db, space_id, data)


@budgets_alerts_router.patch("/alert-rules/{rule_id}", response_model=schemas.AlertRuleOut)
def update_alert_rule(rule_id: int, data: schemas.AlertRuleUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    rule = db.query(models.AlertRule).filter(models.AlertRule.id == rule_id, models.AlertRule.space_id == space_id).first()
    if not rule:
        raise HTTPException(404, "Regel nicht gefunden")
    return crud.update_alert_rule(db, rule, data)


@budgets_alerts_router.delete("/alert-rules/{rule_id}")
def remove_alert_rule(rule_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    rule = db.query(models.AlertRule).filter(models.AlertRule.id == rule_id, models.AlertRule.space_id == space_id).first()
    if not rule:
        raise HTTPException(404, "Regel nicht gefunden")
    crud.delete_alert_rule(db, rule)
    return {"ok": True}
