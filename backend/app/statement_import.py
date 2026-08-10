"""Automatischer Import von Kontoauszügen aus einem Eingangs-Unterordner
(siehe Settings.file_sort_statements_subfolder), Buchung für Buchung, ohne
manuelle Bestätigung - anders als der Beleg-Chat (dort bewusst ein
Vorschlag, den der Nutzer bestätigt). Der Nutzer hat das für diesen
speziellen Ordner ausdrücklich so gewollt.

Zwei Sicherheitsnetze, die trotzdem verhindern, dass etwas Falsches auf ein
Konto gebucht wird:
- Buchungen werden NUR angelegt, wenn das Modell den Kontoauszug einem der
  echten, bekannten Kontonamen eindeutig zuordnen konnte. Sonst bleibt die
  Datei unverändert in IHREM eigenen Unterordner liegen, es wird nichts
  geraten.
- Vor jeder neuen Buchung wird auf diesem Konto nach einer bereits
  existierenden Buchung mit gleichem Betrag (±0,01 €) innerhalb von einem
  Tag gesucht - ein Treffer gilt als Duplikat (z.B. weil derselbe Auszug
  versehentlich zweimal reinkopiert wurde oder eine Buchung schon über
  FinTS/PayPal-Sync da ist) und wird übersprungen statt doppelt angelegt.

Wichtig: nicht zuordenbare Dateien werden bewusst NICHT wie bei file_sort.py
in den geteilten "Zum Prüfen"-Ordner verschoben - dieser wird von der
normalen Kategorie-Einsortierung selbst als zweiter aktiver Eingang
durchsucht (siehe file_sort.py). Live beobachtet: ein dorthin verschobener,
nicht zuordenbarer Kontoauszug wurde vom nächsten Kategorisierungslauf als
"Rechnung" fehlklassifiziert und verschwand im falschen Ordner, obwohl der
eigentliche Import ihn schon als Kontoauszug erkannt, nur das Konto nicht
sicher zugeordnet hatte. Die Datei bleibt deshalb in ihrem eigenen
Kontoauszüge-Unterordner liegen, wo sie nur dieses Modul je anfasst.
"""

import json
import os
import re
import shutil
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from . import crud, document_extract, file_sort, models, ollama_client, schemas

MAX_STATEMENT_CHARS = 60000
OLLAMA_TIMEOUT = 3 * 60 * 60
# Live beobachtet: ein einzelner Ollama-Aufruf mit dem ganzen Auszugstext kam
# auf bis zu 13.289 Tokens - das Server-Kontextfenster lag hier aber nur bei
# 4096, und ein Versuch, es per num_ctx pro Anfrage hochzusetzen, hat den
# Ollama-Prozess auf dieser Maschine sogar abstürzen lassen (zu wenig RAM für
# den größeren KV-Cache). Deshalb wird der Auszug stattdessen in kleine,
# zeilenweise Häppchen zerlegt (CHUNK_CHARS), die beim Standard-Kontext sicher
# bleiben - mehr Ollama-Aufrufe statt mehr Kontext pro Aufruf. Auch bei
# 6000 Zeichen/Häppchen kam es live noch zu vereinzelten Server-Abstürzen
# ("unexpected EOF") bei mehreren Häppchen hintereinander - der Ollama-
# Container erholt sich zwar selbst (Docker-Restartpolicy) und ein
# einzelner Absturz kostet nur einen fehlgeschlagenen Abschnitt, aber ein
# kleinerer Wert senkt das Risiko pro Aufruf weiter.
CHUNK_CHARS = 3000

_JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)

# Erster Abschnitt: Konto erkennen + Buchungen dieses Abschnitts.
STATEMENT_PROMPT = """Das Folgende ist der Anfang eines Kontoauszugs. Bekannte Konten in diesem Finanztool:
{account_names}

Antworte in zwei Schritten:
1. Schreib in der ALLERERSTEN Zeile deiner Antwort GENAU einen der obigen Kontonamen (exakt wie oben geschrieben), zu dem dieser Auszug gehört. Bist du dir nicht sicher, schreib stattdessen nur das Wort UNBEKANNT.
2. Gib danach für JEDE einzelne Buchungszeile in diesem Ausschnitt einen eigenen JSON-Block aus, in dreifachen Backticks mit "json":
```json
{{"date": "YYYY-MM-DD", "amount": -12.34, "description": "..."}}
```
(amount negativ = Abbuchung/Ausgabe, positiv = Gutschrift/Einnahme). Erfinde KEINE Buchungen, die nicht im Text stehen, und lass keine echte Buchungszeile aus.

Ausschnitt:
{content}"""

