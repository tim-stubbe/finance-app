import base64
import json
import re
from datetime import date

import pymupdf

from . import ollama_client

MAX_PDF_PAGES_AS_IMAGES = 3
MAX_TEXT_CHARS = 8000

RECEIPT_PARSE_PROMPT = (
    "Du bekommst den Text einer Rechnung oder eines Belegs. Nenne ausschliesslich "
    "das Belegdatum und den Gesamtbetrag. Antworte NUR mit einem JSON-Block:\n"
    "```json\n{\"datum\": \"JJJJ-MM-TT\", \"betrag\": 12.34}\n```\n"
    "Wenn du eines der beiden nicht sicher erkennst, schreibe null. Rate nicht."
)


def extract_pdf(data: bytes) -> tuple[str | None, list[str]]:
    """Liest ein PDF aus. Enthält es durchsuchbaren Text (z.B. ein digital
    erzeugter Kontoauszug/eine Wertpapierabrechnung), wird der Text zurückgegeben.
    Andernfalls (z.B. ein eingescannter Beleg) werden die ersten Seiten als
    PNG-Bilder (base64) gerendert, damit ein Vision-Modell sie lesen kann."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    text_parts = []
    for page in doc:
        page_text = page.get_text().strip()
        if page_text:
            text_parts.append(page_text)

    if text_parts:
        return "\n".join(text_parts)[:MAX_TEXT_CHARS], []

    images = []
    for page in doc[:MAX_PDF_PAGES_AS_IMAGES]:
        pix = page.get_pixmap(dpi=150)
        images.append(base64.b64encode(pix.tobytes("png")).decode())
    return None, images


def parse_receipt_fields(
    ollama_url: str, ollama_model: str, beleg_chat_model: str | None,
    content: bytes, filename: str, timeout: int = 180,
) -> tuple[date | None, float | None, str | None]:
    """Liest Datum und Betrag aus einem Beleg per KI. Gemeinsam genutzt vom
    E-Mail-Postfach-Import und der Datei-Sortierung, damit beide dieselbe
    Auswertung nutzen statt zwei leicht unterschiedliche Versionen zu pflegen.

    Gibt (datum, betrag, fehler) zurück - ein Fehlschlag ist kein Drama, der
    Beleg landet dann nur ohne vorausgefüllte Werte in der Sichtliste.
    """
    if not ollama_url or not ollama_model:
        return None, None, "Kein Ollama-Server eingerichtet"

    text, images = None, []
    try:
        if filename.lower().endswith(".pdf"):
            text, images = extract_pdf(content)
        else:
            images = [base64.b64encode(content).decode()]
    except Exception as e:
        return None, None, f"Datei nicht lesbar: {e}"

    nachricht = {"role": "user", "content": RECEIPT_PARSE_PROMPT}
    if text:
        nachricht["content"] += f"\n\nBelegtext:\n{text[:6000]}"
        modell = ollama_model
    elif images:
        nachricht["images"] = images[:1]
        modell = beleg_chat_model or ollama_model
    else:
        return None, None, "Weder Text noch Bild aus der Datei gewinnbar"

    try:
        antwort = ollama_client.chat(ollama_url, modell, [nachricht], timeout=timeout)
    except Exception as e:
        return None, None, f"KI nicht erreichbar: {e}"

    treffer = re.search(r"```json\s*(\{.*?\})\s*```", antwort, re.DOTALL)
    if not treffer:
        treffer = re.search(r"(\{[^{}]*\"betrag\"[^{}]*\})", antwort, re.DOTALL)
    if not treffer:
        return None, None, "Kein verwertbares Ergebnis von der KI"

    try:
        daten = json.loads(treffer.group(1))
    except Exception:
        return None, None, "Antwort der KI war kein gültiges JSON"

    betrag = daten.get("betrag")
    try:
        betrag = float(betrag) if betrag is not None else None
    except (TypeError, ValueError):
        betrag = None
    datum = None
    if daten.get("datum"):
        try:
            datum = date.fromisoformat(str(daten["datum"])[:10])
        except ValueError:
            datum = None
    return datum, betrag, None
