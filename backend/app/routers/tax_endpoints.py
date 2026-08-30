"""Steuer-Endpunkte (Basiszins-Sätze, Sparerpauschbetrag, Vorabpauschale,
realisierte Gewinne, Zusammenfassung) - näherungsweise Berechnung zur
Orientierung, keine Steuerberatung (siehe backend/app/tax.py, die
eigentliche Berechnungslogik, unverändert dort belassen).

Zweiter Schritt der Code-Modularisierung (siehe ROADMAP.md), nach
routers/investments.py. Datei bewusst NICHT `tax.py` genannt, um nicht mit
dem bestehenden `app/tax.py` (Berechnungslogik, kein Router) zu kollidieren -
unterschiedliche Modulpfade wären technisch kein Problem, aber verwirrend
für zwei gleichnamige Dateien mit unterschiedlicher Bedeutung im selben
Projekt."""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from pydantic import BaseModel

from .. import models, schemas, auth, tax, tax_advice
from ..database import get_db

tax_router = APIRouter(prefix="/api")


class TaxAskIn(BaseModel):
    question: str
    year: Optional[int] = None


class TaxProfileIn(BaseModel):
    church_tax_rate: Optional[float] = None      # 0.0 / 0.08 / 0.09
    marginal_tax_rate: Optional[float] = None    # 0.0 .. 0.45
    filing_married: Optional[bool] = None
    sparerpauschbetrag: Optional[float] = None


class TaxTipStatusIn(BaseModel):
    year: int
    status: str  # "done" | "not_relevant" | "open"


@tax_router.get("/tax/profile")
def get_tax_profile(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    return {
        "church_tax_rate": s.church_tax_rate or 0.0,
        "marginal_tax_rate": s.marginal_tax_rate or 0.0,
        "filing_married": bool(s.filing_married),
        "sparerpauschbetrag": s.sparerpauschbetrag,
        "country": s.residence_country,
    }


@tax_router.put("/tax/profile")
def update_tax_profile(data: TaxProfileIn, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    if data.church_tax_rate is not None:
        s.church_tax_rate = min(0.09, max(0.0, data.church_tax_rate))
    if data.marginal_tax_rate is not None:
        s.marginal_tax_rate = min(0.45, max(0.0, data.marginal_tax_rate))
    if data.filing_married is not None:
        s.filing_married = data.filing_married
    if data.sparerpauschbetrag is not None:
        s.sparerpauschbetrag = max(0.0, data.sparerpauschbetrag)
    db.commit()
    return get_tax_profile(db)


@tax_router.post("/tax/tips/{tip_id}/status")
def set_tax_tip_status(tip_id: str, data: TaxTipStatusIn, db: Session = Depends(get_db)):
    """Markiert einen Spar-Tipp für ein Jahr als erledigt / nicht relevant
    (oder setzt ihn mit "open" zurück). Der Steuern-Tab, /steuer und die
    Jahresend-Erinnerung blenden erledigte Tipps dann aus."""
    row = (db.query(models.TaxTipStatus)
           .filter(models.TaxTipStatus.year == data.year,
                   models.TaxTipStatus.tip_id == tip_id).first())
    if data.status == "open":
        if row:
            db.delete(row)
            db.commit()
        return {"ok": True, "status": "open"}
    if data.status not in ("done", "not_relevant"):
        raise HTTPException(400, "status muss done, not_relevant oder open sein")
    if row:
        row.status = data.status
    else:
        db.add(models.TaxTipStatus(year=data.year, tip_id=tip_id, status=data.status))
    db.commit()
    return {"ok": True, "status": data.status}


@tax_router.get("/tax/tips")
def get_tax_tips(year: Optional[int] = None, db: Session = Depends(get_db),
                 space_id: int = Depends(auth.get_active_space_id)):
    """Regelbasierte Steuer-Spar-Tipps aus den echten Daten (siehe
    app/tax_advice.py) - für den Steuern-Tab. Keine Steuerberatung."""
    settings = auth.get_or_create_settings(db)
    return tax_advice.generate_tips(db, settings, space_id, year or date.today().year)


@tax_router.post("/tax/ask")
def ask_tax_question(data: TaxAskIn, db: Session = Depends(get_db),
                     space_id: int = Depends(auth.get_active_space_id)):
    """Freitext-Frage an die lokale KI, mit den berechneten Steuer-Fakten als
    Kontext. Keine Cloud, mit Haftungshinweis im System-Prompt."""
    settings = auth.get_or_create_settings(db)
    return tax_advice.answer_question(db, settings, space_id, data.question,
                                     data.year or date.today().year)


@tax_router.get("/tax/basiszins", response_model=List[schemas.BasiszinsRateOut])
def list_basiszins(db: Session = Depends(get_db)):
    return db.query(models.BasiszinsRate).order_by(models.BasiszinsRate.year).all()


@tax_router.put("/tax/basiszins", response_model=schemas.BasiszinsRateOut)
def upsert_basiszins(data: schemas.BasiszinsRateUpdate, db: Session = Depends(get_db)):
    row = db.query(models.BasiszinsRate).filter(models.BasiszinsRate.year == data.year).first()
    if row:
        row.rate_percent = data.rate_percent
    else:
        row = models.BasiszinsRate(year=data.year, rate_percent=data.rate_percent)
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


@tax_router.get("/tax/sparerpauschbetrag")
def get_sparerpauschbetrag(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    return {"amount": s.sparerpauschbetrag}


@tax_router.put("/tax/sparerpauschbetrag")
def update_sparerpauschbetrag(data: schemas.SparerpauschbetragUpdate, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    s.sparerpauschbetrag = data.amount
    db.commit()
    return {"amount": s.sparerpauschbetrag}


@tax_router.get("/tax/vorabpauschale", response_model=schemas.PortfolioVorabpauschaleOut)
def get_vorabpauschale(year: Optional[int] = None, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return tax.portfolio_vorabpauschale(db, space_id, year or date.today().year)


@tax_router.get("/tax/realized-gains", response_model=schemas.RealizedGainsOut)
def get_realized_gains(year: Optional[int] = None, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return tax.compute_realized_gains(db, space_id, year or date.today().year)


@tax_router.get("/tax/summary", response_model=schemas.TaxSummaryOut)
def get_tax_summary(year: Optional[int] = None, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    y = year or date.today().year
    vp = tax.portfolio_vorabpauschale(db, space_id, y)
    rg = tax.compute_realized_gains(db, space_id, y)
    settings = auth.get_or_create_settings(db)
    taxable = max(0.0, vp.total_steuerpflichtig + max(rg.total_gain, 0.0) - settings.sparerpauschbetrag)
    return schemas.TaxSummaryOut(
        year=y, vorabpauschale_total=vp.total_steuerpflichtig, realized_gain_total=rg.total_gain,
        sparerpauschbetrag=settings.sparerpauschbetrag, taxable_after_allowance=round(taxable, 2),
    )
