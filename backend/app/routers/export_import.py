"""Export/Import: Buchungen (CSV), Steuer-Export (CSV/PDF), Investments (CSV).

Neunzehnter Schritt der Code-Modularisierung (siehe ROADMAP.md), nach
investments/tax/debts/goals/trips/wishlist/personal/business_life/
budgets_alerts/deadlines/calendar_todos/categories/immich_routes/
bank_connections/enablebanking_ebay/mail_routes/spaces_accounts/
backup_restore.

`HOLDING_ASSET_TYPE_ALIASES` (ohne führenden Unterstrich wie die anderen
Konstanten hier, war vorher schon so benannt) wird auch von main.beleg_chat
gebraucht (KI-Chat kann Positionen direkt anlegen), deshalb exportiert und
in main.py zurückimportiert - gleiches Muster wie goal_out/
immich_credentials/run_mail_sync/write_backup_to_disk."""

import csv
import io
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from .. import models, schemas, crud, auth, tax_export
from ..database import get_db

export_import_router = APIRouter(prefix="/api")


# ---------------- Export / Import ----------------
@export_import_router.get("/export/transactions.csv")
def export_transactions_csv(
    account_id: Optional[int] = None,
    category_id: Optional[int] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    transactions = crud.get_transactions(db, space_id, account_id, category_id, year, month, search)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Datum", "Betrag", "Konto", "Kategorie", "Beschreibung", "Notiz"])
    for t in transactions:
        writer.writerow([
            t.date.isoformat(),
            f"{t.amount:.2f}".replace(".", ","),
            t.account.name if t.account else "",
            t.category.name if t.category else "",
            t.description or "",
            t.notes or "",
        ])
    filename = f"buchungen_{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _tax_export_subtitle(date_from: Optional[date], date_to: Optional[date], is_business: Optional[bool]) -> str:
    parts = []
    if date_from or date_to:
        von = date_from.strftime("%d.%m.%Y") if date_from else "…"
        bis = date_to.strftime("%d.%m.%Y") if date_to else "…"
        parts.append(f"{von} – {bis}")
    if is_business is not None:
        parts.append("Geschäftlich" if is_business else "Privat")
    return " · ".join(parts)


@export_import_router.get("/export/tax.csv")
def export_tax_csv(
    date_from: Optional[date] = None, date_to: Optional[date] = None,
    account_id: Optional[int] = None, category_id: Optional[int] = None,
    is_business: Optional[bool] = None,
    db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id),
):
    transactions = crud.get_transactions_for_export(db, space_id, date_from, date_to, account_id, category_id, is_business)
    csv_text = tax_export.build_csv(transactions)
    filename = f"steuer-export_{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@export_import_router.get("/export/tax.pdf")
