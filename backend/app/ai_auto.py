"""Automatische Kategorisierung unkategorisierter Buchungen per Ollama.

Läuft stündlich über den Scheduler (main.py), zusätzlich manuell auslösbar.
Bewusst konservativ: nur Buchungen, bei denen die KI eine Sicherheit über
CONFIDENCE_THRESHOLD angibt, werden direkt zugeordnet. Vorschläge mit
mittlerer Konfidenz (siehe QUEUE_MIN_CONFIDENCE) landen stattdessen in einer
Review-Warteschlange (models.CategorySuggestion) zum manuellen Bestätigen/
Ablehnen - nur wirklich geratene Vorschläge werden ganz verworfen."""

import json
import re
from datetime import datetime
from typing import NamedTuple

from sqlalchemy.orm import Session

from . import models, crud, ollama_client

CONFIDENCE_THRESHOLD = 0.7
BATCH_SIZE = 25
MAX_PENDING_PER_RUN = 200

_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

# Feste, KI-freie Regeln fuer Faelle, in denen dieselbe Gegenstelle je nach
# Vorzeichen etwas komplett anderes bedeutet - z.B. eBay: negativer Betrag
# = Einkauf (Ausgabe), positiver Betrag = Verkaufserloes (Einnahme). Live
# beobachtet: die KI ordnete positive eBay-Gutschriften der Ausgaben-Kategorie
# "Shopping & Kleidung" zu (passte nur zum Haendlernamen, nicht zum
# Vorzeichen) - das liess die Kategorie rechnerisch positiv werden. Fest
# codiert statt der KI überlassen, weil es eine eindeutige Nutzer-Vorgabe ist,
# kein Graubereich ("eBay ist immer Verkaufserlös, alles andere ist Retoure").
DETERMINISTIC_RULES = [
    (re.compile(r"ebay", re.IGNORECASE), lambda amount: amount > 0, "Nebeneinkommen"),
]


def _apply_deterministic_rules(pending: list[models.Transaction], cat_by_name: dict) -> tuple[list[models.Transaction], int]:
    remaining = []
    matched = 0
    for t in pending:
        hit = False
        for pattern, sign_ok, cat_name in DETERMINISTIC_RULES:
            if pattern.search(t.description or "") and sign_ok(t.amount):
                cat = cat_by_name.get(cat_name.strip().lower())
                if cat:
                    t.category_id = cat.id
                    t.categorized_at = datetime.utcnow()
                    matched += 1
                    hit = True
                break
        if not hit:
            remaining.append(t)
    return remaining, matched


# Unterhalb dieser Konfidenz wird ein Vorschlag nicht mal in die Review-
# Warteschlange gelegt - reines Rauschen (die KI hat wirklich geraten, siehe
# _prompt: "0 = geraten"), damit die Queue nicht mit wertlosen Vorschlägen
# vollläuft, die niemand je bestätigen würde.
QUEUE_MIN_CONFIDENCE = 0.35


class CategorizeResult(NamedTuple):
    categorized: int
    skipped: int
    queued: int
    error: str | None


def _extract_json_array(text: str) -> list:
    match = _ARRAY_RE.search(text)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _prompt(categories: list[models.Category], batch: list[models.Transaction]) -> str:
    lines = [
        "Du ordnest Kontobuchungen von Kies, einem privaten Finanztool, bestehenden Kategorien zu.",
        "Antworte NUR mit einem JSON-Array, ein Objekt pro Buchung, keine Erklärung außenrum:",
        '[{"id": 123, "category": "Lebensmittel", "confidence": 0.9}]',
        "- confidence: deine Sicherheit zwischen 0 und 1 (0 = geraten, 1 = eindeutig).",
        "- category: EXAKT einer der folgenden Namen (keine Erfindungen, keine Abweichungen):",
        ", ".join(c.name for c in categories),
        "- Bist du dir nicht sicher, gib trotzdem dein bestes category ist mit niedriger confidence an -",
        "  wird ohnehin nur ab einer bestimmten Sicherheit übernommen.",
        "",
        "Buchungen:",
    ]
    for t in batch:
        line = f'- id={t.id}, Betrag={t.amount:.2f} EUR, Beschreibung="{t.description or ""}"'
        # Notiz zusaetzlich mitgeben, wenn sie ueber die Beschreibung hinaus
        # etwas hergibt - bei manchen Quellen (z.B. PayPal-Buchungen ueber die
        # Bank) steht der eigentliche Haendler nur im Verwendungszweck, nicht
        # im Beschreibungsfeld selbst.
        if t.notes and t.notes.strip() and t.notes.strip() != (t.description or "").strip():
            line += f', Verwendungszweck="{t.notes.strip()[:200]}"'
        lines.append(line)
    return "\n".join(lines)


