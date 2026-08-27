"""Investments-Domäne (Holdings/Lots, Diversifikation, Dividenden, Kurs-
historie) - erster Schritt der crud.py-Modularisierung (siehe ROADMAP.md),
analog zur main.py-Router-Extraktion. Reine Verschiebung ohne Verhaltens-
änderung.

net_worth/build_digest/record_net_worth_snapshot/net_worth_history bleiben
bewusst in crud.py - die sind cross-cutting (Konten+Investments+Schulden
bzw. der komplette Digest-Aufbau), keine reinen Investments-Funktionen,
auch wenn sie im selben main.py-Abschnitt standen.

crud.py importiert alle hier definierten Namen zurück (from .crud_investments
import ...), damit jeder bestehende `crud.holding_out(...)`-Aufrufstil in
main.py/routers/ unverändert weiterfunktioniert - keine Aufrufstellen
mussten angepasst werden."""

import json
import math
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from . import models, schemas, prices

CACHE_TTL = timedelta(hours=24)


def get_cached_history(db: Session, asset_type: str, symbol: str, range_key: str) -> list[tuple[str, float]]:
    """Holt Kurshistorie, cacht sie aber für 'lange' Ranges (alles außer 1d/2w) einen
    Tag lang auf der Festplatte statt bei jedem Chart-Aufruf erneut die externe API
    zu befragen. 1d/2w bleiben bewusst immer live, da sie kurzfristige Bewegungen
    zeigen sollen. Schlägt der Live-Abruf fehl, wird - falls vorhanden - auf einen
    auch älteren Cache-Stand zurückgegriffen statt einen Fehler zu werfen.

    Live beobachtet: einige automatisch von Scalable Capital übernommene
    Positionen tragen eine ISIN statt eines Yahoo-Tickers als symbol - Yahoo
    liefert dafür zuverlässig 404. Ohne die fetched_at-Aktualisierung unten hat
    das JEDEN Portfolio-Chart-Aufruf erneut denselben aussichtslosen Live-Abruf
    versuchen lassen (10+ Positionen x mehrere Sekunden Latenz = das Chart hat
    "mega lange" gebraucht). fetched_at wird deshalb IMMER aktualisiert, auch
    bei einem fehlgeschlagenen Abruf (negatives Caching) - ein dauerhaft
    kaputtes Symbol wird dadurch höchstens einmal pro CACHE_TTL neu versucht,
    nicht bei jedem einzelnen Request."""
    if range_key in prices.LIVE_RANGES:
        return prices.fetch_history(asset_type, symbol, range_key)

    row = (
        db.query(models.PriceHistoryCache)
        .filter_by(asset_type=asset_type, symbol=symbol, range_key=range_key)
        .first()
    )
    if row and (datetime.utcnow() - row.fetched_at) < CACHE_TTL:
        return json.loads(row.data_json)

    try:
        points = prices.fetch_history(asset_type, symbol, range_key)
    except Exception:
        if row:
            row.fetched_at = datetime.utcnow()
            db.commit()
            return json.loads(row.data_json)
        db.add(models.PriceHistoryCache(
            asset_type=asset_type, symbol=symbol, range_key=range_key,
            fetched_at=datetime.utcnow(), data_json="[]",
        ))
        db.commit()
        return []

    payload = json.dumps(points)
    if row:
        row.data_json = payload
        row.fetched_at = datetime.utcnow()
    else:
        db.add(models.PriceHistoryCache(
            asset_type=asset_type, symbol=symbol, range_key=range_key,
            fetched_at=datetime.utcnow(), data_json=payload,
        ))
    db.commit()
    return points


# Ranges, die get_cached_history tatsächlich auf der Festplatte cacht (alles
# außer LIVE_RANGES, siehe prices.py) - für refresh_price_history_cache unten.
_CACHEABLE_RANGES = [r for r in prices.RANGE_MAP if r not in prices.LIVE_RANGES]