# Weitere Abschnitte desselben Auszugs: Konto ist schon bekannt, nur noch Buchungen.
STATEMENT_CHUNK_PROMPT = """Das Folgende ist ein weiterer Ausschnitt DESSELBEN Kontoauszugs (Fortsetzung). \
Gib für JEDE einzelne Buchungszeile in diesem Ausschnitt einen eigenen JSON-Block aus, in dreifachen Backticks mit "json":
```json
{{"date": "YYYY-MM-DD", "amount": -12.34, "description": "..."}}
```
(amount negativ = Abbuchung/Ausgabe, positiv = Gutschrift/Einnahme). Erfinde KEINE Buchungen, die nicht im Text stehen, und lass keine echte Buchungszeile aus.

Ausschnitt:
{content}"""


def _split_statement_chunks(text: str, chunk_chars: int = CHUNK_CHARS) -> list[str]:
    """Zerlegt zeilenweise (nicht mitten in einer Buchungszeile) in Häppchen bis
    chunk_chars - so bleibt jeder einzelne Ollama-Aufruf sicher unter dem
    Server-Kontextfenster, unabhängig davon, wie lang der ganze Auszug ist.
    Eine einzelne, ungewöhnlich lange "Zeile" (z.B. ein PDF ohne Zeilenumbrüche)
    wird zusätzlich hart umgebrochen - sonst würde genau der Fall, den diese
    Funktion verhindern soll, durch die Hintertür wieder auftreten."""
    chunks, current, current_len = [], [], 0
    for line in text.splitlines():
        while len(line) > chunk_chars:
            if current:
                chunks.append("\n".join(current))
                current, current_len = [], 0
            chunks.append(line[:chunk_chars])
            line = line[chunk_chars:]
        if current and current_len + len(line) + 1 > chunk_chars:
            chunks.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _extract_account_name(reply: str, account_names: list[str]) -> str | None:
    first_line = next((line.strip() for line in reply.splitlines() if line.strip()), "")
    for name in account_names:
        if name.lower() in first_line.lower():
            return name
    return None


_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y")