def auto_categorize(db: Session, space_id: int, settings: models.Settings) -> CategorizeResult:
    model = settings.ollama_model or settings.beleg_chat_model
    if not settings.ollama_url or not model:
        return CategorizeResult(0, 0, 0, "Ollama-Server-URL/Modell nicht konfiguriert")

    categories = crud.get_categories(db)
    if not categories:
        return CategorizeResult(0, 0, 0, None)
    cat_by_name = {c.name.strip().lower(): c for c in categories}

    pending = (
        db.query(models.Transaction)
        .join(models.Account)
        .filter(
            models.Account.space_id == space_id,
            models.Transaction.category_id.is_(None),
            models.Transaction.is_transfer.is_(False),
        )
        .order_by(models.Transaction.date.desc())
        .limit(MAX_PENDING_PER_RUN)
        .all()
    )
    if not pending:
        return CategorizeResult(0, 0, 0, None)

    categorized = 0
    skipped = 0
    queued = 0
    pending, deterministic_hits = _apply_deterministic_rules(pending, cat_by_name)
    categorized += deterministic_hits
    if deterministic_hits:
        db.commit()
    if not pending:
        return CategorizeResult(categorized, skipped, queued, None)

    # Bereits vorhandene Vorschläge (jeder Status) vorab laden statt pro Zeile
    # einzeln nachzufragen - verhindert UNIQUE-Konflikte beim Anlegen (siehe
    # models.CategorySuggestion-Docstring: ein einmal entschiedener Vorschlag
    # für dieselbe Buchung+Kategorie soll nicht erneut auftauchen).
    existing_suggestions = {
        (s.transaction_id, s.suggested_category_id)
        for s in db.query(models.CategorySuggestion.transaction_id, models.CategorySuggestion.suggested_category_id)
    }

    for i in range(0, len(pending), BATCH_SIZE):
        batch = pending[i:i + BATCH_SIZE]
        by_id = {t.id: t for t in batch}
        try:
            reply = ollama_client.generate(settings.ollama_url, model, _prompt(categories, batch))
        except Exception:
            skipped += len(batch)
            continue
        rows = _extract_json_array(reply)
        matched_ids = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            tx = by_id.get(row.get("id"))
            if tx is None:
                continue
            matched_ids.add(tx.id)
            confidence = row.get("confidence")
            cat = cat_by_name.get(str(row.get("category", "")).strip().lower())
            if cat is None or not isinstance(confidence, (int, float)):
                skipped += 1
                continue
            if confidence >= CONFIDENCE_THRESHOLD:
                tx.category_id = cat.id
                tx.categorized_at = datetime.utcnow()
                categorized += 1
            elif confidence >= QUEUE_MIN_CONFIDENCE and (tx.id, cat.id) not in existing_suggestions:
                db.add(models.CategorySuggestion(
                    transaction_id=tx.id, suggested_category_id=cat.id, confidence=confidence,
                ))
                existing_suggestions.add((tx.id, cat.id))
                queued += 1
            else:
                skipped += 1
        # Buchungen, zu denen die KI gar keine Zeile geliefert hat, zählen ebenfalls
        # als übersprungen statt stillschweigend zu verschwinden.
        skipped += len(batch) - len(matched_ids)

    if categorized or queued:
        db.commit()
    return CategorizeResult(categorized, skipped, queued, None)
