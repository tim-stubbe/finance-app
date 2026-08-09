"""Automatische Einsortierung eines Eingangsordners in Kategorie-Unterordner.

Bewusst mit fester Kategorienliste statt KI-erfundener Ordnernamen - das
verhindert Ordner-Wildwuchs ("Strom" vs. "Stromrechnung" vs. "Energie") und
übernimmt stattdessen die vom Nutzer bereits von Hand angelegte Struktur.

Sicherheitsprinzipien, analog zu Immich in diesem Projekt:
- Nichts wird überschrieben - bei einer Namenskollision im Ziel wird ein
  Zähler an den Dateinamen angehängt (wie es der Nutzer selbst schon
  handhabt, siehe "Bundeswehr_Fragebogen (2).pdf" im echten Bestand).
- Unsichere Einordnungen werden NICHT geraten, sondern übersprungen und im
  Log als "manuell prüfen" markiert - lieber liegen lassen als falsch
  einsortieren.
- Dateitypen, die kein auswertbares Dokument sind (Bilder von Werbebannern,
  Datenbank-Dumps, u.ä.) werden nicht angefasst, nur protokolliert.
"""

import base64
import os
import shutil

from sqlalchemy.orm import Session

from . import models, document_extract, ollama_client

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".webp"}
UNCERTAIN_MARKER = "UNSICHER"

CLASSIFY_PROMPT = """Du sortierst ein Dokument in genau eine Kategorie ein.

Verfügbare Kategorien:
{categories}

Regeln:
- Wenn du dir bei der Zuordnung nicht recht sicher bist, oder das Dokument in
  keine der Kategorien eindeutig passt, antworte NUR mit dem Wort {uncertain}.
- Sonst antworte NUR mit exakt einem der Kategorienamen, sonst nichts.

Dateiname: {filename}
{content_label}: {content}"""


def list_inbox_files(source_path: str) -> list[str]:
    if not os.path.isdir(source_path):
        raise FileNotFoundError(f"Eingangsordner nicht gefunden: {source_path}")
    return sorted(
        f for f in os.listdir(source_path)
        if os.path.isfile(os.path.join(source_path, f)) and not f.startswith(".")
    )


def classify_file(ollama_url: str, ollama_model: str, beleg_chat_model: str | None,
                   filename: str, content: bytes, categories: list[str]) -> str:
    """Liest eine Datei aus und lässt Ollama eine der bekannten Kategorien
    wählen. Gibt UNCERTAIN_MARKER zurück, wenn Text/Bild nicht lesbar ist
    oder das Modell selbst unsicher ist."""
    ext = os.path.splitext(filename)[1].lower()
    text, images = None, []
    if ext == ".pdf":
        text, images = document_extract.extract_pdf(content)
    elif ext in SUPPORTED_EXTENSIONS:
        images = [base64.b64encode(content).decode()]

    categories_list = "\n".join(f"- {c}" for c in categories)
    if text:
        prompt = CLASSIFY_PROMPT.format(
            categories=categories_list, uncertain=UNCERTAIN_MARKER,
            filename=filename, content_label="Textauszug", content=text[:2500],
        )
        model = ollama_model
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

    answer = ollama_client.chat(ollama_url, model, [message], timeout=120).strip()
    # Manche Modelle antworten trotz Anweisung mit einem ganzen Satz - darin
    # nach einer der bekannten Kategorien suchen, statt exakte Übereinstimmung
    # zu verlangen.
    for cat in categories:
        if cat.lower() in answer.lower():
            return cat
    return UNCERTAIN_MARKER


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


def run(db: Session, settings: models.Settings) -> dict:
    source = settings.file_sort_source_path
    target = settings.file_sort_target_path
    categories = [c.strip() for c in (settings.file_sort_categories or "").split(",") if c.strip()]
    if not source or not target or not categories:
        return {"processed": 0, "moved": 0, "skipped": 0, "error": "Nicht vollständig eingerichtet"}
    if not settings.ollama_url or not settings.ollama_model:
        return {"processed": 0, "moved": 0, "skipped": 0, "error": "Kein Ollama-Server eingerichtet"}

    moved, skipped, processed = 0, 0, 0
    try:
        files = list_inbox_files(source)
    except FileNotFoundError as e:
        return {"processed": 0, "moved": 0, "skipped": 0, "error": str(e)}

    for filename in files:
        ext = os.path.splitext(filename)[1].lower()
        path = os.path.join(source, filename)

        if ext not in SUPPORTED_EXTENSIONS:
            # Nur einmal protokollieren, nicht bei jedem Durchlauf erneut -
            # sonst wächst das Log nur mit denselben paar Werbe-/Müll-Dateien.
            already_logged = db.query(models.FileSortLog).filter(
                models.FileSortLog.filename == filename,
                models.FileSortLog.action == "skipped_unsupported",
            ).first()
            if not already_logged:
                db.add(models.FileSortLog(
                    filename=filename, action="skipped_unsupported",
                    detail=f"Dateityp {ext or '(ohne Endung)'} wird nicht automatisch ausgewertet.",
                ))
                db.commit()
            continue

        processed += 1
        try:
            with open(path, "rb") as fh:
                content = fh.read()
            category = classify_file(
                settings.ollama_url, settings.ollama_model, settings.beleg_chat_model,
                filename, content, categories,
            )
        except Exception as e:
            db.add(models.FileSortLog(filename=filename, action="error", detail=str(e)))
            db.commit()
            continue

        if category == UNCERTAIN_MARKER:
            already_logged = db.query(models.FileSortLog).filter(
                models.FileSortLog.filename == filename,
                models.FileSortLog.action == "skipped_uncertain",
            ).first()
            if not already_logged:
                db.add(models.FileSortLog(
                    filename=filename, action="skipped_uncertain",
                    detail="Keine eindeutige Kategorie erkannt - bitte manuell einsortieren.",
                ))
                db.commit()
            skipped += 1
            continue

        target_dir = os.path.join(target, category)
        os.makedirs(target_dir, exist_ok=True)
        dest = _unique_target(target_dir, filename)
        try:
            shutil.move(path, dest)
        except Exception as e:
            db.add(models.FileSortLog(filename=filename, action="error", detail=f"Verschieben fehlgeschlagen: {e}"))
            db.commit()
            continue

        db.add(models.FileSortLog(
            filename=filename, category=category, action="moved",
            detail=f"-> {category}/{os.path.basename(dest)}",
        ))
        db.commit()
        moved += 1

    return {"processed": processed, "moved": moved, "skipped": skipped, "error": None}
