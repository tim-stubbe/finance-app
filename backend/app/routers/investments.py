"""Investments-Endpunkte (Holdings/Lots/Kurshistorie/Portfolio-Kennzahlen).

Erster Baustein der Code-Modularisierung (siehe ROADMAP.md) - main.py war auf
~5900 Zeilen gewachsen, ohne fachliche Aufteilung. Reine Verschiebung ohne
Verhaltensänderung: exakt dieselben Pfade/Funktionen wie vorher, nur aus
main.py heraus in ein eigenes Modul, registriert wie sync_router (siehe
sync.py) über `app.include_router(investments_router)` in main.py.

Bewusst NICHT /tax/* und /net-worth hier mit rausgezogen - die bleiben für
diesen ersten Schritt in main.py, um die Änderung überschaubar zu halten
(siehe ROADMAP.md: "in kleinen Schritten"). Weitere fachliche Router
(Debts, Goals, ...) folgen bei Bedarf nach demselben Muster."""

from datetime import date, datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, crud, auth, prices
from ..database import get_db

investments_router = APIRouter(prefix="/api")


# ---------------- Holdings (Investments) ----------------
@investments_router.get("/holdings", response_model=List[schemas.HoldingOut])
def list_holdings(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return [crud.holding_out(h) for h in crud.get_holdings(db, space_id)]


@investments_router.post("/holdings", response_model=schemas.HoldingOut)
def create_holding(data: schemas.HoldingCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    # Gleiches Symbol schon vorhanden (z.B. ein zweiter Kauf/Sparplan-Vorgang
    # derselben Aktie) -> als weiteren Vorgang an die bestehende Position
    # haengen statt eine zweite, doppelte Zeile anzulegen (dieselbe Regel wie
    # beim Beleg-Chat- und CSV-Import, siehe crud.find_holding_by_symbol).
    existing = crud.find_holding_by_symbol(db, space_id, data.asset_type, data.symbol)
    if existing:
        crud.create_lot(db, existing.id, space_id, schemas.HoldingLotCreate(
            date=data.purchase_date or date.today(), type=models.LotType.kauf,
            quantity=data.quantity, price_per_unit=data.purchase_price,
        ))
        out = crud.holding_out(existing)
        out.price_warning = f"Als weiterer Vorgang zu bestehender Position „{existing.name}“ ({existing.symbol}) hinzugefügt statt einer neuen Zeile."
        return out

    h = crud.create_holding(db, data, space_id)
    price_warning = None
    if h.asset_type in (models.AssetType.aktie, models.AssetType.etf):
        try:
            profile = prices.fetch_profile(h.symbol)
            h.sector = h.sector or profile["sector"]
            h.country = profile["country"]
            h.currency = profile["currency"]
        except Exception:
            pass
    if h.asset_type in (models.AssetType.aktie, models.AssetType.etf, models.AssetType.krypto):
        try:
            h.current_price = prices.fetch_price_eur(h.asset_type.value, h.symbol)
            h.price_updated_at = datetime.utcnow()
        except Exception as e:
            # Kein Abbruch - die Position wird trotzdem angelegt (das Symbol
            # koennte spaeter korrigiert werden), aber der Nutzer bekommt
            # sofort einen Hinweis statt still einen dauerhaft kurslosen
            # Eintrag zu erzeugen (genau das Problem, das zur Nvidia-Dublette
            # mit Symbol="Nvidia" statt "NVDA" gefuehrt hat).
            price_warning = f"Kein Kurs gefunden für Symbol „{h.symbol}“ - bitte prüfen (z.B. den echten Ticker wie „NVDA“ statt des Firmennamens verwenden). Fehler: {e}"
    db.commit()
    db.refresh(h)
    out = crud.holding_out(h)
    out.price_warning = price_warning
    return out


@investments_router.put("/holdings/{holding_id}", response_model=schemas.HoldingOut)
def update_holding(holding_id: int, data: schemas.HoldingUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    h = crud.update_holding(db, holding_id, space_id, data)
    if not h:
        raise HTTPException(404, "Position nicht gefunden")
    return crud.holding_out(h)


@investments_router.delete("/holdings/{holding_id}")
def delete_holding(holding_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    h = crud.delete_holding(db, holding_id, space_id)
    if not h:
        raise HTTPException(404, "Position nicht gefunden")
    return {"ok": True}


@investments_router.post("/holdings/refresh-prices", response_model=schemas.PriceRefreshResult)
def refresh_prices(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    holdings = crud.get_holdings(db, space_id)
    updated = 0
    failed: list[str] = []
    for h in holdings:
        try:
            h.current_price = prices.fetch_price_eur(h.asset_type.value, h.symbol)
            h.price_updated_at = datetime.utcnow()
            updated += 1
        except Exception as e:
            failed.append(f"{h.name} ({h.symbol}): {e}")
    db.commit()
    return schemas.PriceRefreshResult(
        updated=updated,
        failed=failed,
        holdings=[crud.holding_out(h) for h in crud.get_holdings(db, space_id)],
    )


@investments_router.get("/holdings/{holding_id}/lots", response_model=List[schemas.HoldingLotOut])
def list_lots(holding_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    lots = crud.get_lots(db, holding_id, space_id)
    if lots is None:
        raise HTTPException(404, "Position nicht gefunden")
    return lots


@investments_router.post("/holdings/{holding_id}/lots", response_model=schemas.HoldingLotOut)
def create_lot(holding_id: int, data: schemas.HoldingLotCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    lot = crud.create_lot(db, holding_id, space_id, data)
    if not lot:
        raise HTTPException(404, "Position nicht gefunden")
    return lot


@investments_router.put("/holdings/{holding_id}/lots/{lot_id}", response_model=schemas.HoldingLotOut)
def update_lot(holding_id: int, lot_id: int, data: schemas.HoldingLotUpdate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    lot = crud.update_lot(db, lot_id, holding_id, space_id, data)
    if not lot:
        raise HTTPException(404, "Kauf/Verkauf nicht gefunden")
    return lot


@investments_router.delete("/holdings/{holding_id}/lots/{lot_id}")
def delete_lot(holding_id: int, lot_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    lot = crud.delete_lot(db, lot_id, holding_id, space_id)
    if not lot:
        raise HTTPException(404, "Kauf/Verkauf nicht gefunden")
    return {"ok": True}


# ---------------- Kurshistorie & Portfolio-Verlauf ----------------
@investments_router.get("/holdings/{holding_id}/history", response_model=schemas.HoldingHistoryOut)
def get_holding_history(holding_id: int, range: str = "1y", db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    try:
        result = crud.holding_history(db, holding_id, space_id, range)
    except Exception as e:
        raise HTTPException(400, f"Kurshistorie konnte nicht geladen werden: {e}")
    if result is None:
        raise HTTPException(404, "Position nicht gefunden")
    return result


@investments_router.get("/portfolio/history", response_model=schemas.PortfolioHistoryOut)
def get_portfolio_history(range: str = "1y", db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.portfolio_history(db, space_id, range)


@investments_router.get("/portfolio/diversification", response_model=schemas.DiversificationOut)
def get_portfolio_diversification(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.portfolio_diversification(db, space_id)


@investments_router.get("/portfolio/volatility", response_model=schemas.VolatilityOut)
def get_portfolio_volatility(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.portfolio_volatility(db, space_id)


@investments_router.get("/portfolio/dividends", response_model=schemas.PortfolioDividendsOut)
def get_portfolio_dividends(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.portfolio_dividends(db, space_id)


@investments_router.get("/investments/savings-plans", response_model=schemas.SavingsPlansOut)
def get_savings_plans(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    """Aktuell laufende Sparpläne (aktuell nur Scalable Capital, siehe
    scalable_sync.sync_savings_plans) - reiner Lesezugriff auf die zuletzt
    synchronisierten Daten, kein Live-Abruf bei jedem Aufruf."""
    return crud.get_savings_plans(db, space_id)


@investments_router.get("/portfolio/dividends/upcoming", response_model=List[schemas.UpcomingDividendOut])
def get_upcoming_dividends(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.estimate_next_dividends(db, space_id)
