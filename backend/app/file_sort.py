"""Automatische Einsortierung eines Eingangsordners in Kategorie-Unterordner.

Zwei Eingänge werden verarbeitet: der eigentliche Eingangsordner (z.B. wo
automatisch E-Mail-Anhänge landen) UND der "Zum Prüfen"-Ordner selbst, den
der Nutzer von Hand befüllt (z.B. vom Desktop reingezogene Dateien). Im
Eingangsordner darf aufgeräumt/gelöscht werden, im "Zum Prüfen"-Ordner nie -
dort wird nur rausverschoben, was sich einordnen lässt, der Rest bleibt
liegen (siehe _process_source).

Bewusst mit fester Kategorienliste statt KI-erfundener Ordnernamen - das
verhindert Ordner-Wildwuchs ("Strom" vs. "Stromrechnung" vs. "Energie") und
übernimmt stattdessen die vom Nutzer bereits von Hand angelegte Struktur.
Einzige Ausnahme: innerhalb EINER konfigurierbaren Kategorie (Standard
"Rechnung") wird zusätzlich nach Anbieter/Absender in Unterordner sortiert -
dort ist das gewünscht, weil sich viele Rechnungen sonst in einem einzigen
Ordner stauen (siehe file_sort_subfolder_category in models.py).

Sicherheitsprinzipien, analog zu Immich in diesem Projekt:
- Nichts wird überschrieben - bei einer Namenskollision im Ziel wird ein
  Zähler an den Dateinamen angehängt (wie es der Nutzer selbst schon
  handhabt, siehe "Bundeswehr_Fragebogen (2).pdf" im echten Bestand).
- Unsichere Einordnungen werden NICHT geraten - landen aber auch nicht für
  immer im Eingangsordner, sondern in einem dritten "Zum Prüfen"-Ordner
  (file_sort_review_path), damit der Eingang nicht vermüllt. Lieber dort
  liegen als falsch einsortiert.
- Nur eindeutiger, wertloser Datenmüll (bekannte AMP-E-Mail-Fragmente,
  Windows-Thumbnail-Caches) wird direkt gelöscht - alles andere Unbekannte
  geht zum manuellen Prüfen in denselben dritten Ordner, nicht in den Papierkorb.
- Kein hartes Zeitlimit beim Warten auf die KI: der Job läuft ohnehin im
  Hintergrund, ein überlasteter Ollama-Server darf ruhig länger brauchen,
  statt die Datei als Fehler zu verbuchen (siehe OLLAMA_TIMEOUT).
"""

import base64
import os
import re
import shutil
import threading

from sqlalchemy.orm import Session

from . import models, document_extract, ollama_client

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".webp", ".txt", ".docx"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
UNCERTAIN_MARKER = "UNSICHER"
# Eindeutig wertloser Datenmüll, der direkt gelöscht wird statt in den
# "Zum Prüfen"-Ordner zu wandern - AMP-E-Mail-Fragmente enthalten kein
# eigenständiges Dokument, Thumbs.db ist ein reiner Windows-Cache.
JUNK_EXTENSIONS = {".x-amp-html"}
JUNK_EXACT_NAMES = {"thumbs.db", ".ds_store"}
# Kein Wert von main.py aus konfigurierbar, bewusst grosszügig statt "kein
# Limit" (ein echt unbegrenzter Request könnte einen einzelnen Lauf für immer
# blockieren, falls die Verbindung selbst haengt statt nur langsam zu sein).
OLLAMA_TIMEOUT = 3 * 60 * 60

# Läuft alle 10 Minuten als Hintergrund-Job UND ist manuell auslösbar - ohne
# diese Sperre liefen bei einer Überschneidung zwei Läufe gleichzeitig über
# dieselbe Dateiliste, rissen sich Dateien gegenseitig unterm Ollama-Aufruf
# weg ("No such file or directory") und produzierten unnötige Timeouts durch
# gegenseitige Ollama-Auslastung.
_run_lock = threading.Lock()