def refresh_price_history_cache(db: Session) -> dict:
    """Wärmt den Kurshistorie-Cache für ALLE gehaltenen Positionen einmal täglich
    im Hintergrund vor (aufgerufen von main._scheduled_bank_sync, gleicher
    Rhythmus wie der Bank-/Broker-Sync) - live beobachtet: portfolio_history()
    ruft get_cached_history() für jede Position sequenziell auf, war der
    24h-Cache beim Öffnen des Investments-Tabs abgelaufen (was bei täglichem
    Öffnen praktisch IMMER der Fall war, siehe CACHE_TTL), hat das bei ~15+
    Positionen ~15+ blockierende Live-Anfragen an Yahoo/CoinGecko HINTEREINANDER
    im selben Request ausgelöst - das Portfolio-Chart hat dadurch spürbar lange
    gebraucht. Läuft dieser Refresh stattdessen einmal täglich im Hintergrund,
    ist der Cache beim nächsten Öffnen praktisch immer frisch (< 24h alt) und
    get_cached_history liest nur noch aus der DB - keine Wartezeit mehr.
    Jede Position/Range isoliert in try/except, damit eine einzelne kaputte
    Notierung (z.B. delistetes Symbol) nicht die übrigen blockiert."""
    symbols = (
        db.query(models.Holding.asset_type, models.Holding.symbol)
        .filter(models.Holding.lots.any())
        .distinct()
        .all()
    )
    refreshed, failed = 0, []
    for asset_type, symbol in symbols:
        asset_type_value = asset_type.value if hasattr(asset_type, "value") else asset_type
        for range_key in _CACHEABLE_RANGES:
            try:
                get_cached_history(db, asset_type_value, symbol, range_key)
                refreshed += 1
            except Exception as e:
                failed.append(f"{symbol} ({range_key}): {e}")
    return {"refreshed": refreshed, "failed": failed}


# ---------- Holdings (Investments) ----------
def get_holdings(db: Session, space_id: int):
    return (
        db.query(models.Holding)
        .filter(models.Holding.space_id == space_id)
        .order_by(models.Holding.name)
        .all()
    )


def get_savings_plans(db: Session, space_id: int) -> schemas.SavingsPlansOut:
    """Liest die von scalable_sync.sync_savings_plans synchronisierten
    Sparpläne - reiner Lesezugriff, die eigentliche Sync-Logik lebt bewusst
    in scalable_sync.py (analog zu holdings/lots dort)."""
    plans = (
        db.query(models.SavingsPlan)
        .filter(models.SavingsPlan.space_id == space_id)
        .order_by(models.SavingsPlan.name)
        .all()
    )
    total = round(sum(p.amount for p in plans if p.frequency == "MONTHLY"), 2)
    return schemas.SavingsPlansOut(
        plans=[schemas.SavingsPlanOut.model_validate(p) for p in plans],
        total_monthly_amount=total,
    )


def get_holding(db: Session, holding_id: int, space_id: int):
    return (
        db.query(models.Holding)
        .filter(models.Holding.id == holding_id, models.Holding.space_id == space_id)
        .first()
    )


def find_holding_by_symbol(db: Session, space_id: int, asset_type, symbol: str) -> models.Holding | None:
    """Sucht eine bestehende Position mit demselben Symbol (gross-/klein-
    schreibungsunabhaengig) - dieselbe Logik, die main.py schon beim Beleg-
    Chat-Import und beim CSV-Import nutzt, hier als gemeinsamer Helfer auch
    fuer die manuelle "Neue Position"-Eingabe (siehe main.create_holding),
    damit ein zweiter Kauf derselben Aktie dort als weiterer Vorgang an die
    bestehende Position gehaengt wird statt eine zweite, doppelte Zeile
    anzulegen."""
    symbol_lower = symbol.strip().lower()
    return next(
        (h for h in get_holdings(db, space_id) if h.asset_type == asset_type and h.symbol.lower() == symbol_lower),
        None,
    )


def create_holding(db: Session, data: schemas.HoldingCreate, space_id: int):
    holding = models.Holding(**data.model_dump(), space_id=space_id)
    db.add(holding)
    db.flush()
    if holding.quantity:
        db.add(models.HoldingLot(
            holding_id=holding.id,
            date=holding.purchase_date or date.today(),
            type=models.LotType.kauf,
            quantity=holding.quantity,
            price_per_unit=holding.purchase_price,
        ))
    db.commit()
    db.refresh(holding)
    return holding


def update_holding(db: Session, holding_id: int, space_id: int, data: schemas.HoldingUpdate):
    holding = get_holding(db, holding_id, space_id)
    if not holding:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(holding, key, value)
    db.commit()
    db.refresh(holding)
    return holding