def _parse_statement_date(raw) -> date | None:
    """Trotz Anweisung im Prompt liefern kleine Modelle das Datum nicht
    zuverlässig als ISO-String (live beobachtet: "05-07-2026" statt
    "2026-07-05") - mehrere gängige Formate durchprobieren statt blind auf
    ISO zu vertrauen."""
    text = str(raw).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_statement_amount(raw) -> float | None:
    """Ebenso beim Betrag: kleine Modelle geben ihn oft als String im
    deutschen Zahlenformat zurück ("-45,30" statt -45.30, teils mit
    Tausenderpunkt "1.234,56") statt als JSON-Zahl mit Punkt."""
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace("€", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        # Das letzte der beiden Zeichen ist der Dezimaltrenner, das andere Tausendertrennung.
        if text.rindex(",") > text.rindex("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _extract_transactions(reply: str) -> list[dict]:
    items = []
    for match in _JSON_BLOCK_RE.findall(reply):
        try:
            data = json.loads(match)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("date") and data.get("amount") is not None:
            items.append(data)
    return items


def _is_duplicate(db: Session, account_id: int, amount: float, tx_date: date) -> bool:
    return (
        db.query(models.Transaction)
        .filter(
            models.Transaction.account_id == account_id,
            models.Transaction.amount.between(amount - 0.01, amount + 0.01),
            models.Transaction.date.between(tx_date - timedelta(days=1), tx_date + timedelta(days=1)),
        )
        .first()
        is not None
    )


def process_statement_inbox(db: Session, settings: models.Settings, space_id: int) -> dict:
    subfolder = settings.file_sort_statements_subfolder
    result = {"processed": 0, "imported": 0, "duplicates": 0, "error": None}
    if not subfolder or not settings.file_sort_source_path:
        return result

    source_dir = os.path.join(settings.file_sort_source_path, subfolder)
    try:
        files = file_sort.list_inbox_files(source_dir)
    except FileNotFoundError as e:
        result["error"] = str(e)
        return result

    accounts = crud.get_accounts(db, space_id)
    account_by_name = {a.name: a for a in accounts}
    account_names = list(account_by_name.keys())
    account_list_text = "\n".join(f"- {n}" for n in account_names)

    for filename in files:
        path = os.path.join(source_dir, filename)
        ext = os.path.splitext(filename)[1].lower()

        if ext != ".pdf":
            # Bewusst NICHT file_sort._move_to_review: dieser Ordner ist NICHT
            # der geteilte "Zum Prüfen"-Ordner, den die normale Kategorisierung
            # ebenfalls als zweiten Eingang durchsucht (siehe Modul-Docstring) -
            # die Datei bleibt hier liegen, zum manuellen Anschauen.
            file_sort._log_once(
                db, filename, "review",
                f"Kontoauszug: Dateityp {ext or '(ohne Endung)'} wird nicht unterstützt.",
            )
            continue

        result["processed"] += 1
        try:
            with open(path, "rb") as fh:
                content = fh.read()
            text, _images = document_extract.extract_pdf(content, max_chars=MAX_STATEMENT_CHARS)
        except Exception as e:
            file_sort._log_once(db, filename, "error", f"Kontoauszug konnte nicht gelesen werden: {e}")
            continue

        if not text:
            file_sort._log_once(
                db, filename, "review",
                "Kontoauszug: kein Text erkennbar (vermutlich eingescannt statt digital erzeugt).",
            )
            continue

        model = settings.file_sort_model or settings.ollama_model
        chunks = _split_statement_chunks(text)
        account_name = None
        all_transactions: list[dict] = []
        failed_chunks = 0
        for i, chunk in enumerate(chunks):
            prompt = (
                STATEMENT_PROMPT.format(account_names=account_list_text, content=chunk) if i == 0
                else STATEMENT_CHUNK_PROMPT.format(content=chunk)
            )
            try:
                reply = ollama_client.chat(
                    settings.ollama_url, model, [{"role": "user", "content": prompt}], timeout=OLLAMA_TIMEOUT,
                )
            except Exception as e:
                failed_chunks += 1
                # Bewusst KEIN _log_once (dedupliziert nach Dateiname+Aktion): bei
                # einem Kontoauszug soll ein sich änderndes Fehlerbild (oder ein
                # späterer Erfolg) beim nächsten Lauf sichtbar bleiben statt hinter
                # der ersten geloggten Fehlermeldung für immer zu verschwinden.
                db.add(models.FileSortLog(
                    filename=filename, action="error",
                    detail=f"Kontoauszug-Import (Abschnitt {i + 1}/{len(chunks)}) fehlgeschlagen: {e}",
                ))
                db.commit()
                continue
            if i == 0:
                account_name = _extract_account_name(reply, account_names)
            all_transactions.extend(_extract_transactions(reply))

        # Zusätzlicher deterministischer Gegencheck, unabhängig vom Modell: der
        # behauptete Kontoname muss auch tatsächlich im Auszugstext selbst
        # vorkommen. Live beobachtet: das Modell hat einen Auszug, der explizit
        # "Sparkasse Musterstadt" nannte, trotzdem einem der bekannten Konten
        # zugeordnet statt UNBEKANNT zu antworten - bei automatischem Import
        # ohne Bestätigung reicht "das Modell hat es behauptet" hier nicht.
        if account_name and account_name.lower() not in text.lower():
            account_name = None
        if not account_name:
            file_sort._log_once(
                db, filename, "review",
                "Kontoauszug: Konto nicht sicher erkannt - bitte manuell zuordnen und importieren.",
            )
            continue
        account = account_by_name[account_name]

        added, skipped_dupes = 0, 0
        for t in all_transactions:
            tx_date = _parse_statement_date(t.get("date"))
            amount = _parse_statement_amount(t.get("amount"))
            if tx_date is None or amount is None:
                continue
            amount = round(amount, 2)
            if _is_duplicate(db, account.id, amount, tx_date):
                skipped_dupes += 1
                continue
            crud.create_transaction(db, schemas.TransactionCreate(
                date=tx_date, amount=amount, account_id=account.id,
                description=str(t.get("description") or "").strip()[:255] or "Kontoauszug-Import",
                notes="Automatisch aus Kontoauszug importiert",
            ))
            added += 1

        target_root = settings.file_sort_target_path or source_dir
        dest_dir = os.path.join(target_root, subfolder, account_name)
        os.makedirs(dest_dir, exist_ok=True)
        dest = file_sort._unique_target(dest_dir, filename)
        try:
            shutil.move(path, dest, copy_function=shutil.copyfile)
        except Exception as e:
            file_sort._log_once(db, filename, "error", f"Verschieben nach Import fehlgeschlagen: {e}")
            continue

        rel = os.path.relpath(dest, target_root)
        warn = f" (ACHTUNG: {failed_chunks}/{len(chunks)} Abschnitte nicht auswertbar, evtl. unvollständig)" if failed_chunks else ""
        db.add(models.FileSortLog(
            filename=filename, category="Kontoauszug", action="statement_imported",
            detail=f"{account_name}: {added} Buchung(en) importiert, {skipped_dupes} Duplikat(e) übersprungen -> {rel}{warn}",
        ))
        db.commit()
        result["imported"] += added
        result["duplicates"] += skipped_dupes

    return result
