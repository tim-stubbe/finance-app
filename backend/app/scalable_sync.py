"""Investments-Anbindung an Scalable Capital über das offizielle CLI-Binary
"sc" (siehe https://github.com/ScalableCapital/scalable-cli) - Scalable
bietet kein klassisches REST-API für Endnutzer, nur dieses Rust-Binary.

Login läuft bewusst NICHT durch Kies selbst: `sc login` ist ein Device-Code-
Flow, der laut Scalable-Doku "human-oriented" bleiben soll ("complete login
yourself rather than via an AI agent") - Kies sieht nie ein Passwort oder
Secret, die Session liegt als Datei unter $XDG_CONFIG_HOME/scalable-cli/
(im Docker-Image auf /data/scalable-cli-home gemappt, siehe Dockerfile,
übersteht damit Container-Neustarts/Redeploys). Der Login muss einmalig
manuell im laufenden Container nachgeholt werden (`docker exec -it ...
sc login --local-read-only`) - Kies selbst kann und soll diesen Schritt
nicht automatisieren.

Analog zu exchange_sync.py (Bitvavo): echte Käufe/Verkäufe aus der
Transaktionshistorie werden als HoldingLot importiert statt nur den
aktuellen Bestand zu übernehmen - dieselbe (Datum, Menge, Preis)-Dedup-Logik
verhindert doppelte Lots bei wiederholten Syncs, macht inkrementelle Syncs
über --from-time robust."""

import json
import subprocess
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from . import models, crud, schemas

SC_BINARY = "sc"

SECURITY_TYPE_TO_ASSET_TYPE = {
    "STOCK": models.AssetType.aktie,
    "ETF": models.AssetType.etf,
    "BOND": models.AssetType.anleihe,
    "CRYPTO": models.AssetType.krypto,
}


def _run_sc(*args: str) -> dict:
    """Ruft `sc <args> --json` auf und liefert `data.result` aus der
    JSON-Hülle (siehe capabilities-Ausgabe: `"output":"json_envelope"`).
    Wirft eine aussagekräftige Fehlermeldung statt eines rohen
    CalledProcessError, u.a. für den häufigsten Fall: noch nicht
    eingeloggt (auth_or_config_error, Exit-Code 20)."""
    try:
        result = subprocess.run(
            [SC_BINARY, *args, "--json"], capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        raise RuntimeError("Scalable-CLI ('sc') ist auf diesem System nicht installiert.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Scalable-CLI hat nicht rechtzeitig geantwortet (Timeout).")

    if not result.stdout.strip():
        if result.returncode == 20:
            raise RuntimeError("Nicht eingeloggt - einmalig 'sc login' im Container nachholen (siehe ROADMAP).")
        raise RuntimeError(result.stderr.strip() or f"'sc {' '.join(args)}' lieferte keine Antwort (Exit {result.returncode}).")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Unerwartete Antwort von 'sc {' '.join(args)}': {result.stdout[:200]}")
    if not data.get("ok"):
        raise RuntimeError(str(data.get("error") or data))
    return data["data"]["result"]


def is_logged_in() -> bool:
    try:
        _run_sc("whoami")
        return True
    except Exception:
        return False


def sync(db: Session, settings: models.Settings, space_id: int) -> dict:
    holdings_data = _run_sc("broker", "holdings")
    holdings_by_isin = {h.symbol: h for h in crud.get_holdings(db, space_id) if h.symbol}

    created, updated = 0, 0
    for item in holdings_data.get("items", []):
        isin = item.get("isin")
        if not isin:
            continue
        asset_type = SECURITY_TYPE_TO_ASSET_TYPE.get(item.get("security_type"), models.AssetType.sonstiges)
        current_price = item.get("quote_mid_price")

        existing = holdings_by_isin.get(isin)
        if existing:
            holding = existing
            updated += 1
        else:
            # quantity=0 wie bei Bitvavo (siehe exchange_sync.py) - der
            # tatsächliche Bestand ergibt sich ausschließlich aus den unten
            # importierten Lots, nicht aus einem direkt gesetzten Wert.
            holding = crud.create_holding(db, schemas.HoldingCreate(
                asset_type=asset_type, name=item.get("name") or isin, symbol=isin,
                quantity=0, purchase_price=0.0,
            ), space_id)
            holdings_by_isin[isin] = holding
            created += 1
        if current_price is not None:
            holding.current_price = current_price
            holding.price_updated_at = datetime.utcnow()

    # Nur echte Wertpapier-Käufe/-Verkäufe für Lots - Sparplan-Ausführungen
    # laufen ebenfalls über BUY (siehe security_transaction_type=SAVINGS_PLAN
    # in der Testantwort), zählen hier also mit dazu, das ist gewollt (auch
    # ein Sparplan-Kauf ist ein echter Lot).
    from_time = (
        (settings.scalable_last_sync_at - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if settings.scalable_last_sync_at else
        (datetime.utcnow() - timedelta(days=730)).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    lots_added = 0
    cursor = None
    for _page in range(20):  # Sicherheitsnetz gegen eine Endlosschleife bei kaputter Pagination
        args = [
            "broker", "transactions", "--page-size", "100",
            "--type-filter", "BUY", "--type-filter", "SELL", "--from-time", from_time,
        ]
        if cursor:
            args += ["--cursor", cursor]
        page = _run_sc(*args)
        for tx in page.get("items", []):
            if tx.get("type") != "SECURITY_TRANSACTION" or tx.get("status") != "SETTLED" or tx.get("is_cancellation"):
                continue
            isin = tx.get("isin")
            quantity = tx.get("quantity")
            amount = tx.get("amount")
            if not isin or not quantity or amount is None:
                continue
            holding = holdings_by_isin.get(isin)
            if not holding:
                continue  # Position nicht (mehr) im Depot - keine verwaiste Lot-Historie anlegen
            price_per_unit = abs(amount) / quantity
            tx_date = datetime.fromisoformat(tx["last_event_datetime"].replace("Z", "+00:00")).date()

            known = {
                (l.date, round(l.quantity, 6), round(l.price_per_unit, 6))
                for l in holding.lots if l.type in (models.LotType.kauf, models.LotType.verkauf)
            }
            key = (tx_date, round(quantity, 6), round(price_per_unit, 6))
            if key in known:
                continue
            lot_type = models.LotType.kauf if tx.get("side") == "BUY" else models.LotType.verkauf
            crud.create_lot(db, holding.id, space_id, schemas.HoldingLotCreate(
                date=tx_date, type=lot_type, quantity=quantity, price_per_unit=price_per_unit,
            ))
            lots_added += 1
        cursor = page.get("cursor")
        if not cursor or not page.get("items"):
            break

    settings.scalable_last_sync_at = datetime.utcnow()
    settings.scalable_last_sync_status = f"OK: {created} neu, {updated} aktualisiert, {lots_added} Lot(s) importiert"
    db.commit()
    return {"created": created, "updated": updated, "lots_added": lots_added, "error": None}