def delete_holding(db: Session, holding_id: int, space_id: int):
    holding = get_holding(db, holding_id, space_id)
    if holding:
        db.delete(holding)
        db.commit()
    return holding


RISK_LEVELS = {
    "krypto": "hoch",
    "aktie": "mittel-hoch",
    "etf": "mittel",
    "anleihe": "niedrig",
    "sonstiges": "unbekannt",
}


def holding_out(h: models.Holding) -> schemas.HoldingOut:
    current = h.current_price if h.current_price is not None else h.purchase_price
    purchase_value = round(h.quantity * h.purchase_price, 2)
    current_value = round(h.quantity * current, 2)
    gain_abs = round(current_value - purchase_value, 2)
    gain_pct = round((gain_abs / purchase_value * 100) if purchase_value else 0.0, 2)
    return schemas.HoldingOut(
        id=h.id,
        asset_type=h.asset_type,
        name=h.name,
        symbol=h.symbol,
        sector=h.sector,
        country=h.country,
        currency=h.currency,
        risk_level=RISK_LEVELS.get(h.asset_type.value if hasattr(h.asset_type, "value") else h.asset_type, "unbekannt"),
        quantity=h.quantity,
        purchase_price=h.purchase_price,
        purchase_date=h.purchase_date,
        current_price=h.current_price,
        price_updated_at=h.price_updated_at,
        import_source=h.import_source,
        purchase_value=purchase_value,
        current_value=current_value,
        gain_abs=gain_abs,
        gain_pct=gain_pct,
        lot_count=len(h.lots),
    )


# ---------- Holding-Lots (einzelne Käufe/Verkäufe) ----------
def recompute_holding_from_lots(db: Session, holding: models.Holding):
    """Leitet Stückzahl und durchschnittlichen Einstandspreis aus den Lots ab
    (Durchschnittskostenmethode: ein Verkauf reduziert die Stückzahl zum aktuellen
    Durchschnittspreis, unabhängig davon welches konkrete Lot verkauft wurde)."""
    lots = sorted(holding.lots, key=lambda l: (l.date, l.id))
    qty, total_cost, first_date = 0.0, 0.0, None
    for lot in lots:
        if lot.type in (models.LotType.kauf, models.LotType.staking):
            if first_date is None or (lot.date and lot.date < first_date):
                first_date = lot.date
            qty += lot.quantity
            total_cost += lot.quantity * lot.price_per_unit
        elif lot.type == models.LotType.verkauf:
            if qty > 0:
                avg_cost = total_cost / qty
                sell_qty = min(lot.quantity, qty)
                total_cost -= sell_qty * avg_cost
                qty -= sell_qty
        # dividende: reine Ertragsbuchung, wirkt sich nicht auf Bestand/Einstand aus
    holding.quantity = round(max(qty, 0.0), 8)
    holding.purchase_price = round(total_cost / qty, 6) if qty > 0 else 0.0
    holding.purchase_date = first_date


def get_lots(db: Session, holding_id: int, space_id: int):
    holding = get_holding(db, holding_id, space_id)
    if not holding:
        return None
    return sorted(holding.lots, key=lambda l: (l.date, l.id))


def get_lot(db: Session, lot_id: int, holding_id: int, space_id: int):
    holding = get_holding(db, holding_id, space_id)
    if not holding:
        return None
    return db.query(models.HoldingLot).filter(
        models.HoldingLot.id == lot_id, models.HoldingLot.holding_id == holding_id
    ).first()


def create_lot(db: Session, holding_id: int, space_id: int, data: schemas.HoldingLotCreate):
    holding = get_holding(db, holding_id, space_id)
    if not holding:
        return None
    lot = models.HoldingLot(holding_id=holding_id, **data.model_dump())
    db.add(lot)
    db.flush()
    db.refresh(holding)
    recompute_holding_from_lots(db, holding)
    db.commit()
    db.refresh(lot)
    return lot


def update_lot(db: Session, lot_id: int, holding_id: int, space_id: int, data: schemas.HoldingLotUpdate):
    lot = get_lot(db, lot_id, holding_id, space_id)
    if not lot:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(lot, key, value)
    db.flush()
    holding = get_holding(db, holding_id, space_id)
    recompute_holding_from_lots(db, holding)
    db.commit()
    db.refresh(lot)
    return lot


