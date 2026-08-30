"""Proaktiver KI-Assistent: schaut mehrmals täglich über einen breiten
Lebens-Snapshot und meldet sich per Telegram NUR, wenn die lokale Ollama
darin eine wirklich nützliche, nicht offensichtliche Beobachtung, Erinnerung
oder Anregung findet.

Bewusst getrennt von den bestehenden, rein regelbasierten Jobs
(_scheduled_suggestion_check, _scheduled_anomaly_check, _scheduled_digest,
morning_briefing): die machen feste Einzelprüfungen, das hier ist der
freie "Assistent denkt über dein Leben nach"-Teil - das langfristige Ziel.

Absicherungen gegen Nervigkeit:
  * opt-in (Settings.proactive_assistant_enabled, Default aus)
  * Mindestabstand zwischen zwei Meldungen (min_gap_hours, Default 4 h)
  * Dedup über einen Hash der letzten Meldung
  * Ruhezeiten greifen ohnehin in notifications.notify()
  * die KI wird explizit angewiesen, "NICHTS" zu antworten, wenn nichts
    einen Ping wert ist - und kurze/leere Antworten werden verworfen
"""

import hashlib
from datetime import date, datetime, timedelta

from . import crud, models, ollama_client

_NOTHING_TOKENS = ("NICHTS", "NOTHING", "KEIN VORSCHLAG", "KEINE MELDUNG")

_SYSTEM = (
    "Du bist Kies - ein persönlicher, proaktiver Assistent (wie Jarvis). Du bekommst "
    "einen kompakten Snapshot vom Leben deines Nutzers: Finanzen, Termine, Todos, Ziele, "
    "Lebensbereiche, Fristen. Deine Aufgabe: entscheide, ob es GERADE JETZT genau EINE "
    "wirklich nützliche, nicht offensichtliche Sache gibt, die eine kurze Telegram-Nachricht "
    "wert ist - eine Erinnerung, eine Beobachtung, ein konkreter Vorschlag oder eine Frage, "
    "die dem Nutzer hilft.\n"
    "Regeln:\n"
    "- Wenn nichts einen Ping wert ist (der Normalfall!), antworte mit EXAKT: NICHTS\n"
    "- Sonst: 1-2 kurze deutsche Sätze, direkt, ohne Anrede/Grußformel, ohne Emojis.\n"
    "- Keine reine Wiederholung von etwas, das im Snapshot schon offensichtlich steht.\n"
    "- Keine Zahlen erfinden, keine Anlageberatung.\n"
    "- Lieber NICHTS als etwas Belangloses."
)


def _fmt_eur(v) -> str:
    try:
        return f"{float(v):,.0f} €".replace(",", ".")
    except (TypeError, ValueError):
        return "–"


