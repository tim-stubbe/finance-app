"""Dauerhaftes Gedächtnis des Assistenten.

Zwei Bausteine:

- **Langzeit** (`AssistantMemory`): ein Fakt / eine Präferenz / ein Vorhaben
  je Zeile. `build_memory_block()` speist die wichtigsten davon in die Prompts
  von proactive.py, telegram_bot.py und jarvis.py ein - so muss Tim dem
  Assistenten Dinge nicht bei jedem Gespräch neu sagen.
- **Kurzzeit** (`ConversationTurn`): der Telegram-Freitext-Verlauf, dauerhaft
  statt nur im RAM. `load_history_for_prompt()` gibt ihn zeit- und
  zeichen-budgetiert zurück, `compress_old_turns()` verdichtet Altes zu einer
  `zusammenfassung`-Memory.

Kein Cloud-LLM: `distill_recent()` und `compress_old_turns()` laufen über die
lokale Ollama. Helfer committen NICHT selbst (Aufrufer committen), Ausnahmen
sind unten vermerkt.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta

from . import models, ollama_client

# Explizite Kontextfenster für die grossen Chat-Calls. Ollama-Default (2048/
# 4096) schneidet den Prompt sonst still ab - genau der Effekt, den das
# Gedächtnis verhindern soll.
NUM_CTX_CHAT = 8192
NUM_CTX_PROACTIVE = 8192

_CATEGORIES = ("fakt", "praeferenz", "vorhaben", "erledigt", "kontext", "zusammenfassung")

_DISTILL_SYSTEM = (
    "Du pflegst das Langzeitgedächtnis eines persönlichen Assistenten. Lies das "
    "Gespräch und nenne NUR dauerhaft nützliche Fakten, die Tim AUSDRÜCKLICH "
    "gesagt hat (Präferenzen, feste Vorhaben, Rahmenbedingungen). Nichts "
    "raten, nichts herleiten, keine Tageskleinigkeiten. Wenn nichts Neues da "
    "ist: leere Liste. Antworte AUSSCHLIESSLICH als JSON: "
    '{"facts":[{"text":"<ein knapper Satz>","category":"fakt|praeferenz|vorhaben|kontext","importance":1|2}]}'
)

_COMPRESS_SYSTEM = (
    "Fasse den folgenden Gesprächsausschnitt in 3-5 knappen deutschen "
    "Stichpunkten zusammen: offene Punkte, getroffene Entscheidungen, genannte "
    "Fakten. Kein Vorspann, nur die Stichpunkte mit '- '."
)


# --------------------------------------------------------------------------- #
# Kleine Helfer
# --------------------------------------------------------------------------- #
def est_tokens(text: str) -> int:
    """Grobe Token-Schätzung (~4 Zeichen/Token) - nur fürs Budgetieren."""
    return (len(text or "") + 3) // 4


def _slugify(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", (text or "").lower().replace("ä", "ae")
                       .replace("ö", "oe").replace("ü", "ue").replace("ß", "ss"))
    slug = "-".join(words[:6])[:60].strip("-")
    return slug or "notiz"


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 3}


def _jaccard(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _now() -> datetime:
    return datetime.utcnow()


# --------------------------------------------------------------------------- #
# Langzeit: schreiben / verwalten
# --------------------------------------------------------------------------- #
def add_memory(db, *, text: str, category: str = "fakt", source: str = "manuell",
               importance: int = 2, key: str | None = None,
               expires_at: datetime | None = None, pinned: bool = False):
    """Fakt merken (Upsert per `key`). Gibt die Zeile zurück, oder die
    bestehende ähnliche Zeile, wenn der Text quasi schon da ist. Committet
    NICHT."""
    text = (text or "").strip()
    if not text:
        return None
    if category not in _CATEGORIES:
        category = "fakt"
    importance = max(1, min(3, int(importance or 2)))

    # Schon (fast) wörtlich vorhanden? -> nichts Neues anlegen.
    existing_similar = None
    for row in db.query(models.AssistantMemory).filter(
            models.AssistantMemory.status == "aktiv").all():
        if _jaccard(row.text, text) >= 0.6:
            existing_similar = row
            break
    if existing_similar is not None and not key:
        return existing_similar

    slug = key or _slugify(text)
    row = (db.query(models.AssistantMemory)
           .filter(models.AssistantMemory.key == slug).first())
    if row is not None:
        # Kollidiert der Slug mit inhaltlich fremdem Text -> eindeutigen Key.
        if _jaccard(row.text, text) < 0.3:
            slug = f"{slug}-{hashlib.sha1(text.encode('utf-8')).hexdigest()[:4]}"
            row = (db.query(models.AssistantMemory)
                   .filter(models.AssistantMemory.key == slug).first())

    if row is None:
        row = models.AssistantMemory(key=slug, text=text, category=category,
                                     source=source, importance=importance,
                                     pinned=pinned, expires_at=expires_at,
                                     status="aktiv")
        db.add(row)
    else:
        row.text = text
        row.category = category
        row.importance = importance
        row.status = "aktiv"
        row.updated_at = _now()
        if expires_at is not None:
            row.expires_at = expires_at
        if pinned:
            row.pinned = True
    return row


def forget_memory(db, *, key: str | None = None, mem_id: int | None = None,
                  hard: bool = False) -> bool:
    """Gemerkten Punkt vergessen (soft: status='verworfen'). Committet NICHT."""
    q = db.query(models.AssistantMemory)
    row = (q.filter(models.AssistantMemory.id == mem_id).first() if mem_id
           else q.filter(models.AssistantMemory.key == key).first())
    if row is None:
        return False
    if hard:
        db.delete(row)
    else:
        row.status = "verworfen"
        row.updated_at = _now()
    return True


def _active_query(db):
    now = _now()
    return (db.query(models.AssistantMemory)
            .filter(models.AssistantMemory.status == "aktiv")
            .filter((models.AssistantMemory.expires_at.is_(None))
                    | (models.AssistantMemory.expires_at > now)))


def _ordered(rows: list) -> list:
    return sorted(rows, key=lambda r: (
        r.pinned,
        r.importance,
        r.last_used_at or datetime.min,
        r.updated_at or datetime.min,
    ), reverse=True)


def list_memories(db, *, include_inactive: bool = False, limit: int = 200) -> list:
    q = db.query(models.AssistantMemory)
    if not include_inactive:
        q = _active_query(db)
    return _ordered(q.all())[:limit]


# --------------------------------------------------------------------------- #
# Langzeit: einspeisen
# --------------------------------------------------------------------------- #
def build_memory_block(db, char_budget: int = 1500) -> str:
    """Die wichtigsten Merksätze als Prompt-Block. Leerstring wenn nichts.
    Seiteneffekt: `last_used_at` der eingespeisten Zeilen wird gebumpt
    (eigener Commit, in try/except - darf die Antwort nie blockieren)."""
    try:
        rows = _ordered(_active_query(db).all())
    except Exception:
        return ""
    if not rows:
        return ""

    picked, out, used = [], ["Was ich mir gemerkt habe:"], len("Was ich mir gemerkt habe:")
    for r in rows:
        line = f"- {r.text}"
        if used + len(line) + 1 > char_budget:
            break
        out.append(line)
        used += len(line) + 1
        picked.append(r.id)
    if len(out) == 1:
        return ""

    try:
        now = _now()
        (db.query(models.AssistantMemory)
         .filter(models.AssistantMemory.id.in_(picked))
         .update({models.AssistantMemory.last_used_at: now}, synchronize_session=False))
        db.commit()
    except Exception:
        db.rollback()
    return "\n".join(out) + "\n\n"


# --------------------------------------------------------------------------- #
# Kurzzeit: Chatverlauf
# --------------------------------------------------------------------------- #
def append_turn(db, role: str, content: str, chat_id: str | None = None) -> None:
    """Einen Chat-Zug persistieren. Committet."""
    content = (content or "").strip()
    if not content:
        return
    db.add(models.ConversationTurn(
        role="assistant" if role == "assistant" else "user",
        content=content, chat_id=str(chat_id) if chat_id is not None else None))
    db.commit()


def load_history_for_prompt(db, char_budget: int = 6000, chat_id: str | None = None,
                            max_age_hours: int = 48) -> list[dict]:
    """Verlauf als [{"role","content"}] - zeit- UND budget-gekappt,
    chronologisch."""
    since = _now() - timedelta(hours=max_age_hours)
    q = (db.query(models.ConversationTurn)
         .filter(models.ConversationTurn.created_at >= since))
    if chat_id is not None:
        q = q.filter(models.ConversationTurn.chat_id == str(chat_id))
    rows = q.order_by(models.ConversationTurn.id.desc()).limit(60).all()

    picked, used = [], 0
    for r in rows:  # von neu nach alt, bis Budget voll
        used += len(r.content)
        if used > char_budget:
            break
        picked.append(r)
    picked.reverse()
    return [{"role": r.role, "content": r.content} for r in picked]


def compress_old_turns(db, settings, keep_chars: int = 6000,
                       chat_id: str | None = None):
    """Wenn der Verlauf das Budget sprengt: die ältesten überzähligen Züge von
    der KI zusammenfassen lassen, als `zusammenfassung`-Memory ablegen (Upsert
    pro ISO-Woche) und die Züge löschen. Committet. Gibt die Memory zurück
    oder None."""
    model = settings.ollama_model or settings.beleg_chat_model or None
    if not (settings.ollama_url and model):
        return None

    q = db.query(models.ConversationTurn)
    if chat_id is not None:
        q = q.filter(models.ConversationTurn.chat_id == str(chat_id))
    rows = q.order_by(models.ConversationTurn.id.asc()).all()
    if not rows:
        return None

    # Wieviel vom Ende passt ins Budget? Der Rest davor wird verdichtet.
    used, keep_from = 0, len(rows)
    for i in range(len(rows) - 1, -1, -1):
        used += len(rows[i].content)
        if used > keep_chars:
            keep_from = i + 1
            break
    else:
        return None  # alles passt

    old = rows[:keep_from]
    if len(old) < 4:
        return None

    convo = "\n".join(f"{r.role}: {r.content}" for r in old)[:8000]
    try:
        summary = ollama_client.chat(
            settings.ollama_url, model,
            [{"role": "system", "content": _COMPRESS_SYSTEM},
             {"role": "user", "content": convo}],
            timeout=180, options={"num_predict": 400, "num_ctx": NUM_CTX_PROACTIVE},
        ).strip()
    except Exception:
        return None
    if not summary:
        return None

    iso = _now().isocalendar()
    mem = add_memory(db, text=summary, category="zusammenfassung",
                     source="destillation", importance=2,
                     key=f"gespraechszusammenfassung-{iso[0]}-w{iso[1]:02d}")
    for r in old:
        db.delete(r)
    db.commit()
    return mem


# --------------------------------------------------------------------------- #
# Destillation (nächtlicher Job)
# --------------------------------------------------------------------------- #
def distill_recent(db, settings, max_new: int = 5) -> list:
    """Liest die letzten 24 h Gespräch + beantwortete Vorschläge und legt
    daraus leise neue Merksätze an (nie importance 3, nie pinned). Committet.
    Gibt die neuen Zeilen zurück."""
    model = settings.ollama_model or settings.beleg_chat_model or None
    if not (settings.ollama_url and model):
        return []

    since = _now() - timedelta(hours=24)
    turns = (db.query(models.ConversationTurn)
             .filter(models.ConversationTurn.created_at >= since)
             .order_by(models.ConversationTurn.id.asc()).limit(40).all())
    proposals = (db.query(models.ProactiveProposal)
                 .filter(models.ProactiveProposal.answered_at.isnot(None),
                         models.ProactiveProposal.answered_at >= since).all())
    if not turns and not proposals:
        return []

    parts = ["Bereits bekannt:\n" + (build_memory_block(db, 1200) or "(nichts)")]
    if turns:
        parts.append("Gespräch:\n" + "\n".join(f"{t.role}: {t.content}" for t in turns))
    if proposals:
        parts.append("Beantwortete Vorschläge:\n" + "\n".join(
            f"- {p.title} -> {p.chosen_key or '?'} ({p.result_text or ''})" for p in proposals))
    user_msg = "\n\n".join(parts)[:9000]

    try:
        raw = ollama_client.chat(
            settings.ollama_url, model,
            [{"role": "system", "content": _DISTILL_SYSTEM},
             {"role": "user", "content": user_msg}],
            timeout=180, format="json", options={"num_predict": 600, "num_ctx": NUM_CTX_PROACTIVE},
        )
    except Exception:
        return []

    import json
    try:
        i, j = raw.find("{"), raw.rfind("}")
        facts = json.loads(raw[i:j + 1]).get("facts") or []
    except (ValueError, json.JSONDecodeError):
        return []

    created = []
    for f in facts[:max_new]:
        if not isinstance(f, dict):
            continue
        text = (f.get("text") or "").strip()
        if not text:
            continue
        row = add_memory(db, text=text, category=f.get("category", "fakt"),
                         source="destillation",
                         importance=min(2, int(f.get("importance", 2) or 2)))
        if row is not None and row not in created:
            created.append(row)
    db.commit()
    return created


# --------------------------------------------------------------------------- #
# Aufräumen (wöchentlicher Job)
# --------------------------------------------------------------------------- #
def prune(db, keep_active: int = 130) -> int:
    """Abgelaufenes/Verworfenes/alte Zusammenfassungen weg, aktive Menge
    deckeln, alten Chatverlauf abschneiden. `pinned` bleibt unangetastet.
    Committet. Gibt die Anzahl gelöschter Zeilen zurück."""
    now = _now()
    M = models.AssistantMemory
    n = 0

    n += db.query(M).filter(M.expires_at.isnot(None), M.expires_at < now,
                            M.pinned.is_(False)).delete(synchronize_session=False)
    n += (db.query(M)
          .filter(M.status.in_(("erledigt", "verworfen")),
                  M.updated_at < now - timedelta(days=30), M.pinned.is_(False))
          .delete(synchronize_session=False))
    n += (db.query(M)
          .filter(M.category == "zusammenfassung",
                  M.updated_at < now - timedelta(days=60), M.pinned.is_(False))
          .delete(synchronize_session=False))

    active = _ordered(db.query(M).filter(M.status == "aktiv", M.pinned.is_(False)).all())
    for row in active[keep_active:]:
        db.delete(row)
        n += 1

    n += (db.query(models.ConversationTurn)
          .filter((models.ConversationTurn.summarized.is_(True))
                  | (models.ConversationTurn.created_at < now - timedelta(days=14)))
          .delete(synchronize_session=False))
    db.commit()
    return n


# --------------------------------------------------------------------------- #
# Obsidian-Export (Einweg DB -> Datei, wird nie zurückgelesen)
# --------------------------------------------------------------------------- #
def export_obsidian(db) -> str | None:
    """Schreibt das aktive Gedächtnis als Markdown nach
    $DATA_DIR/obsidian/Kies-Gedaechtnis.md. Gibt den Pfad zurück."""
    data_dir = os.environ.get("DATA_DIR", "/data")
    target_dir = os.path.join(data_dir, "obsidian")
    try:
        os.makedirs(target_dir, exist_ok=True)
    except OSError:
        return None
    path = os.path.join(target_dir, "Kies-Gedaechtnis.md")

    rows = _ordered(_active_query(db).all())
    lines = ["---", f"aktualisiert: {_now().isoformat(timespec='seconds')}Z",
             f"eintraege: {len(rows)}", "---", "", "# Kies-Gedächtnis", ""]
    for cat in _CATEGORIES:
        grp = [r for r in rows if r.category == cat]
        if not grp:
            continue
        lines.append(f"## {cat}")
        for r in grp:
            pin = " 📌" if r.pinned else ""
            lines.append(f"- {r.text}  _(⋆{r.importance}, {r.source}){pin}_")
        lines.append("")

    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        os.replace(tmp, path)
    except OSError:
        return None
    return path
