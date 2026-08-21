"""KI-Assistent (Ollama): Portfolio-Einschaetzung, fehlende Belege,
Beleg-Chat (Bild/PDF/Text -> Buchung oder Investment-Position), freier
Chat-Assistent mit Web-Suche und Vorschlags-Erkennung (Buchung,
Kategorie-Aenderung, Umbuchung, Schulden-Eintrag).

Sechsundzwanzigster Schritt der Code-Modularisierung (siehe ROADMAP.md),
nach investments/tax/debts/goals/trips/wishlist/personal/business_life/
budgets_alerts/deadlines/calendar_todos/categories/immich_routes/
bank_connections/enablebanking_ebay/mail_routes/spaces_accounts/
backup_restore/export_import/analytics/settings_misc/notify_settings/
dashboard/profile_ollama/sync_all. Der bisher letzte, mit Abstand
groesste und am staerksten intern verzahnte main.py-Abschnitt (mehrere
lokale Helfer, die NUR innerhalb dieses Blocks gebraucht werden) - deshalb
bis hierher bewusst zurueckgestellt statt frueh mit angefasst.

`websearch_configured`/`websearch_run` (ohne fuehrenden Unterstrich)
werden auch von main.integrations_status und einem main.py-Scheduler-Job
(Digest) gebraucht, deshalb exportiert und in main.py zurueckimportiert -
gleiches Muster wie goal_out/immich_credentials/run_mail_sync/
write_backup_to_disk/HOLDING_ASSET_TYPE_ALIASES/sync_all_connections.

UPLOAD_DIR eigenstaendig berechnet statt aus main importiert (main.py
importiert diesen Router beim Start VOR der Stelle, an der main.UPLOAD_DIR
definiert wird, siehe mail_routes.py-Docstring)."""

import base64
import json
import os
import re
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import models, schemas, crud, auth, bank_sync, document_extract, ollama_client, websearch
from ..database import get_db, DATA_DIR
from .export_import import HOLDING_ASSET_TYPE_ALIASES
from .mail_routes import find_receipt_matches

UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

ai_assistant_router = APIRouter(prefix="/api")


def _build_portfolio_insight_prompt(db: Session, space_id: int) -> str:
    net_worth = crud.net_worth(db, space_id)
    holdings = [crud.holding_out(h) for h in crud.get_holdings(db, space_id)]
    diversification = crud.portfolio_diversification(db, space_id)

    lines = [
        "Du bist ein nüchterner, hilfreicher Finanzassistent für Kies, ein privates Finanztool.",
        "Gib eine kurze Einschätzung auf Deutsch (max. 180 Wörter, Fließtext oder kurze Stichpunkte).",
        "Keine Anlageberatung, keine Kauf-/Verkaufsempfehlungen - nur Beobachtungen zu Struktur, Konzentration und Entwicklung.",
        "",
        f"Gesamtvermögen: {net_worth.total:.2f} EUR (Konten: {net_worth.accounts_total:.2f} EUR, Investments: {net_worth.investments_total:.2f} EUR)",
        "",
        "Positionen:",
    ]
    for h in holdings:
        asset_type_label = h.asset_type.value if hasattr(h.asset_type, "value") else h.asset_type
        lines.append(
            f"- {h.name} ({asset_type_label}, Sektor: {h.sector or 'unbekannt'}): "
            f"Wert {h.current_value:.2f} EUR, Gewinn/Verlust {h.gain_pct:.1f}%, Risiko {h.risk_level}"
        )
    lines.append("")
    lines.append("Verteilung nach Anlageklasse: " + ", ".join(f"{s.label} {s.percent:.0f}%" for s in diversification.by_asset_type))
    lines.append("Verteilung nach Sektor: " + ", ".join(f"{s.label} {s.percent:.0f}%" for s in diversification.by_sector))
    if diversification.risk_flags:
        lines.append("Bereits erkannte Risikohinweise: " + "; ".join(f.message for f in diversification.risk_flags))
    return "\n".join(lines)