def delete_lot(db: Session, lot_id: int, holding_id: int, space_id: int):
    lot = get_lot(db, lot_id, holding_id, space_id)
    if not lot:
        return None
    db.delete(lot)
    db.flush()
    holding = get_holding(db, holding_id, space_id)
    recompute_holding_from_lots(db, holding)
    db.commit()
    return lot


# ---------- Diversifikation & Risiko ----------
def portfolio_diversification(db: Session, space_id: int) -> schemas.DiversificationOut:
    holdings = get_holdings(db, space_id)
    by_type: dict[str, float] = {}
    by_sector: dict[str, float] = {}
    by_position: dict[str, float] = {}
    by_region: dict[str, float] = {}
    by_currency: dict[str, float] = {}
    total = 0.0
    currency_total = 0.0
    for h in holdings:
        current = h.current_price if h.current_price is not None else h.purchase_price
        value = h.quantity * current
        if value <= 0:
            continue
        total += value
        type_label = h.asset_type.value if hasattr(h.asset_type, "value") else h.asset_type
        by_type[type_label] = by_type.get(type_label, 0.0) + value
        sector_label = h.sector or "Nicht zugeordnet"
        by_sector[sector_label] = by_sector.get(sector_label, 0.0) + value
        by_position[h.name] = by_position.get(h.name, 0.0) + value
        region_label = h.country or "Nicht zugeordnet"
        by_region[region_label] = by_region.get(region_label, 0.0) + value
        # Krypto ist bewusst außen vor - keine "Währung" im klassischen Sinn.
        if type_label != "krypto":
            currency_label = h.currency or "Unbekannt"
            by_currency[currency_label] = by_currency.get(currency_label, 0.0) + value
            currency_total += value

    def slices(d: dict[str, float], basis: float | None = None) -> list[schemas.DiversificationSlice]:
        denom = total if basis is None else basis
        return sorted(
            [
                schemas.DiversificationSlice(
                    label=k, value=round(v, 2), percent=round((v / denom * 100) if denom else 0.0, 1)
                )
                for k, v in d.items()
            ],
            key=lambda s: s.value, reverse=True,
        )

    risk_flags: list[schemas.RiskFlag] = []
    if total > 0:
        for h in holdings:
            current = h.current_price if h.current_price is not None else h.purchase_price
            value = h.quantity * current
            share = value / total * 100
            if share >= 40:
                risk_flags.append(schemas.RiskFlag(
                    level="hoch",
                    message=f"{h.name} macht {share:.0f}% deines Portfolios aus - hohe Klumpenrisiko-Gefahr.",
                ))
        krypto_share = by_type.get("krypto", 0.0) / total * 100
        if krypto_share >= 50:
            risk_flags.append(schemas.RiskFlag(
                level="hoch",
                message=f"{krypto_share:.0f}% deines Portfolios steckt in Krypto - hohe Schwankungsbreite.",
            ))
        if len(holdings) <= 2 and total > 0:
            risk_flags.append(schemas.RiskFlag(
                level="mittel",
                message="Nur wenige Positionen im Portfolio - wenig Streuung.",
            ))

    return schemas.DiversificationOut(
        by_asset_type=slices(by_type),
        by_sector=slices(by_sector),
        by_position=slices(by_position),
        by_region=slices(by_region),
        by_currency=slices(by_currency, basis=currency_total),
        risk_flags=risk_flags,
    )


def compute_volatility(db: Session, asset_type: str, symbol: str) -> float | None:
    """Annualisierte Volatilität (Standardabweichung der täglichen Log-Renditen über
    das letzte Jahr, hochgerechnet auf ein Jahr) in Prozent. None, wenn zu wenig
    Kursdaten vorliegen. Nutzt denselben Tages-Cache wie der 1J-Chart."""
    try:
        points = get_cached_history(db, asset_type, symbol, "1y")
    except Exception:
        return None
    closes = [p[1] for p in points if p[1] > 0]
    if len(closes) < 10:
        return None
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    if len(returns) < 5:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    return round((variance ** 0.5) * (252 ** 0.5) * 100, 1)


