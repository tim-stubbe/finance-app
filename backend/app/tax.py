"""Näherungsweise Berechnung von Vorabpauschale und realisierten Gewinnen für
deutsche Privatanleger (§ 18 InvStG bzw. § 20 EStG). Dient der Orientierung,
ersetzt keine Steuerberatung - insbesondere fehlt die Anrechnung bereits
versteuerter Vorabpauschale auf die Anschaffungskosten bei Verkäufen, und die
Teilfreistellung wird pauschal mit 30% (Aktienfonds) für alle ETF-Positionen
angesetzt, unabhängig von der tatsächlichen Fondskategorie."""

from datetime import date

from sqlalchemy.orm import Session

from . import models, crud, schemas

ACQUIRE_TYPES = (models.LotType.kauf, models.LotType.staking)
TEILFREISTELLUNG_AKTIENFONDS = 0.30


def _price_at(points: list[tuple[str, float]], target: date) -> float | None:
    candidates = [(date.fromisoformat(d), p) for d, p in points if date.fromisoformat(d) <= target]
    if candidates:
        return max(candidates, key=lambda c: c[0])[1]
    return points[0][1] if points else None


def get_basiszins(db: Session, year: int) -> float | None:
    row = db.query(models.BasiszinsRate).filter(models.BasiszinsRate.year == year).first()
    return row.rate_percent if row else None


def compute_vorabpauschale_for_holding(db: Session, holding: models.Holding, year: int) -> schemas.VorabpauschaleOut | None:
    asset_type = holding.asset_type.value if hasattr(holding.asset_type, "value") else holding.asset_type
    if asset_type != "etf":
        return None

    basiszins = get_basiszins(db, year)
    if basiszins is None:
        return None

    lots = sorted(holding.lots, key=lambda l: (l.date, l.id))
    if not lots:
        return None

    year_end = date(year, 12, 31)
    today = date.today()
    is_estimate = year >= today.year
    effective_end = min(year_end, today) if is_estimate else year_end

    qty_start, _ = crud._position_at(lots, date(year - 1, 12, 31))
    qty_end, _ = crud._position_at(lots, effective_end)
    if qty_end <= 0 and qty_start <= 0:
        return None

    try:
        history = crud.get_cached_history(db, asset_type, holding.symbol, "max")
    except Exception:
        history = []

    price_start = _price_at(history, date(year - 1, 12, 31)) if (history and qty_start > 0) else None
    if is_estimate:
        price_end = holding.current_price or (history[-1][1] if history else None)
    else:
        price_end = _price_at(history, effective_end) if history else None

    if price_end is None:
        return None

    basisertrag = 0.0
    invested_this_year = 0.0
    value_start = 0.0
    if qty_start > 0 and price_start is not None:
        value_start = qty_start * price_start
        basisertrag += value_start * (basiszins / 100) * 0.7

    for lot in lots:
        if lot.type not in ACQUIRE_TYPES or lot.date.year != year:
            continue
        months_held = 12 - lot.date.month + 1
        value_at_purchase = lot.quantity * lot.price_per_unit
        basisertrag += value_at_purchase * (basiszins / 100) * 0.7 * (months_held / 12)
        invested_this_year += value_at_purchase

    value_end = qty_end * price_end
    wertsteigerung = value_end - value_start - invested_this_year

    vorabpauschale_brutto = max(0.0, min(basisertrag, max(wertsteigerung, 0.0)))

    dividends_out = crud.holding_dividends(db, holding)
    dividends_in_year = sum(
        p.total for p in dividends_out.history if date.fromisoformat(p.date).year == year
    )

    vorabpauschale = max(0.0, vorabpauschale_brutto - dividends_in_year)
    steuerpflichtig = vorabpauschale * (1 - TEILFREISTELLUNG_AKTIENFONDS)

    return schemas.VorabpauschaleOut(
        holding_id=holding.id, name=holding.name, symbol=holding.symbol, year=year,
        basiszins_percent=basiszins, basisertrag=round(basisertrag, 2),
        wertsteigerung=round(wertsteigerung, 2), ausschuettung=round(dividends_in_year, 2),
        vorabpauschale=round(vorabpauschale, 2),
        teilfreistellung_percent=TEILFREISTELLUNG_AKTIENFONDS * 100,
        steuerpflichtiger_betrag=round(steuerpflichtig, 2),
        is_estimate=is_estimate,
    )


def portfolio_vorabpauschale(db: Session, space_id: int, year: int) -> schemas.PortfolioVorabpauschaleOut:
    holdings = crud.get_holdings(db, space_id)
    rows = []
    has_etf = False
    for h in holdings:
        asset_type = h.asset_type.value if hasattr(h.asset_type, "value") else h.asset_type
        if asset_type == "etf":
            has_etf = True
        row = compute_vorabpauschale_for_holding(db, h, year)
        if row:
            rows.append(row)
    total = round(sum(r.steuerpflichtiger_betrag for r in rows), 2)
    missing = has_etf and get_basiszins(db, year) is None
    return schemas.PortfolioVorabpauschaleOut(year=year, rows=rows, total_steuerpflichtig=total, missing_basiszins=missing)


def compute_realized_gains(db: Session, space_id: int, year: int) -> schemas.RealizedGainsOut:
    holdings = crud.get_holdings(db, space_id)
    rows = []
    for h in holdings:
        lots = sorted(h.lots, key=lambda l: (l.date, l.id))
        qty, total_cost = 0.0, 0.0
        for lot in lots:
            if lot.type in ACQUIRE_TYPES:
                qty += lot.quantity
                total_cost += lot.quantity * lot.price_per_unit
            elif lot.type == models.LotType.verkauf:
                if qty > 0:
                    avg_cost = total_cost / qty
                    sell_qty = min(lot.quantity, qty)
                    proceeds = sell_qty * lot.price_per_unit
                    cost_basis = sell_qty * avg_cost
                    if lot.date.year == year:
                        rows.append(schemas.RealizedGainRow(
                            holding_id=h.id, name=h.name, symbol=h.symbol, date=lot.date,
                            quantity=round(sell_qty, 8), proceeds=round(proceeds, 2),
                            cost_basis=round(cost_basis, 2), gain=round(proceeds - cost_basis, 2),
                        ))
                    total_cost -= cost_basis
                    qty -= sell_qty
    rows.sort(key=lambda r: r.date)
    total_gain = round(sum(r.gain for r in rows), 2)
    return schemas.RealizedGainsOut(year=year, rows=rows, total_gain=total_gain)