def build_snapshot(db, settings, space_id: int) -> str:
    """Kompakter Mehr-Domänen-Text als KI-Kontext. Jede Teilabfrage ist
    einzeln abgesichert - eine kaputte Domäne darf den Snapshot nicht kippen."""
    today = date.today()
    lines: list[str] = [f"Datum/Uhrzeit: {datetime.now().strftime('%a %d.%m.%Y %H:%M')}"]

    try:
        nw = crud.net_worth(db, space_id)
        lines.append(f"Nettovermögen: {_fmt_eur(nw.total)}")
    except Exception:
        pass

    try:
        ds = crud.dashboard_summary(db, space_id, today.year, today.month)
        inc = getattr(ds, "income", None) or (ds.get("income") if isinstance(ds, dict) else None)
        exp = getattr(ds, "expenses", None) or (ds.get("expenses") if isinstance(ds, dict) else None)
        if inc is not None or exp is not None:
            lines.append(f"Diesen Monat: Einnahmen {_fmt_eur(inc)}, Ausgaben {_fmt_eur(exp)}")
    except Exception:
        pass

    try:
        budgets = crud.get_budgets(db, space_id) or []
        over = [b for b in budgets if getattr(b, "spent", 0) and getattr(b, "amount", 0)
                and b.spent > b.amount]
        if over:
            lines.append("Budget überschritten: " + ", ".join(
                f"{b.category_name if hasattr(b, 'category_name') else 'Kategorie'} "
                f"({_fmt_eur(b.spent)}/{_fmt_eur(b.amount)})" for b in over[:4]))
    except Exception:
        pass

    try:
        overdue = (db.query(models.Todo)
                   .filter(models.Todo.done.is_(False), models.Todo.due_date.isnot(None),
                           models.Todo.due_date < today).count())
        soon = (db.query(models.Todo)
                .filter(models.Todo.done.is_(False), models.Todo.due_date.isnot(None),
                        models.Todo.due_date >= today, models.Todo.due_date <= today + timedelta(days=2))
                .order_by(models.Todo.due_date).limit(5).all())
        if overdue:
            lines.append(f"Überfällige Todos: {overdue}")
        if soon:
            lines.append("Todos fällig in 2 Tagen: " + "; ".join(t.title for t in soon))
    except Exception:
        pass

    try:
        events = crud.get_upcoming_calendar_events(db, days=2, limit=8)
        if events:
            lines.append("Termine nächste 48 h: " + "; ".join(
                f"{e.title} ({e.start[:16].replace('T', ' ')})" for e in events))
    except Exception:
        pass

    try:
        goals = (db.query(models.Goal)
                 .filter(models.Goal.status == "open")
                 .order_by(models.Goal.target_date.is_(None), models.Goal.target_date)
                 .limit(6).all())
        if goals:
            lines.append("Offene Ziele: " + "; ".join(
                f"{g.title}" + (f" (bis {g.target_date})" if g.target_date else "") for g in goals))
    except Exception:
        pass

    try:
        cutoff = today + timedelta(days=30)
        reminders = (db.query(models.ContractReminder)
                     .filter(models.ContractReminder.renewal_date <= cutoff)
                     .order_by(models.ContractReminder.renewal_date).limit(5).all())
        if reminders:
            lines.append("Kündigungsfristen < 30 Tage: " + "; ".join(
                f"{r.label} (Verlängerung {r.renewal_date})" for r in reminders))
    except Exception:
        pass

    try:
        wl = (db.query(models.WishlistItem)
              .filter(models.WishlistItem.active.is_(True), models.WishlistItem.purchased.is_(False))
              .count())
        if wl:
            lines.append(f"Aktive Wünsche auf der Liste: {wl}")
    except Exception:
        pass

    try:
        lines += _health_lines(db)
    except Exception:
        pass

    return "\n".join(lines)


def _avg(vals) -> float | None:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _health_lines(db) -> list[str]:
    """Auffällige Gesundheits-Trends aus health_metrics (Apple-Health-Import) -
    nur was heraussticht, plus je Kennzahl der letzte Wert als Kontext."""
    out: list[str] = []
    for mt, label, unit in (
        (models.HealthMetricType.schlaf, "Schlaf", "h"),
        (models.HealthMetricType.schritte, "Schritte", ""),
        (models.HealthMetricType.gewicht, "Gewicht", "kg"),
        (models.HealthMetricType.puls, "Ruhepuls", "bpm"),
    ):
        rows = crud.get_health_metrics(db, mt, days=30)
        if not rows:
            continue
        vals = [r.value for r in rows]
        last = vals[-1]
        shown = f"{last:.1f} kg" if mt == models.HealthMetricType.gewicht else \
                f"{last:.1f} h" if mt == models.HealthMetricType.schlaf else \
                f"{round(last)}{(' ' + unit) if unit else ''}"
        note = f"{label}: zuletzt {shown}"

        if mt == models.HealthMetricType.schlaf and len(vals) >= 3 and all(v < 6 for v in vals[-3:]):
            note += " – 3 Nächte in Folge unter 6 h"
        elif mt == models.HealthMetricType.schritte and len(vals) >= 10:
            wk = _avg(vals[-7:]); prev = _avg(vals[-14:-7])
            if wk and prev and wk < prev * 0.65:
                note += f" – diese Woche im Schnitt deutlich weniger ({round(wk)} statt {round(prev)})"
        elif mt == models.HealthMetricType.gewicht and len(vals) >= 2:
            delta = vals[-1] - vals[0]
            if abs(delta) >= 2:
                note += f" – {delta:+.1f} kg in ~{(rows[-1].date - rows[0].date).days} Tagen"
        elif mt == models.HealthMetricType.puls and len(vals) >= 10:
            recent = _avg(vals[-7:]); base = _avg(vals[:-7])
            if recent and base and recent > base + 4:
                note += f" – zuletzt erhöht (Ø {round(recent)} vs. {round(base)})"
        out.append(note)
    return out