CLASSIFY_PROMPT = """Du sortierst ein Dokument in genau eine Kategorie ein.

Verfügbare Kategorien:
{categories}

Regeln:
- Behoerde NUR waehlen, wenn klar erkennbar ein Amt/eine Behoerde/oeffentliche
  Stelle der Absender ist (Finanzamt, Stadtverwaltung, Bundesamt, Gericht,
  Bundeswehr, etc). Eine normale Firma, ein Online-Shop, eine Privatperson
  oder Werbung ist KEINE Behoerde.
- Sonstiges ist der normale Standardfall für alles, was nicht eindeutig in
  eine andere Kategorie passt - im Zweifel lieber Sonstiges als eine
  spezifischere Kategorie zu erzwingen.
- Wenn du dir auch bei Sonstiges nicht sicher bist, antworte NUR mit dem Wort
  {uncertain}.
- Sonst antworte NUR mit exakt einem der Kategorienamen, sonst nichts.

Dateiname: {filename}
{content_label}: {content}"""

VENDOR_PROMPT = """Nenne NUR den Namen des Absenders/Anbieters/Unternehmens dieses
Dokuments, kurz (ein bis zwei Wörter, wie ein Firmenname), ohne Rechtsform
und ohne weitere Erklärung. Wenn nicht erkennbar, antworte mit "Unbekannt".

Dateiname: {filename}
{content_label}: {content}"""

_SAFE_FOLDER_RE = re.compile(r"[^\w äöüÄÖÜß.\-]+")


def _safe_folder_name(name: str) -> str:
    name = _SAFE_FOLDER_RE.sub("", name).strip(" .")
    return name[:60] or "Unbekannt"


def list_inbox_files(source_path: str) -> list[str]:
    if not os.path.isdir(source_path):
        raise FileNotFoundError(f"Eingangsordner nicht gefunden: {source_path}")
    return sorted(
        f for f in os.listdir(source_path)
        if os.path.isfile(os.path.join(source_path, f)) and not f.startswith(".")
    )


# Live beobachtet: ein 1x30-Pixel-Bild (kaputter Tracking-Pixel aus einer
# E-Mail, trotz Dateiname "Zahlungsbeleg" kein echtes Foto) brachte Ollamas
# Bildmodell zuverlässig zum Absturz (Verbindungsabbruch ohne Antwort) - so
# ein Mini-Bild kann ohnehin kein lesbares Dokument sein, deshalb gar nicht
# erst an die KI schicken.
MIN_IMAGE_DIMENSION = 20


def _is_degenerate_image(content: bytes) -> bool:
    try:
        from PIL import Image
        from io import BytesIO
        img = Image.open(BytesIO(content))
        return img.width < MIN_IMAGE_DIMENSION or img.height < MIN_IMAGE_DIMENSION
    except Exception:
        # Nicht als Bild lesbar - kein Fall fuer diese Pruefung, das faellt
        # spaeter beim eigentlichen Verarbeiten ohnehin auf.
        return False


def _extract_docx_text(content: bytes) -> str | None:
    """Liest den Fliesstext aus einer .docx (ist ein ZIP mit XML drin) -
    kein neues pip-Paket noetig (das haette einen Docker-Rebuild erzwungen),
    reine Stdlib-Extraktion reicht fuer Klassifizierungszwecke."""
    try:
        import zipfile
        import io
        import xml.etree.ElementTree as ET
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            xml_bytes = z.read("word/document.xml")
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        root = ET.fromstring(xml_bytes)
        paragraphs = []
        for p in root.iter(f"{ns}p"):
            texts = [node.text for node in p.iter(f"{ns}t") if node.text]
            if texts:
                paragraphs.append("".join(texts))
        text = "\n".join(paragraphs).strip()
        return text or None
    except Exception:
        return None


def _read_content(filename: str, content: bytes) -> tuple[str | None, list[str]]:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return document_extract.extract_pdf(content)
    if ext == ".txt":
        try:
            return content.decode("utf-8"), []
        except UnicodeDecodeError:
            return content.decode("latin-1", errors="replace"), []
    if ext == ".docx":
        return _extract_docx_text(content), []
    if ext in IMAGE_EXTENSIONS:
        if _is_degenerate_image(content):
            return None, []
        return None, [base64.b64encode(content).decode()]
    return None, []


