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
import re
import subprocess
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from . import models, crud, schemas

SC_BINARY = "sc"


def _normalize_name(name: str) -> str:
    """Fürs Dubletten-Matching per Name (siehe sync()) - Scalable liefert nur
    die ISIN, keinen Ticker, kann also nie direkt mit einer manuell per
    Ticker angelegten Position übereinstimmen. Kleinschreibung + nur
    alphanumerische Zeichen fängt Groß-/Kleinschreibung, Leerzeichen und
    Zusätze wie "(Acc)"/"(Dist)" ab, ohne diese extra pflegen zu müssen."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


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


def _find_by_name(candidates: list, item_name: str) -> models.Holding | None:
    """Sucht eine bereits vorhandene, manuell angelegte Position mit
    ähnlichem Namen (siehe sync()). Nicht auf exakte Gleichheit geprüft -
    live beobachtet, dass Scalable und eine von Hand eingetragene Bezeichnung
    fürs selbe Wertpapier unterschiedlich abgekürzt/großgeschrieben sein
    können (z.B. "Scottish Mortgage Invest" vs. "Scottish Mortgage
    Investment Trust", "SUPERQ QUANTUM COMPUTING INC." vs. "SuperQ Quantum
    Computing") - ein Teilstring-Vergleich in beide Richtungen fängt das ab,
    exakte Gleichheit hätte diese Fälle sonst übersehen."""
    norm_item = _normalize_name(item_name)
    for h in candidates:
        norm_h = _normalize_name(h.name)
        if norm_h and (norm_h in norm_item or norm_item in norm_h):
            return h
    return None


def sync(db: Session, settings: models.Settings, space_id: int) -> dict:
    holdings_data = _run_sc("broker", "holdings")
    all_holdings = crud.get_holdings(db, space_id)
    holdings_by_isin = {h.symbol: h for h in all_holdings if h.symbol}
    # Fürs einmalige "Adoptieren" einer schon vorhandenen, manuell per Ticker
    # angelegten Position (siehe unten) - bewusst nur unter rein manuell
    # angelegten Positionen suchen (import_source is None), nicht unter
    # Bitvavo-verwalteten: eine andere Anbindung/Anlageklasse soll nie per
    # Namensähnlichkeit von Scalable "gekapert" werden können. Wird bei jeder
    # Adoption sofort entfernt (siehe unten), damit zwei unterschiedliche
    # Scalable-Positionen nie um dieselbe manuelle Position konkurrieren.
    unmatched_manual = [h for h in all_holdings if h.import_source is None]

    created, updated, adopted = 0, 0, 0
    for item in holdings_data.get("items", []):
        isin = item.get("isin")
        if not isin:
            continue
        asset_type = SECURITY_TYPE_TO_ASSET_TYPE.get(item.get("security_type"), models.AssetType.sonstiges)
        current_price = item.get("quote_mid_price")
        item_name = item.get("name") or isin

        existing = holdings_by_isin.get(isin)
        name_match = _find_by_name(unmatched_manual, item_name) if not existing else None
        if existing:
            holding = existing
            updated += 1
        elif name_match:
            # Dieselbe reale Position wurde vor der Scalable-Anbindung schon
            # manuell angelegt (per Ticker statt ISIN, daher kein ISIN-Match) -
            # sonst entsteht bei jedem neuen Symbol eine Dublette derselben
            # Position (live beobachtet: 11 doppelte Positionen nach dem
            # ersten Sync, siehe Commit-Nachricht "Investments: Scalable-
            # Dubletten..."). Alte, von Hand ungenau erfasste Lots durch die
            # unten importierte, präzise Scalable-Transaktionshistorie
            # ersetzen statt beide Sätze zu addieren (sonst doppelt gezählt).
            holding = name_match
            unmatched_manual.remove(name_match)
            for lot in list(holding.lots):
                db.delete(lot)
            db.flush()
            holding.symbol = isin
            holdings_by_isin[isin] = holding
            adopted += 1
        else:
            # quantity=0 wie bei Bitvavo (siehe exchange_sync.py) - der
            # tatsächliche Bestand ergibt sich ausschließlich aus den unten
            # importierten Lots, nicht aus einem direkt gesetzten Wert.
            holding = crud.create_holding(db, schemas.HoldingCreate(
                asset_type=asset_type, name=item_name, symbol=isin,
                quantity=0, purchase_price=0.0,
            ), space_id)
            holdings_by_isin[isin] = holding
            created += 1
        holding.import_source = "scalable"
        if item.get("quote_currency"):
            holding.currency = item["quote_currency"]
        if current_price is not None:
            holding.current_price = current_price
            holding.price_updated_at = datetime.utcnow()

    # Alle Vorgangs-Typen, die den Bestand tatsaechlich veraendern - BUY/SELL
    # deckt NUR manuelle Einzelkaeufe/-verkaeufe ab, Sparplan-Ausfuehrungen
    # laufen als eigener Typ SAVINGS_PLAN (live geprueft: ein per --type-
    # filter BUY/SELL gefiltertes erstes Sync hatte alle Sparplan-ETFs mit
    # quantity=0 stehen gelassen, obwohl das Konto erst seit Mai besteht -
    # keine Zeitfenster-Frage, sondern ein fehlender Typ). SWAP_IN/OUT und
    # REINVESTMENT ebenfalls dazu, da auch die die Stueckzahl aendern.
    TX_TYPES_AFFECTING_QUANTITY = ["BUY", "SELL", "SAVINGS_PLAN", "SWAP_IN", "SWAP_OUT", "REINVESTMENT"]
    # Bei einer eben "adoptierten" Position (siehe oben) wurden die alten,
    # ungenauen manuellen Lots bereits geloescht - ein rein inkrementelles
    # Zeitfenster (seit dem letzten Sync) wuerde die Historie dieser Position
    # nicht neu auffuellen, sie bliebe bis zur naechsten echten Transaktion
    # bei quantity=0 haengen. Bei jeder Adoption deshalb die volle Historie
    # abfragen statt nur seit dem letzten Sync.
    from_time = (
        (settings.scalable_last_sync_at - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if settings.scalable_last_sync_at and not adopted else
        (datetime.utcnow() - timedelta(days=730)).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    lots_added = 0
    cursor = None
    for _page in range(20):  # Sicherheitsnetz gegen eine Endlosschleife bei kaputter Pagination
        args = ["broker", "transactions", "--page-size", "100", "--from-time", from_time]
        for t in TX_TYPES_AFFECTING_QUANTITY:
            args += ["--type-filter", t]
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

    # Eigener, unkritischer Schritt: gibt es dabei ein Problem, soll das den
    # eigentlichen Holdings-/Lots-Sync oben nicht mit reißen (siehe try/except).
    try:
        sync_savings_plans(db, space_id)
    except Exception:
        pass

    settings.scalable_last_sync_at = datetime.utcnow()
    settings.scalable_last_sync_status = (
        f"OK: {created} neu, {updated} aktualisiert"
        + (f", {adopted} mit bestehender Position zusammengeführt" if adopted else "")
        + f", {lots_added} Lot(s) importiert"
    )
    db.commit()
    return {"created": created, "updated": updated, "lots_added": lots_added, "error": None}


def sync_savings_plans(db: Session, space_id: int) -> int:
    """Synct die aktuell aktiven Scalable-Sparpläne (wiederkehrende Käufe -
    NICHT die bisherigen Ausführungen, die laufen weiterhin über sync() oben
    als eigene Lots) in eine eigene Tabelle (siehe models.SavingsPlan) -
    bewusst nicht als Holding mit quantity=0 modelliert: live beobachtet,
    dass genau das dazu geführt hat, dass ein Sparplan ohne bisherige
    Ausführung als verwirrende "0"-Zeile in der Holdings-Tabelle auftaucht.
    Ersetzt den kompletten Bestand je Aufruf (Upsert + Löschen nicht mehr
    gelisteter Pläne) - 'sc broker savings-plans' liefert immer den
    vollständigen aktuellen Stand, kein inkrementelles Delta."""
    result = _run_sc("broker", "savings-plans")
    items = result.get("items", [])
    seen_isins = set()
    synced = 0
    for item in items:
        isin = item.get("isin")
        if not isin or item.get("amount") is None:
            continue
        seen_isins.add(isin)
        plan = db.query(models.SavingsPlan).filter_by(space_id=space_id, isin=isin).first()
        next_exec_raw = item.get("next_execution_date")
        next_exec_date = datetime.strptime(next_exec_raw, "%Y-%m-%d").date() if next_exec_raw else None
        if plan:
            plan.name = item.get("name") or plan.name
            plan.amount = item["amount"]
            plan.frequency = item.get("frequency") or plan.frequency
            plan.day_of_month = item.get("day_of_month")
            plan.dynamization_rate = item.get("dynamization_rate")
            plan.next_execution_date = next_exec_date
            plan.security_type = item.get("security_type")
        else:
            db.add(models.SavingsPlan(
                space_id=space_id, isin=isin, name=item.get("name") or isin,
                amount=item["amount"], frequency=item.get("frequency") or "MONTHLY",
                day_of_month=item.get("day_of_month"), dynamization_rate=item.get("dynamization_rate"),
                next_execution_date=next_exec_date, security_type=item.get("security_type"),
            ))
        synced += 1
    # Nicht mehr gelistete Pläne (pausiert/gekündigt) hier ebenfalls entfernen -
    # sonst würden aufgehobene Sparpläne dauerhaft weiter angezeigt.
    for plan in db.query(models.SavingsPlan).filter_by(space_id=space_id).all():
        if plan.isin not in seen_isins:
            db.delete(plan)
    db.commit()
    return synced