def _chat_model(settings) -> str | None:
    return settings.ollama_model or settings.beleg_chat_model or None


# Harte Untergrenze zwischen zwei Meldungen, egal wie der Job getaktet ist -
# verhindert nur, dass sich zwei ueberlappende/nachgeholte Laeufe doppeln.
# Ansonsten darf sich der Assistent so oft melden, wie er wirklich etwas Neues
# hat (Wunsch des Nutzers) - der Dedup-Hash haelt Wiederholungen raus.
_MIN_GAP_SECONDS = 8 * 60


def _hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode("utf-8")).hexdigest()[:16]


def generate(db, settings) -> tuple[str, str] | None:
    """Gibt (text, reply_hash) zurück, wenn die KI eine proaktive Meldung hat -
    sonst None.

    Nebeneffekt: schreibt `settings.proactive_assistant_last_snapshot_hash`
    fort, sobald ein Snapshot ausgewertet wurde (auch wenn die KI "NICHTS"
    sagt) - der Aufrufer muss danach committen. Dadurch wird die KI beim
    10-Minuten-Takt nur befragt, wenn sich am Lebens-Snapshot wirklich etwas
    geändert hat, statt bei jedem Lauf.
    """
    if not (settings.proactive_assistant_enabled and settings.notifications_enabled):
        return None
    model = _chat_model(settings)
    if not (settings.ollama_url and model):
        return None

    snoozed = getattr(settings, "proactive_assistant_snoozed_until", None)
    if snoozed and datetime.utcnow() < snoozed:
        return None

    last = settings.proactive_assistant_last_sent_at
    if last and (datetime.utcnow() - last).total_seconds() < _MIN_GAP_SECONDS:
        return None

    spaces = crud.get_spaces(db)
    space_id = spaces[0].id if spaces else 1
    snapshot = build_snapshot(db, settings, space_id)

    # Nichts Substanzielles (nur Datum + evtl. Nettovermögen) ODER unveränderter
    # Snapshot seit dem letzten Lauf -> gar nicht erst die KI bemühen.
    snap_hash = _hash(snapshot)
    if len(snapshot.splitlines()) <= 2 or snap_hash == (settings.proactive_assistant_last_snapshot_hash or ""):
        return None
    settings.proactive_assistant_last_snapshot_hash = snap_hash

    try:
        reply = ollama_client.chat(
            settings.ollama_url, model,
            [{"role": "system", "content": _SYSTEM},
             {"role": "user", "content": "Snapshot:\n" + snapshot}],
            timeout=90,
        ).strip()
    except Exception:
        return None

    compact = reply.strip().strip(".").upper()
    if len(reply.strip()) < 12 or any(compact.startswith(tok) for tok in _NOTHING_TOKENS):
        return None

    h = _hash(reply)
    if h == (settings.proactive_assistant_last_hash or ""):
        return None
    return reply, h


def preview(db, settings) -> str:
    """Wie generate(), aber OHNE die Gates (opt-in, Abstand, Snooze, Dedup,
    unveränderter Snapshot) und ohne Nebeneffekte - für einen Testknopf, der
    zeigt, wie eine proaktive Meldung aussähe. Fällt auf einen Beispieltext
    zurück, wenn die KI "NICHTS" sagt oder Ollama fehlt."""
    example = ("Du hast diese Woche im Schnitt deutlich weniger Schritte gemacht als sonst "
               "und morgen steht ein Termin ohne Ort im Kalender - willst du kurz beides klären?")
    model = _chat_model(settings)
    if not (settings.ollama_url and model):
        return example
    spaces = crud.get_spaces(db)
    space_id = spaces[0].id if spaces else 1
    snapshot = build_snapshot(db, settings, space_id)
    try:
        reply = ollama_client.chat(
            settings.ollama_url, model,
            [{"role": "system", "content": _SYSTEM},
             {"role": "user", "content": "Snapshot:\n" + snapshot}],
            timeout=90,
        ).strip()
    except Exception:
        return example
    compact = reply.strip().strip(".").upper()
    if len(reply.strip()) < 12 or any(compact.startswith(tok) for tok in _NOTHING_TOKENS):
        return example
    return reply