def classify_file(ollama_url: str, ollama_model: str, beleg_chat_model: str | None,
                   filename: str, content: bytes, categories: list[str],
                   text_model: str | None = None) -> str:
    """Liest eine Datei aus und lässt Ollama eine der bekannten Kategorien
    wählen. Gibt UNCERTAIN_MARKER zurück, wenn Text/Bild nicht lesbar ist
    oder das Modell selbst unsicher ist.

    `text_model` überschreibt bei Textdokumenten das Standardmodell - kleine
    Modelle unterscheiden sich hier erheblich in der Zuverlässigkeit. Live
    getestet: phi4-mini klassifiziert eine eindeutige IKEA-Rechnung
    hartnäckig als "Behoerde", selbst mit expliziter Gegenanweisung im
    Prompt; qwen3:4b-instruct erkennt dieselbe Rechnung sofort richtig. Das
    ist also kein Prompt-Problem, sondern eine Modellschwäche."""
    text, images = _read_content(filename, content)
    categories_list = "\n".join(f"- {c}" for c in categories)
    if text:
        prompt = CLASSIFY_PROMPT.format(
            categories=categories_list, uncertain=UNCERTAIN_MARKER,
            filename=filename, content_label="Textauszug", content=text[:2500],
        )
        model = text_model or ollama_model
        message = {"role": "user", "content": prompt}
    elif images:
        prompt = CLASSIFY_PROMPT.format(
            categories=categories_list, uncertain=UNCERTAIN_MARKER,
            filename=filename, content_label="(Bild angehängt)", content="",
        )
        model = beleg_chat_model or ollama_model
        message = {"role": "user", "content": prompt, "images": images[:1]}
    else:
        return UNCERTAIN_MARKER

    answer = ollama_client.chat(ollama_url, model, [message], timeout=OLLAMA_TIMEOUT).strip()
    # Manche Modelle antworten trotz Anweisung mit einem ganzen Satz - darin
    # nach einer der bekannten Kategorien suchen, statt exakte Übereinstimmung
    # zu verlangen. Längste zuerst, damit z.B. "Sonstiges" nicht faelschlich
    # in einem laengeren, aehnlich lautenden Namen anschlaegt.
    for cat in sorted(categories, key=len, reverse=True):
        if cat.lower() in answer.lower():
            return cat
    return UNCERTAIN_MARKER


def detect_vendor(ollama_url: str, ollama_model: str, beleg_chat_model: str | None,
                   filename: str, content: bytes, text_model: str | None = None) -> str:
    text, images = _read_content(filename, content)
    if text:
        prompt = VENDOR_PROMPT.format(filename=filename, content_label="Textauszug", content=text[:2000])
        model = text_model or ollama_model
        message = {"role": "user", "content": prompt}
    elif images:
        prompt = VENDOR_PROMPT.format(filename=filename, content_label="(Bild angehängt)", content="")
        model = beleg_chat_model or ollama_model
        message = {"role": "user", "content": prompt, "images": images[:1]}
    else:
        return "Unbekannt"
    try:
        answer = ollama_client.chat(ollama_url, model, [message], timeout=OLLAMA_TIMEOUT)
    except Exception:
        return "Unbekannt"
    return _safe_folder_name(answer.strip().splitlines()[0] if answer.strip() else "Unbekannt")


def _unique_target(target_dir: str, filename: str) -> str:
    """Verhindert Überschreiben: bei Namenskollision einen Zähler anhängen,
    genau wie es in der bestehenden, von Hand sortierten Ablage schon gemacht
    wird (siehe "Bundeswehr_Fragebogen (2).pdf")."""
    base, ext = os.path.splitext(filename)
    candidate = filename
    n = 2
    while os.path.exists(os.path.join(target_dir, candidate)):
        candidate = f"{base} ({n}){ext}"
        n += 1
    return os.path.join(target_dir, candidate)