def export_tax_pdf(
    date_from: Optional[date] = None, date_to: Optional[date] = None,
    account_id: Optional[int] = None, category_id: Optional[int] = None,
    is_business: Optional[bool] = None,
    db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id),
):
    transactions = crud.get_transactions_for_export(db, space_id, date_from, date_to, account_id, category_id, is_business)
    pdf_bytes = tax_export.build_pdf(
        transactions, title="Kies – Buchungsexport",
        subtitle=_tax_export_subtitle(date_from, date_to, is_business),
    )
    filename = f"steuer-export_{date.today().isoformat()}.pdf"
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@export_import_router.post("/import/transactions")
def import_transactions_csv(file: UploadFile = File(...), db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    raw = file.file.read().decode("utf-8-sig")
    delimiter = ";" if raw.split("\n", 1)[0].count(";") >= raw.split("\n", 1)[0].count(",") else ","
    reader = list(csv.reader(io.StringIO(raw), delimiter=delimiter))
    if not reader:
        raise HTTPException(400, "Leere Datei")

    header = [h.strip().lower() for h in reader[0]]
    accounts_by_name = {a.name.lower(): a for a in crud.get_accounts(db, space_id)}
    categories_by_name = {c.name.lower(): c for c in crud.get_categories(db)}

    imported, skipped, errors = 0, 0, []
    for i, row in enumerate(reader[1:], start=2):
        if not row or not any(cell.strip() for cell in row):
            continue
        data = dict(zip(header, row))
        try:
            acc = accounts_by_name.get((data.get("konto") or "").strip().lower())
            if not acc:
                raise ValueError(f"Konto '{data.get('konto', '')}' nicht gefunden")
            cat = categories_by_name.get((data.get("kategorie") or "").strip().lower())
            amount = float((data.get("betrag") or "0").replace(",", "."))
            tx_date = date.fromisoformat(data["datum"].strip())
            crud.create_transaction(db, schemas.TransactionCreate(
                date=tx_date, amount=amount, account_id=acc.id,
                category_id=cat.id if cat else None,
                description=(data.get("beschreibung") or None),
                notes=(data.get("notiz") or None),
            ))
            imported += 1
        except Exception as e:
            # Nur Fehlertyp + Nachricht statt roher Exception-Repraesentation
            # (koennte interne Details enthalten - CodeQL: py/stack-trace-exposure).
            # Bleibt fuer den Import des eigenen CSVs nuetzlich.
            errors.append(f"Zeile {i}: {type(e).__name__}: {e}")
            skipped += 1

    return {"imported": imported, "skipped": skipped, "errors": errors}


# ---------------- Export / Import: Investments ----------------
HOLDING_ASSET_TYPE_ALIASES = {
    "aktie": models.AssetType.aktie,
    "etf": models.AssetType.etf,
    "anleihe": models.AssetType.anleihe,
    "krypto": models.AssetType.krypto,
    "sonstiges": models.AssetType.sonstiges,
}


@export_import_router.get("/export/holdings.csv")
def export_holdings_csv(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    holdings = crud.get_holdings(db, space_id)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Anlageklasse", "Name", "Symbol", "Sektor", "Stückzahl", "Kaufpreis", "Kaufdatum"])
    for h in holdings:
        writer.writerow([
            h.asset_type.value,
            h.name,
            h.symbol,
            h.sector or "",
            f"{h.quantity}".replace(".", ","),
            f"{h.purchase_price:.4f}".replace(".", ","),
            h.purchase_date.isoformat() if h.purchase_date else "",
        ])
    filename = f"positionen_{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@export_import_router.post("/import/holdings")
def import_holdings_csv(file: UploadFile = File(...), db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    raw = file.file.read().decode("utf-8-sig")
    delimiter = ";" if raw.split("\n", 1)[0].count(";") >= raw.split("\n", 1)[0].count(",") else ","
    reader = list(csv.reader(io.StringIO(raw), delimiter=delimiter))
    if not reader:
        raise HTTPException(400, "Leere Datei")

    header = [h.strip().lower() for h in reader[0]]
    existing = {(h.asset_type, h.symbol.lower()): h for h in crud.get_holdings(db, space_id)}

    created, added_lots, skipped, errors = 0, 0, 0, []
    for i, row in enumerate(reader[1:], start=2):
        if not row or not any(cell.strip() for cell in row):
            continue
        data = dict(zip(header, row))
        try:
            asset_type = HOLDING_ASSET_TYPE_ALIASES.get((data.get("anlageklasse") or "").strip().lower())
            if not asset_type:
                raise ValueError(f"Unbekannte Anlageklasse '{data.get('anlageklasse', '')}' (aktie/etf/anleihe/krypto/sonstiges)")
            name = (data.get("name") or "").strip()
            symbol = (data.get("symbol") or "").strip()
            if not name or not symbol:
                raise ValueError("Name und Symbol erforderlich")
            quantity = float((data.get("stückzahl") or "0").replace(",", "."))
            purchase_price = float((data.get("kaufpreis") or "0").replace(",", "."))
            purchase_date_raw = (data.get("kaufdatum") or "").strip()
            purchase_date = date.fromisoformat(purchase_date_raw) if purchase_date_raw else None
            sector = (data.get("sektor") or "").strip() or None

            key = (asset_type, symbol.lower())
            if key in existing:
                h = existing[key]
                crud.create_lot(db, h.id, space_id, schemas.HoldingLotCreate(
                    date=purchase_date or date.today(), type=models.LotType.kauf,
                    quantity=quantity, price_per_unit=purchase_price,
                ))
                added_lots += 1
            else:
                h = crud.create_holding(db, schemas.HoldingCreate(
                    asset_type=asset_type, name=name, symbol=symbol, sector=sector,
                    quantity=quantity, purchase_price=purchase_price, purchase_date=purchase_date,
                ), space_id)
                existing[key] = h
                created += 1
        except Exception as e:
            # Nur Fehlertyp + Nachricht statt roher Exception-Repraesentation
            # (koennte interne Details enthalten - CodeQL: py/stack-trace-exposure).
            # Bleibt fuer den Import des eigenen CSVs nuetzlich.
            errors.append(f"Zeile {i}: {type(e).__name__}: {e}")
            skipped += 1

    return {"created": created, "added_lots": added_lots, "skipped": skipped, "errors": errors}