def portfolio_volatility(db: Session, space_id: int) -> schemas.VolatilityOut:
    holdings = get_holdings(db, space_id)
    result = []
    for h in holdings:
        asset_type = h.asset_type.value if hasattr(h.asset_type, "value") else h.asset_type
        if asset_type in ("anleihe", "sonstiges"):
            continue
        result.append(schemas.HoldingVolatility(
            holding_id=h.id, name=h.name, volatility_pct=compute_volatility(db, asset_type, h.symbol),
        ))
    return schemas.VolatilityOut(holdings=result)


# ---------- Dividenden ----------
def get_cached_dividends(db: Session, symbol: str) -> list[tuple[str, float]]:
    """Wie get_cached_history, aber für Dividendenzahlungen (eigener Cache-Eintrag
    über asset_type='dividend' als Unterscheidungsmerkmal, einmal täglich aktualisiert)."""
    row = (
        db.query(models.PriceHistoryCache)
        .filter_by(asset_type="dividend", symbol=symbol, range_key="dividends")
        .first()
    )
    if row and (datetime.utcnow() - row.fetched_at) < CACHE_TTL:
        return json.loads(row.data_json)
    try:
        points = prices.fetch_dividends(symbol)
    except Exception:
        if row:
            return json.loads(row.data_json)
        raise
    payload = json.dumps(points)
    if row:
        row.data_json = payload
        row.fetched_at = datetime.utcnow()
    else:
        db.add(models.PriceHistoryCache(
            asset_type="dividend", symbol=symbol, range_key="dividends",
            fetched_at=datetime.utcnow(), data_json=payload,
        ))
    db.commit()
    return points


def holding_dividends(db: Session, holding: models.Holding) -> schemas.HoldingDividendsOut:
    asset_type = holding.asset_type.value if hasattr(holding.asset_type, "value") else holding.asset_type
    history: list[schemas.DividendPayment] = []
    annual_rate_per_share = 0.0
    if asset_type in ("aktie", "etf"):
        try:
            div_points = get_cached_dividends(db, holding.symbol)
        except Exception:
            div_points = []
        lots = sorted(holding.lots, key=lambda l: (l.date, l.id))
        cutoff = date.today() - timedelta(days=365)
        for d, amount_per_share in div_points:
            d_date = date.fromisoformat(d)
            qty, _ = _position_at(lots, d_date)
            if qty <= 0:
                continue
            history.append(schemas.DividendPayment(
                date=d, amount_per_share=amount_per_share, quantity=qty, total=round(qty * amount_per_share, 2),
            ))
            if d_date >= cutoff:
                annual_rate_per_share += amount_per_share

    annual_income = round(annual_rate_per_share * holding.quantity, 2)
    return schemas.HoldingDividendsOut(
        holding_id=holding.id, name=holding.name, symbol=holding.symbol,
        history=history,
        annual_rate_per_share=round(annual_rate_per_share, 4),
        annual_income_estimate=annual_income,
        forecast_1y=annual_income,
        forecast_5y=round(annual_income * 5, 2),
        forecast_10y=round(annual_income * 10, 2),
    )


def portfolio_dividends(db: Session, space_id: int) -> schemas.PortfolioDividendsOut:
    holdings = get_holdings(db, space_id)
    per_holding = [holding_dividends(db, h) for h in holdings]
    per_holding = [h for h in per_holding if h.history or h.annual_rate_per_share]

    by_year: dict[int, float] = {}
    for h in per_holding:
        for payment in h.history:
            year = int(payment.date[:4])
            by_year[year] = round(by_year.get(year, 0.0) + payment.total, 2)

    total_annual = round(sum(h.annual_income_estimate for h in per_holding), 2)
    return schemas.PortfolioDividendsOut(
        total_annual_income_estimate=total_annual,
        forecast_1y=total_annual,
        forecast_5y=round(total_annual * 5, 2),
        forecast_10y=round(total_annual * 10, 2),
        by_year=[schemas.YearlyDividendPoint(year=y, total=v) for y, v in sorted(by_year.items())],
        holdings=per_holding,
    )