def _log_once(db: Session, filename: str, action: str, detail: str) -> None:
    """Verhindert Log-Spam: wenn genau diese Datei mit dieser Aktion schon
    einmal protokolliert wurde (z.B. wiederholter Timeout bei jedem der
    10-Minuten-Läufe), nicht erneut eintragen."""
    exists = db.query(models.FileSortLog).filter(
        models.FileSortLog.filename == filename, models.FileSortLog.action == action,
    ).first()
    if not exists:
        db.add(models.FileSortLog(filename=filename, action=action, detail=detail))
        db.commit()


def run(db: Session, settings: models.Settings) -> dict:
    if not _run_lock.acquire(blocking=False):
        return {"processed": 0, "moved": 0, "skipped": 0, "error": "Läuft bereits, dieser Aufruf wird übersprungen.", "receipts": []}
    try:
        return _run_locked(db, settings)
    finally:
        _run_lock.release()


def _move_to_review(db: Session, review_path: str, source: str, filename: str, action: str, detail: str) -> None:
    """Bekommt eine Datei, die weder automatisch einsortiert noch sicher als
    Müll gelöscht werden kann - landet zum manuellen Prüfen in einem dritten
    Ordner, statt für immer im Eingang liegen zu bleiben oder riskiert falsch
    einsortiert zu werden."""
    if not review_path:
        _log_once(db, filename, action, detail)
        return
    try:
        os.makedirs(review_path, exist_ok=True)
        dest = _unique_target(review_path, filename)
        # copy_function=copyfile statt des Standards (copy2): copy2 versucht
        # auch Berechtigungen/Zeitstempel zu uebertragen, was auf mancher
        # SMB-Freigabe mit "Operation not permitted" fehlschlaegt - dann blieb
        # die Datei kopiert UND im Eingang liegen. copyfile ueberträgt nur den
        # Inhalt, das reicht hier.
        shutil.move(os.path.join(source, filename), dest, copy_function=shutil.copyfile)
        _log_once(db, filename, action, detail)
    except Exception as e:
        _log_once(db, filename, "error", f"Verschieben zum Prüfen fehlgeschlagen: {e}")