@ai_assistant_router.post("/ai/portfolio-insight", response_model=schemas.AiTextResult)
def portfolio_insight(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    settings = auth.get_or_create_settings(db)
    if not settings.ollama_url or not settings.ollama_model:
        raise HTTPException(400, "Bitte zuerst Ollama-Server-URL und Modell in den Einstellungen hinterlegen")
    prompt = _build_portfolio_insight_prompt(db, space_id)
    try:
        text = ollama_client.generate(settings.ollama_url, settings.ollama_model, prompt)
    except Exception as e:
        return schemas.AiTextResult(text=None, error=str(e))
    return schemas.AiTextResult(text=text, error=None)


@ai_assistant_router.get("/ai/missing-receipts", response_model=schemas.MissingReceiptsOut)
def missing_receipts(min_amount: float = 20.0, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    transactions = crud.transactions_missing_receipt(db, space_id, min_amount)
    total = round(sum(abs(t.amount) for t in transactions), 2)

    summary = None
    settings = auth.get_or_create_settings(db)
    if settings.ollama_url and settings.ollama_model and transactions:
        lines = [
            "Du bist ein freundlicher Finanzassistent für Kies, ein privates Finanztool.",
            f"Der Nutzer hat {len(transactions)} Ausgabe(n) ohne hinterlegten Beleg im Gesamtwert von {total:.2f} EUR.",
            "Hier die Liste (Datum, Betrag, Beschreibung):",
        ]
        for t in transactions[:30]:
            lines.append(f"- {t.date}: {abs(t.amount):.2f} EUR, {t.description or 'ohne Beschreibung'}")
        lines.append("")
        lines.append(
            "Schreib einen kurzen, freundlichen Hinweis auf Deutsch (2-4 Sätze), der auffällige Muster nennt "
            "(z.B. Kategorie/Zeitraum falls erkennbar) und motiviert, die Belege nachzutragen."
        )
        try:
            summary = ollama_client.generate(settings.ollama_url, settings.ollama_model, "\n".join(lines))
        except Exception:
            summary = None

    return schemas.MissingReceiptsOut(transactions=transactions, total_amount=total, summary=summary)


# ---------------- Beleg-Chat (Bild/PDF/Text -> Buchung oder Investment-Position) ----------------
BELEG_CHAT_SYSTEM_PROMPT = """Du bist ein Assistent in Kies, einem privaten Finanztool, der Belege, Kassenbons, \
Wertpapier-Abrechnungen und Kontoauszüge ausliest, die der Nutzer als Bild, PDF oder Text schickt. \
Antworte immer kurz und freundlich auf Deutsch.

Wenn du EINDEUTIG eine Buchung (Ausgabe/Einnahme auf einem Konto) oder einen \
Wertpapier-/Krypto-Kauf, -Verkauf, Staking-Ertrag oder eine Dividende erkennst, gib am ENDE deiner \
Antwort zusätzlich für JEDEN erkannten Vorgang einen eigenen JSON-Block in dreifachen Backticks mit "json" aus. \
Enthält das Dokument z.B. mehrere Zeilen eines Kontoauszugs oder mehrere Positionen einer Abrechnung, \
gib entsprechend MEHRERE JSON-Blöcke hintereinander aus (einen pro Vorgang), nicht nur einen.

Für eine Kontobuchung:
```json
{"type": "transaction", "date": "YYYY-MM-DD", "amount": -12.34, "description": "Rewe", "category": "Lebensmittel", "notes": null}
```
(amount negativ = Ausgabe, positiv = Einnahme; category ist dein bester Vorschlag für eine Kategorie, z.B. "Lebensmittel", "Miete", "Gehalt")

Für einen Investment-Vorgang:
```json
{"type": "holding_lot", "asset_type": "aktie", "name": "Apple Inc", "symbol": "AAPL", "lot_type": "kauf", "date": "YYYY-MM-DD", "quantity": 1.5, "price_per_unit": 150.20}
```
(asset_type: aktie/etf/anleihe/krypto/sonstiges, lot_type: kauf/verkauf/staking/dividende)

Bist du dir NICHT sicher oder fehlen wichtige Angaben (z.B. Betrag oder Datum), gib für diesen Vorgang KEINEN JSON-Block aus, \
sondern frag im Text konkret nach den fehlenden Angaben. Erkennst du keine Buchung/keinen Investment-Vorgang, \
gib ebenfalls keinen JSON-Block aus - antworte dann nur im Fließtext."""

_JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_beleg_proposals(reply: str, allowed_types=("transaction", "holding_lot")) -> list[dict]:
    proposals = []
    for match in _JSON_BLOCK_RE.findall(reply):
        try:
            data = json.loads(match)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("type") in allowed_types:
            proposals.append(data)
    return proposals


def _resolve_described_transaction(db: Session, space_id: int, payload: dict) -> tuple[Optional[dict], Optional[str]]:
    """Löst eine von der KI nur beschriebene Buchung (Datum/Betrag/Beschreibung) auf
    eine konkrete Buchung in der Datenbank auf - die KI kennt keine internen IDs.
    Genau ein Treffer wird akzeptiert, sonst wird die Aktion nicht angeboten."""
    try:
        tx_date = date.fromisoformat(str(payload.get("date")))
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        return None, "Datum oder Betrag der gemeinten Buchung ist unklar."
    matches = _find_duplicate_matches(db, space_id, amount, tx_date, tolerance_days=3)
    if not matches:
        return None, "Keine passende Buchung gefunden (Datum/Betrag prüfen)."
    if len(matches) > 1:
        return None, f"{len(matches)} Buchungen passen auf Datum und Betrag - bitte genauer beschreiben."
    return matches[0], None


def _find_duplicate_matches(db: Session, space_id: int, amount: float, tx_date: date, tolerance_days: int = 1) -> list[dict]:
    """Bereits existierende Buchungen, die zu einem neuen Vorschlag verdächtig ähnlich sind (möglicher Doppel-Eintrag)."""
    matches = []
    for t in crud.get_transactions(db, space_id):
        if abs(t.amount - amount) > 0.01:
            continue
        if abs((t.date - tx_date).days) > tolerance_days:
            continue
        matches.append({"id": t.id, "date": t.date.isoformat(), "amount": t.amount, "description": t.description})
    return matches


@ai_assistant_router.post("/ai/beleg-chat", response_model=schemas.BelegChatResult)
def beleg_chat(
    message: str = Form(""),
    history: str = Form("[]"),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    settings = auth.get_or_create_settings(db)
    chat_model = settings.beleg_chat_model or settings.ollama_model
    if not settings.ollama_url or not chat_model:
        raise HTTPException(400, "Bitte zuerst Ollama-Server-URL und Modell in den Einstellungen hinterlegen")

    try:
        hist = json.loads(history)
        if not isinstance(hist, list):
            hist = []
    except json.JSONDecodeError:
        hist = []

    messages = [{"role": "system", "content": BELEG_CHAT_SYSTEM_PROMPT}]
    for m in hist:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": str(m["content"])})

    attachment_filename = None
    attachment_b64 = None
    user_content = message or "(kein Text, siehe Anhang)"
    images: list[str] = []

    if file is not None:
        raw = file.file.read()
        attachment_filename = file.filename
        attachment_b64 = base64.b64encode(raw).decode()
        content_type = file.content_type or ""
        is_pdf = content_type == "application/pdf" or (file.filename or "").lower().endswith(".pdf")
        if is_pdf:
            try:
                text, pdf_images = document_extract.extract_pdf(raw)
            except Exception as e:
                return schemas.BelegChatResult(reply="", error=f"PDF konnte nicht gelesen werden: {e}")
            if text:
                user_content += f"\n\n[Inhalt des angehängten PDF]\n{text}"
            else:
                images.extend(pdf_images)
        elif content_type.startswith("image/"):
            images.append(base64.b64encode(raw).decode())

    user_msg = {"role": "user", "content": user_content}
    if images:
        user_msg["images"] = images
    messages.append(user_msg)

    try:
        reply_raw = ollama_client.chat(settings.ollama_url, chat_model, messages)
    except Exception as e:
        return schemas.BelegChatResult(reply="", error=str(e))

    proposals = _extract_beleg_proposals(reply_raw)
    for p in proposals:
        if p.get("type") != "transaction":
            continue
        try:
            p_date = date.fromisoformat(str(p.get("date")))
            p_amount = float(p.get("amount"))
        except (TypeError, ValueError):
            continue
        if file is not None:
            receipt_matches = find_receipt_matches(db, space_id, p_amount, p_date)
            if receipt_matches:
                p["receipt_matches"] = receipt_matches
        duplicate_matches = _find_duplicate_matches(db, space_id, p_amount, p_date)
        if duplicate_matches:
            p["duplicate_matches"] = duplicate_matches

    reply_clean = _JSON_BLOCK_RE.sub("", reply_raw).strip()
    if not reply_clean:
        reply_clean = (
            f"Ich habe {len(proposals)} Vorschlag/Vorschläge erkannt - bitte prüfen:" if proposals else reply_raw
        )

    return schemas.BelegChatResult(
        reply=reply_clean,
        proposals=proposals,
        attachment_filename=attachment_filename,
        attachment_base64=attachment_b64,
    )


def _beleg_field_as_str(value) -> Optional[str]:
    """Macht Freitext-Felder robust gegen KI-Ausgaben, die z.B. eine Liste statt
    eines einzelnen Strings liefern (empirisch bei kleinen Modellen beobachtet)."""
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or None
    text = str(value).strip()
    return text or None


@ai_assistant_router.post("/ai/beleg-chat/apply", response_model=schemas.BelegChatApplyResult)
def beleg_chat_apply(data: schemas.BelegChatApply, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    payload = data.data

    def _save_attachment(target_id: int) -> Optional[str]:
        if not (data.attachment_base64 and data.attachment_filename):
            return None
        ext = os.path.splitext(data.attachment_filename)[1]
        safe_name = f"{target_id}_{uuid.uuid4().hex}{ext}"
        try:
            raw = base64.b64decode(data.attachment_base64)
        except Exception:
            return None
        with open(os.path.join(UPLOAD_DIR, safe_name), "wb") as f:
            f.write(raw)
        return safe_name

    if data.type == "transaction":
        if not data.account_id or not crud.get_account(db, data.account_id, space_id):
            raise HTTPException(400, "Bitte ein gültiges Konto auswählen")
        try:
            tx_date = date.fromisoformat(str(payload.get("date")))
        except (ValueError, TypeError):
            raise HTTPException(400, "Ungültiges Datum")
        try:
            amount = float(payload.get("amount"))
        except (TypeError, ValueError):
            raise HTTPException(400, "Ungültiger Betrag")

        category_id = None
        category_name = _beleg_field_as_str(payload.get("category"))
        if category_name:
            match = next((c for c in crud.get_categories(db) if c.name.lower() == category_name.lower()), None)
            if match:
                category_id = match.id

        tx = crud.create_transaction(db, schemas.TransactionCreate(
            date=tx_date, amount=amount,
            description=_beleg_field_as_str(payload.get("description")),
            notes=_beleg_field_as_str(payload.get("notes")),
            account_id=data.account_id,
            category_id=category_id,
        ))
        receipt_name = _save_attachment(tx.id)
        if receipt_name:
            crud.set_receipt(db, tx.id, space_id, receipt_name)
        return schemas.BelegChatApplyResult(ok=True, transaction_id=tx.id, message="Buchung angelegt.")

    if data.type == "holding_lot":
        asset_type = HOLDING_ASSET_TYPE_ALIASES.get((payload.get("asset_type") or "").strip().lower())
        if not asset_type:
            raise HTTPException(400, "Unbekannte oder fehlende Anlageklasse (aktie/etf/anleihe/krypto/sonstiges)")
        symbol = (_beleg_field_as_str(payload.get("symbol")) or "").strip()
        name = (_beleg_field_as_str(payload.get("name")) or "").strip() or symbol
        if not symbol:
            raise HTTPException(400, "Symbol fehlt")
        try:
            lot_date = date.fromisoformat(str(payload.get("date")))
        except (ValueError, TypeError):
            raise HTTPException(400, "Ungültiges Datum")
        try:
            quantity = float(payload.get("quantity"))
            price_per_unit = float(payload.get("price_per_unit"))
        except (TypeError, ValueError):
            raise HTTPException(400, "Ungültige Stückzahl oder ungültiger Preis")
        try:
            lot_type = models.LotType(payload.get("lot_type") or "kauf")
        except ValueError:
            raise HTTPException(400, "Unbekannter Transaktionstyp (kauf/verkauf/staking/dividende)")

        existing = next(
            (h for h in crud.get_holdings(db, space_id) if h.asset_type == asset_type and h.symbol.lower() == symbol.lower()),
            None,
        )
        if existing:
            crud.create_lot(db, existing.id, space_id, schemas.HoldingLotCreate(
                date=lot_date, type=lot_type, quantity=quantity, price_per_unit=price_per_unit,
            ))
            holding_id = existing.id
            msg = f"Als weiterer Vorgang zu bestehender Position '{name}' hinzugefügt."
        else:
            h = crud.create_holding(db, schemas.HoldingCreate(
                asset_type=asset_type, name=name, symbol=symbol,
                quantity=quantity, purchase_price=price_per_unit, purchase_date=lot_date,
            ), space_id)
            holding_id = h.id
            msg = f"Neue Position '{name}' angelegt."
        return schemas.BelegChatApplyResult(ok=True, holding_id=holding_id, message=msg)

    if data.type == "attach_receipt":
        tx_id = payload.get("transaction_id")
        tx = crud.get_transaction(db, tx_id, space_id) if tx_id else None
        if not tx:
            raise HTTPException(400, "Buchung nicht gefunden")
        receipt_name = _save_attachment(tx.id)
        if not receipt_name:
            raise HTTPException(400, "Kein Anhang zum Speichern vorhanden")
        crud.set_receipt(db, tx.id, space_id, receipt_name)
        return schemas.BelegChatApplyResult(ok=True, transaction_id=tx.id, message="Beleg an bestehende Buchung angehängt.")

    if data.type == "update_category":
        tx_id = payload.get("transaction_id")
        tx = crud.get_transaction(db, tx_id, space_id) if tx_id else None
        if not tx:
            raise HTTPException(400, "Buchung nicht gefunden")
        category_name = _beleg_field_as_str(payload.get("category")) or ""
        match = next((c for c in crud.get_categories(db) if c.name.lower() == category_name.lower()), None)
        if not match:
            raise HTTPException(400, "Unbekannte Kategorie")
        tx.category_id = match.id
        db.commit()
        return schemas.BelegChatApplyResult(ok=True, transaction_id=tx.id, message=f"Kategorie auf „{match.name}“ gesetzt.")

    if data.type == "create_debt":
        try:
            original_amount = float(payload.get("original_amount"))
        except (TypeError, ValueError):
            raise HTTPException(400, "Ungültiger oder fehlender finanzierter Betrag")
        name = (_beleg_field_as_str(payload.get("name")) or "").strip()
        if not name:
            raise HTTPException(400, "Name fehlt")

        def _opt_date(key: str) -> Optional[date]:
            val = payload.get(key)
            try:
                return date.fromisoformat(str(val)) if val else None
            except ValueError:
                return None

        def _opt_float(key: str) -> Optional[float]:
            val = payload.get(key)
            try:
                return float(val) if val is not None and val != "" else None
            except (TypeError, ValueError):
                return None

        debt = crud.create_debt(db, schemas.DebtCreate(
            name=name,
            lender=_beleg_field_as_str(payload.get("lender")),
            original_amount=original_amount,
            interest_rate_percent=_opt_float("interest_rate_percent") or 0.0,
            monthly_payment=_opt_float("monthly_payment"),
            start_date=_opt_date("start_date"),
            planned_end_date=_opt_date("planned_end_date"),
            account_id=payload.get("resolved_account_id"),
            notes=_beleg_field_as_str(payload.get("notes")),
        ), space_id)

        payments_created = 0
        for pay in payload.get("payments") or []:
            if not isinstance(pay, dict):
                continue
            try:
                pay_date = date.fromisoformat(str(pay.get("date")))
                pay_amount = float(pay.get("total_amount"))
            except (TypeError, ValueError):
                continue
            interest_val = pay.get("interest_amount")
            try:
                interest_amount = float(interest_val) if interest_val is not None and interest_val != "" else None
            except (TypeError, ValueError):
                interest_amount = None
            crud.create_debt_payment(db, debt.id, space_id, schemas.DebtPaymentCreate(
                date=pay_date,
                total_amount=pay_amount,
                interest_amount=interest_amount,
                transaction_id=pay.get("resolved_transaction_id"),
                notes=_beleg_field_as_str(pay.get("notes")),
            ))
            payments_created += 1

        db.refresh(debt)
        return schemas.BelegChatApplyResult(
            ok=True, debt_id=debt.id,
            message=f"Schuld „{debt.name}“ angelegt ({payments_created} Zahlung(en) verknüpft, Restschuld {debt.current_balance:.2f} EUR).",
        )

    if data.type == "mark_transfer":
        tx_id = payload.get("transaction_id")
        tx = crud.get_transaction(db, tx_id, space_id) if tx_id else None
        if not tx:
            raise HTTPException(400, "Buchung nicht gefunden")
        tx.is_transfer = True
        tx.category_id = None
        db.commit()
        return schemas.BelegChatApplyResult(ok=True, transaction_id=tx.id, message="Als Umbuchung markiert - zählt nicht mehr als Einnahme/Ausgabe.")

    raise HTTPException(400, "Unbekannter Vorschlagstyp")


# ---------------- Assistant-Chat (schwebender KI-Button, allgemeine Anweisungen) ----------------
ASSISTANT_CHAT_SYSTEM_PROMPT = """Du bist der KI-Assistent von Kies, einem privaten Finanztool, erreichbar per Chat-Button \
auf jeder Seite der App. Der Nutzer gibt dir Anweisungen oder Fragen in normaler Sprache. Antworte immer kurz \
und freundlich auf Deutsch.

Du kannst VIER Arten von Vorschlägen machen, wenn eindeutig danach gefragt wird - dafür gibst du am Ende \
deiner Antwort einen JSON-Block in dreifachen Backticks mit "json" aus:

1. Neue Buchung anlegen:
```json
{"type": "transaction", "date": "YYYY-MM-DD", "amount": -12.34, "description": "Rewe", "category": "Lebensmittel", "notes": null}
```
(amount negativ = Ausgabe, positiv = Einnahme)

2. Eine bestehende Buchung, die der Nutzer beschreibt, einer Kategorie zuordnen (du kennst keine internen IDs, \
beschreibe die gemeinte Buchung daher so genau wie möglich anhand des Kontexts unten):
```json
{"type": "update_category", "date": "YYYY-MM-DD", "amount": -12.34, "description": "Rewe", "category": "Lebensmittel"}
```

3. Eine bestehende Buchung als Umbuchung zwischen zwei eigenen Konten markieren (zählt dann nicht mehr als \
Einnahme/Ausgabe):
```json
{"type": "mark_transfer", "date": "YYYY-MM-DD", "amount": -500.00, "description": "Überweisung"}
```

4. Eine Schuld/Ratenkauf anlegen (z.B. "PayPal Später bezahlen", Ratenkredit, Kleinkredit) - typischerweise, \
wenn der Nutzer einen Einkauf beschreibt, den er in festen Raten abbezahlt. Die eigentliche Kaufbuchung (der \
volle Betrag) ist meist schon als normale Buchung importiert - lass die unangetastet, hier geht es NUR um die \
Ratenzahlungsvereinbarung und die bereits geleisteten Raten:
```json
{"type": "create_debt", "name": "PayPal Später bezahlen – <Händler>", "lender": "PayPal",
 "account_description": "<Kontoname, über das die Raten laufen>", "original_amount": 604.98,
 "interest_rate_percent": 11.8, "monthly_payment": 28.42, "start_date": "2026-06-25",
 "planned_end_date": "2028-06-25", "notes": "24 Raten à 28,42€, gesamt 682,10€.",
 "payments": [
   {"date": "2026-07-09", "total_amount": 0.18, "notes": "Manuelle Zahlung"},
   {"date": "2026-07-25", "total_amount": 28.42, "interest_amount": 5.95, "notes": "Automatischer Einzug"}
 ]}
```
Regeln dafür: "original_amount" ist der tatsächliche Kaufpreis/finanzierte Betrag OHNE künftige Zinsen (nicht \
die Summe aller Raten). "interest_rate_percent" ist der effektive Jahreszins, falls genannt; ist nur der \
Zinsanteil EINER Zahlung bekannt (nicht der Jahreszins selbst), rechne ihn hoch (Zinsanteil × 12 ÷ original_amount \
× 100) und weise im Fließtext darauf hin, dass das eine Schätzung ist. Ist gar nichts zur Verzinsung bekannt, lass \
"interest_rate_percent" weg. "payments" enthält nur bereits tatsächlich geleistete Zahlungen (kann eine leere \
Liste sein) - "interest_amount" pro Zahlung nur setzen, wenn der Nutzer den Zinsanteil dieser konkreten Zahlung \
explizit genannt hat, sonst weglassen. Erfinde keine Zahlen, die nicht genannt wurden oder sich nicht eindeutig \
herleiten lassen - frag im Zweifel nach.

Für Fragen zum aktuellen Stand (Kontostand, Vermögen, Ausgaben) nutze NUR die unten mitgelieferten Fakten und \
antworte im Fließtext OHNE JSON-Block - erfinde keine Zahlen. Bist du dir bei einer Aktion nicht sicher oder \
fehlen wichtige Angaben, gib KEINEN JSON-Block aus und frag nach.

Du darfst außerdem im Internet suchen, wenn du für eine Frage aktuelle, recherchierbare Informationen brauchst \
(z.B. aktuelle Steuersätze/Freibeträge, Rechtslage, Zinssätze, aktuelle Nachrichten) - dein eigenes Wissen kann \
veraltet sein. Brauchst du das, antworte NUR mit einem Suchblock, sonst NICHTS (kein Fließtext davor/danach):
```search
<eine kurze, gezielte Suchanfrage>
```
Du bekommst danach Suchergebnisse und antwortest DANN im Fließtext basierend darauf. Nutze das gezielt, nicht bei \
jeder Frage - Fragen zu Beträgen/Kategorien/Buchungen etc. beantwortest du direkt.

Für Steuerfragen (z.B. "Leasing gewerblich oder privat absetzen"): gib eine fundierte Einschätzung inkl. der \
wichtigsten Rechenlogik, aber das ist KEINE verbindliche Steuerberatung - weise IMMER kurz darauf hin, dass der \
Nutzer das bei komplexen/hohen Beträgen mit einem Steuerberater absichern sollte."""


def _assistant_context(db: Session, space_id: int) -> str:
    """Fakten-Block, der dem System-Prompt angehängt wird, damit Fragen zum
    aktuellen Stand nicht halluziniert werden müssen."""
    accounts = crud.get_accounts(db, space_id)
    nw = crud.net_worth(db, space_id)
    lines = ["Aktueller Stand:"]
    for a in accounts:
        lines.append(f"- Konto „{a.name}“: {crud.account_balance(db, a):.2f} EUR")
    lines.append(f"- Investments gesamt: {nw.investments_total:.2f} EUR")
    if nw.debts_total:
        lines.append(f"- Offene Schulden: {nw.debts_total:.2f} EUR")
    lines.append(f"- Nettovermögen: {nw.total:.2f} EUR")
    debts = crud.get_debts(db, space_id)
    if debts:
        lines.append("Vorhandene Schulden/Ratenkäufe: " + ", ".join(
            f"„{d.name}“ ({d.current_balance:.2f} EUR offen)" for d in debts if d.status == models.DebtStatus.active
        ))
    categories = crud.get_categories(db)
    if categories:
        lines.append("Vorhandene Kategorien: " + ", ".join(c.name for c in categories))
    return "\n".join(lines)


ASSISTANT_PROPOSAL_TYPES = ("transaction", "update_category", "mark_transfer", "create_debt")


def _resolve_debt_proposal(db: Session, space_id: int, p: dict) -> None:
    """Löst account_description auf ein echtes Konto auf und versucht, jede
    genannte Zahlung einer bereits importierten Buchung zuzuordnen (die KI kennt
    keine internen Konto-/Buchungs-IDs). Buchungen ohne eindeutigen Treffer werden
    trotzdem angelegt, nur ohne Verknüpfung."""
    account_desc = (p.get("account_description") or "").strip().lower()
    account = None
    if account_desc:
        account = next(
            (a for a in crud.get_accounts(db, space_id) if account_desc in a.name.lower() or a.name.lower() in account_desc),
            None,
        )
    p["resolved_account_id"] = account.id if account else None
    p["resolved_account_name"] = account.name if account else None

    for payment in p.get("payments") or []:
        if not isinstance(payment, dict):
            continue
        try:
            pay_date = date.fromisoformat(str(payment.get("date")))
            amount = float(payment.get("total_amount"))
        except (TypeError, ValueError):
            continue
        candidates = [
            t for t in crud.get_transactions(db, space_id)
            if (not account or t.account_id == account.id)
            and abs(abs(t.amount) - abs(amount)) < 0.01
            and abs((t.date - pay_date).days) <= 3
        ]
        if len(candidates) == 1:
            t = candidates[0]
            payment["resolved_transaction_id"] = t.id
            payment["resolved_transaction_label"] = f"{t.date.isoformat()} · {t.amount:.2f} EUR · {t.description or 'ohne Beschreibung'}"
_SEARCH_BLOCK_RE = re.compile(r"```search\s*(.*?)\s*```", re.DOTALL)


def websearch_configured(settings: models.Settings) -> bool:
    if settings.websearch_provider == "searxng":
        return bool(settings.searxng_url)
    return bool(settings.brave_search_api_key_encrypted)


def websearch_run(settings: models.Settings, query: str) -> list[dict]:
    """Dispatcht auf den in Settings.websearch_provider gewählten Anbieter -
    einziger Aufrufpunkt fuer alle drei Stellen, die bisher Brave fest
    eincodiert hatten (Assistant-Chat, Wunschlisten-Deal-Check)."""
    if settings.websearch_provider == "searxng":
        return websearch.search_searxng(settings.searxng_url, query)
    api_key = bank_sync.decrypt_secret(settings.secret_key, settings.brave_search_api_key_encrypted)
    return websearch.search_brave(api_key, query)


@ai_assistant_router.post("/ai/assistant-chat", response_model=schemas.AssistantChatResult)
def assistant_chat(
    message: str = Form(...),
    history: str = Form("[]"),
    db: Session = Depends(get_db),
    space_id: int = Depends(auth.get_active_space_id),
):
    settings = auth.get_or_create_settings(db)
    chat_model = settings.ollama_model or settings.beleg_chat_model
    if not settings.ollama_url or not chat_model:
        raise HTTPException(400, "Bitte zuerst Ollama-Server-URL und Modell in den Einstellungen hinterlegen")

    try:
        hist = json.loads(history)
        if not isinstance(hist, list):
            hist = []
    except json.JSONDecodeError:
        hist = []

    system_content = ASSISTANT_CHAT_SYSTEM_PROMPT + "\n\n" + _assistant_context(db, space_id)
    messages = [{"role": "system", "content": system_content}]
    for m in hist:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": str(m["content"])})
    messages.append({"role": "user", "content": message})

    try:
        reply_raw = ollama_client.chat(settings.ollama_url, chat_model, messages)
    except Exception as e:
        return schemas.AssistantChatResult(reply="", error=str(e))

    web_searches: list[str] = []
    search_match = _SEARCH_BLOCK_RE.search(reply_raw)
    if search_match:
        query = search_match.group(1).strip()
        if not websearch_configured(settings):
            return schemas.AssistantChatResult(
                reply=f"Ich würde dafür gern im Internet suchen („{query}“), habe aber noch keine "
                      "Web-Suche eingerichtet. Trag in den Einstellungen unter „Web-Suche für KI-Chat“ "
                      "einen Brave-Search-API-Key oder eine SearXNG-Instanz ein, dann kann ich das."
            )
        try:
            results = websearch_run(settings, query)
        except Exception as e:
            return schemas.AssistantChatResult(reply="", error=f"Web-Suche fehlgeschlagen: {e}")
        web_searches.append(query)
        # Zweite Runde: die Suchergebnisse als weitere Nutzer-Nachricht anhängen und
        # eine finale, auf den Fakten basierende Antwort einholen - nur ein
        # Suchdurchgang pro Chatnachricht, damit keine Endlosschleife entstehen kann.
        messages.append({"role": "assistant", "content": reply_raw})
        messages.append({"role": "user", "content": websearch.format_for_prompt(query, results)
                         + "\n\nBeantworte jetzt meine ursprüngliche Frage auf Basis dieser Suchergebnisse."})
        try:
            reply_raw = ollama_client.chat(settings.ollama_url, chat_model, messages)
        except Exception as e:
            return schemas.AssistantChatResult(reply="", error=str(e), web_searches=web_searches)

    proposals = _extract_beleg_proposals(reply_raw, allowed_types=ASSISTANT_PROPOSAL_TYPES)
    for p in proposals:
        if p.get("type") in ("update_category", "mark_transfer"):
            resolved, err = _resolve_described_transaction(db, space_id, p)
            if resolved:
                p["resolved_transaction"] = resolved
            else:
                p["resolution_error"] = err
        elif p.get("type") == "transaction":
            try:
                p_date = date.fromisoformat(str(p.get("date")))
                p_amount = float(p.get("amount"))
            except (TypeError, ValueError):
                continue
            duplicate_matches = _find_duplicate_matches(db, space_id, p_amount, p_date)
            if duplicate_matches:
                p["duplicate_matches"] = duplicate_matches
        elif p.get("type") == "create_debt":
            _resolve_debt_proposal(db, space_id, p)

    reply_clean = _SEARCH_BLOCK_RE.sub("", _JSON_BLOCK_RE.sub("", reply_raw)).strip()
    if not reply_clean:
        reply_clean = f"Ich habe {len(proposals)} Vorschlag/Vorschläge erkannt - bitte prüfen:" if proposals else reply_raw

    return schemas.AssistantChatResult(reply=reply_clean, proposals=proposals, web_searches=web_searches)