def estimate_next_dividends(db: Session, space_id: int) -> list[dict]:
    """Schätzt je Position den nächsten Zahlungstermin aus dem Abstand der
    letzten Zahlungen (z.B. quartalsweise alle ~91 Tage) - Yahoo liefert nur
    VERGANGENE Zahlungstermine, keine offizielle Ankündigung künftiger. Bewusst
    als Schätzung behandelt (im Aufrufer klar so kommuniziert), nicht als
    Zusage - Unternehmen können Termine verschieben oder Dividenden aussetzen,
    anders als eine Bank-Lastschrift also spürbar unsicherer als
    detect_recurring_transactions."""
    results = []
    for h in get_holdings(db, space_id):
        if h.asset_type not in (models.AssetType.aktie, models.AssetType.etf):
            continue
        try:
            div_points = get_cached_dividends(db, h.symbol)
        except Exception:
            continue
        if len(div_points) < 2:
            continue

        dated = sorted((date.fromisoformat(d), amt) for d, amt in div_points)
        dates = [d for d, _ in dated]
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        # nur die juengsten Abstaende - ein Wechsel von jaehrlich auf
        # quartalsweise (oder umgekehrt) soll nicht von alten Abstaenden verwaesert werden.
        recent_gaps = gaps[-4:]
        avg_gap = sum(recent_gaps) / len(recent_gaps)
        if avg_gap < 25:
            continue  # zu unregelmaessig/haeufig fuer eine sinnvolle Schaetzung

        last_date, last_amount_per_share = dated[-1]
        next_estimate = last_date + timedelta(days=round(avg_gap))
        while next_estimate < date.today():
            next_estimate += timedelta(days=round(avg_gap))

        qty, _ = _position_at(sorted(h.lots, key=lambda l: (l.date, l.id)), date.today())
        if qty <= 0:
            continue

        results.append({
            "holding_id": h.id,
            "name": h.name,
            "symbol": h.symbol,
            "estimated_date": next_estimate,
            "estimated_amount": round(qty * last_amount_per_share, 2),
        })

    results.sort(key=lambda r: r["estimated_date"])
    return results


def evaluate_dividend_reminders(db: Session, space_id: int, days_before: int = 7) -> list[dict]:
    """Läuft täglich (siehe main._check_daily_alerts): gibt Positionen zurück,
    deren geschätzter nächster Dividendentermin jetzt in den nächsten
    `days_before` Tagen liegt und für GENAU diesen Termin noch nicht erinnert
    wurde. next_dividend_notified_for verhindert eine tägliche Wiederholung,
    solange derselbe geschätzte Termin bevorsteht - verschiebt sich die
    Schätzung nach der nächsten echten Zahlung, wird wieder frisch erinnert."""
    due = []
    today = date.today()
    for est in estimate_next_dividends(db, space_id):
        holding = db.get(models.Holding, est["holding_id"])
        if not holding:
            continue
        days_left = (est["estimated_date"] - today).days
        if 0 <= days_left <= days_before and holding.next_dividend_notified_for != est["estimated_date"]:
            holding.next_dividend_notified_for = est["estimated_date"]
            due.append(est)
    db.commit()
    return due


# ---------- Kurshistorie & Portfolio-Verlauf ----------
def holding_history(db: Session, holding_id: int, space_id: int, range_key: str) -> schemas.HoldingHistoryOut | None:
    holding = get_holding(db, holding_id, space_id)
    if not holding:
        return None
    asset_type = holding.asset_type.value if hasattr(holding.asset_type, "value") else holding.asset_type
    raw_points = get_cached_history(db, asset_type, holding.symbol, range_key)
    lots = sorted(holding.lots, key=lambda l: (l.date, l.id))
    return schemas.HoldingHistoryOut(
        holding=holding_out(holding),
        points=[schemas.HoldingHistoryPoint(date=d, price=p) for d, p in raw_points],
        lots=[
            schemas.HoldingLotOut(
                id=l.id, date=l.date, type=l.type, quantity=l.quantity,
                price_per_unit=l.price_per_unit, notes=l.notes,
            )
            for l in lots
        ],
    )


def _position_at(lots: list[models.HoldingLot], target_date: date) -> tuple[float, float]:
    """Gehaltene Stückzahl und Einstandswert (Summe der Anschaffungskosten der
    verbliebenen Stückzahl, Durchschnittskostenmethode) zu einem Stichtag."""
    qty, total_cost = 0.0, 0.0
    for lot in lots:
        if lot.date and lot.date <= target_date:
            if lot.type in (models.LotType.kauf, models.LotType.staking):
                qty += lot.quantity
                total_cost += lot.quantity * lot.price_per_unit
            elif lot.type == models.LotType.verkauf and qty > 0:
                avg_cost = total_cost / qty
                sell_qty = min(lot.quantity, qty)
                total_cost -= sell_qty * avg_cost
                qty -= sell_qty
    return max(qty, 0.0), max(total_cost, 0.0)