def _process_source(db: Session, settings: models.Settings, source: str, target: str, review: str,
                     categories: list[str], subfolder_category: str, *, allow_delete: bool,
                     leave_uncertain_in_place: bool) -> dict:
    """Sortiert einen Eingangsordner ein. Zwei Quellen nutzen das:
    - der eigentliche Eingang (allow_delete=True, unsichere Dateien wandern
      in den "Zum Prüfen"-Ordner).
    - der "Zum Prüfen"-Ordner selbst als zweiter, vom Nutzer von Hand
      befüllter Eingang (allow_delete=False, unsichere Dateien bleiben
      einfach liegen statt in sich selbst "verschoben" zu werden - dort
      darf laut Nutzer nichts gelöscht werden, nur raus einsortiert)."""
    moved, skipped, processed = 0, 0, 0
    receipts: list[dict] = []
    try:
        files = list_inbox_files(source)
    except FileNotFoundError as e:
        return {"processed": 0, "moved": 0, "skipped": 0, "error": str(e), "receipts": []}

    for filename in files:
        ext = os.path.splitext(filename)[1].lower()
        path = os.path.join(source, filename)

        if ext not in SUPPORTED_EXTENSIONS:
            if allow_delete and (ext in JUNK_EXTENSIONS or filename.lower() in JUNK_EXACT_NAMES):
                try:
                    os.remove(path)
                    _log_once(db, filename, "deleted", "Erkannter Datenmüll ohne eigenständigen Inhalt.")
                except Exception as e:
                    _log_once(db, filename, "error", f"Löschen fehlgeschlagen: {e}")
                continue
            if leave_uncertain_in_place:
                _log_once(db, filename, "skipped_unsupported",
                          f"Dateityp {ext or '(ohne Endung)'} wird nicht automatisch ausgewertet.")
            else:
                _move_to_review(db, review, source, filename, "review",
                                 f"Dateityp {ext or '(ohne Endung)'} wird nicht automatisch ausgewertet.")
            continue

        processed += 1
        try:
            with open(path, "rb") as fh:
                content = fh.read()
            category = classify_file(
                settings.ollama_url, settings.ollama_model, settings.beleg_chat_model,
                filename, content, categories, text_model=settings.file_sort_model,
            )
        except Exception as e:
            _log_once(db, filename, "error", str(e))
            continue

        if category == UNCERTAIN_MARKER:
            if leave_uncertain_in_place:
                _log_once(db, filename, "skipped_uncertain",
                          "Keine eindeutige Kategorie erkannt - bleibt hier liegen.")
            else:
                _move_to_review(db, review, source, filename, "review",
                                 "Keine eindeutige Kategorie erkannt - bitte manuell einsortieren.")
            skipped += 1
            continue

        target_dir = os.path.join(target, category)
        if category == subfolder_category:
            try:
                vendor = detect_vendor(
                    settings.ollama_url, settings.ollama_model, settings.beleg_chat_model,
                    filename, content, text_model=settings.file_sort_model,
                )
            except Exception:
                vendor = "Unbekannt"
            target_dir = os.path.join(target_dir, vendor)

        os.makedirs(target_dir, exist_ok=True)
        dest = _unique_target(target_dir, filename)
        try:
            # copyfile statt des Standards (copy2): copy2 versucht auch
            # Berechtigungen/Zeitstempel zu uebertragen, was auf mancher
            # SMB-Freigabe mit "Operation not permitted" fehlschlaegt - dann
            # blieb die Datei kopiert UND im Eingang liegen.
            shutil.move(path, dest, copy_function=shutil.copyfile)
        except Exception as e:
            db.add(models.FileSortLog(filename=filename, action="error", detail=f"Verschieben fehlgeschlagen: {e}"))
            db.commit()
            continue

        rel = os.path.relpath(dest, target)
        db.add(models.FileSortLog(filename=filename, category=category, action="moved", detail=f"-> {rel}"))
        db.commit()
        moved += 1

        if category == subfolder_category:
            receipts.append({"filename": filename, "dest": dest, "rel": rel, "content": content})

    return {"processed": processed, "moved": moved, "skipped": skipped, "error": None, "receipts": receipts}


def _run_locked(db: Session, settings: models.Settings) -> dict:
    target = settings.file_sort_target_path
    review = settings.file_sort_review_path
    categories = [c.strip() for c in (settings.file_sort_categories or "").split(",") if c.strip()]
    subfolder_category = (settings.file_sort_subfolder_category or "").strip()
    if not settings.file_sort_source_path or not target or not categories:
        return {"processed": 0, "moved": 0, "skipped": 0, "error": "Nicht vollständig eingerichtet", "receipts": []}
    if not settings.ollama_url or not settings.ollama_model:
        return {"processed": 0, "moved": 0, "skipped": 0, "error": "Kein Ollama-Server eingerichtet", "receipts": []}

    result = _process_source(
        db, settings, settings.file_sort_source_path, target, review, categories, subfolder_category,
        allow_delete=True, leave_uncertain_in_place=False,
    )
    if result["error"]:
        return result

    # Zweite Quelle: der "Zum Prüfen"-Ordner selbst ist auch ein Eingang, den
    # der Nutzer von Hand befüllt (z.B. vom Desktop reingezogene Dateien) -
    # wird ebenfalls einsortiert, aber nie etwas darin gelöscht, und
    # Unklares bleibt einfach liegen statt "in sich selbst verschoben" zu
    # werden.
    if review:
        second = _process_source(
            db, settings, review, target, review, categories, subfolder_category,
            allow_delete=False, leave_uncertain_in_place=True,
        )
        if not second["error"]:
            result["processed"] += second["processed"]
            result["moved"] += second["moved"]
            result["skipped"] += second["skipped"]
            result["receipts"] += second["receipts"]

    return result