def portfolio_history(db: Session, space_id: int, range_key: str) -> schemas.PortfolioHistoryOut:
    holdings = get_holdings(db, space_id)
    series_by_holding = {}
    # Positionen ganz ohne abrufbare Kurshistorie (z.B. Scalable-Capital-
    # Positionen mit ISIN statt Yahoo-Ticker als symbol, siehe
    # get_cached_history) - live beobachtet: diese wurden bisher komplett
    # aus Investiert/Wert rausgelassen, obwohl ihr AKTUELLER Kurs (über
    # Scalable selbst, nicht Yahoo, siehe scalable_sync.py) längst bekannt
    # ist. Bei 11 von 15 Positionen betroffen ist "Investiert" dadurch von
    # ~600€ auf ~97€ eingebrochen - deutlich sichtbar falsch statt nur
    # "ein bisschen unvollständig".
    no_history_holdings = []
    partial = False
    for h in holdings:
        if not h.lots:
            continue
        asset_type = h.asset_type.value if hasattr(h.asset_type, "value") else h.asset_type
        try:
            points = get_cached_history(db, asset_type, h.symbol, range_key)
        except Exception:
            partial = True
            no_history_holdings.append(h)
            continue
        # get_cached_history wirft seit dem negativen Caching (siehe dort) bei
        # einem fehlgeschlagenen Live-Abruf keine Exception mehr, sondern gibt
        # [] zurück - der except-Zweig oben greift also praktisch nie mehr für
        # diesen Fall. "partial" trotzdem hier setzen, sonst verschwindet der
        # Hinweis für dauerhaft kaputte Symbole (z.B. ISIN statt Yahoo-Ticker
        # bei manchen Scalable-Capital-Positionen) einfach kommentarlos.
        if not points:
            partial = True
            no_history_holdings.append(h)
            continue
        series_by_holding[h.id] = {
            "prices_by_date": dict(points),
            "dates": [p[0] for p in points],
            "lots": sorted(h.lots, key=lambda l: (l.date, l.id)),
        }

    if not series_by_holding and not no_history_holdings:
        return schemas.PortfolioHistoryOut(points=[], partial=partial)

    all_dates = sorted({d for s in series_by_holding.values() for d in s["dates"]})
    today_str = date.today().isoformat()
    # Sicherstellen, dass der heutige Stichtag immer als letzter Punkt
    # existiert, auch wenn keine der Kurshistorien-Serien selbst schon
    # einen heutigen Eintrag hat - genau an diesem Punkt werden unten die
    # Positionen ohne Kurshistorie mit ihrem aktuellen Preis ergänzt.
    if not all_dates or all_dates[-1] != today_str:
        all_dates.append(today_str)
    last_price: dict[int, float | None] = {hid: None for hid in series_by_holding}
    result_points = []
    for d in all_dates:
        d_date = date.fromisoformat(d)
        total_value, total_invested = 0.0, 0.0
        for hid, s in series_by_holding.items():
            if d in s["prices_by_date"]:
                last_price[hid] = s["prices_by_date"][d]
            price = last_price[hid]
            qty, cost = _position_at(s["lots"], d_date)
            total_invested += cost
            if price is not None:
                total_value += qty * price
        # Positionen ohne Kurshistorie NUR am heutigen Stichtag mit ihrem
        # aktuellen Preis einrechnen (für frühere Tage fehlt uns schlicht
        # die Kursdaten-Grundlage) - gleicher current_price-Fallback wie
        # holding_out(), damit das zur Holdings-Tabelle/net-worth passt.
        if d == today_str:
            for h in no_history_holdings:
                qty, cost = _position_at(sorted(h.lots, key=lambda l: (l.date, l.id)), d_date)
                total_invested += cost
                current = h.current_price if h.current_price is not None else h.purchase_price
                total_value += qty * current
        return_pct = round((total_value - total_invested) / total_invested * 100, 2) if total_invested else None
        result_points.append(schemas.PortfolioHistoryPoint(
            date=d, value=round(total_value, 2), invested=round(total_invested, 2), return_pct=return_pct,
        ))

    return schemas.PortfolioHistoryOut(points=result_points, partial=partial)
