"""Proaktiver KI-Assistent: schaut mehrmals täglich über einen breiten
Lebens-Snapshot und meldet sich per Telegram - aber nicht mehr mit einem
einzelnen Satz, sondern mit einem **strukturierten Vorschlag**: einer
Beobachtung, einer Ja/Nein-Sache oder einer echten Auswahlfrage mit mehreren
Optionen, hinter denen jeweils eine ausführbare Aktion steckt
(siehe proactive_actions.py, models.ProactiveProposal).

Ziel (siehe [[feedback-push-not-pull]]): Tim soll KEINEN Tab bedienen müssen.
Kies erkennt die Sache, bereitet die Entscheidung auf, schickt sie ihm - und
handelt, sobald er eine Option wählt.

Kein Cloud-LLM: alles über die lokale Ollama. Absicherung: opt-in
(Settings.proactive_assistant_enabled), die KI kann nur Aktionen aus der
Allowlist wählen, und ein `dedup_key` verhindert, dass derselbe Vorschlag
immer wieder auftaucht.
"""

import json
import hashlib
from datetime import date, datetime, timedelta

from . import crud, models, ollama_client, proactive_actions

_NOTHING_TOKENS = ("NICHTS", "NOTHING", "KEIN VORSCHLAG", "KEINE MELDUNG")

_SYSTEM = (
    "Du bist Kies - Tims persönlicher, proaktiver Assistent (wie Jarvis). Dein "
    "EINZIGER Zweck: Tim Zeit sparen, damit er in seinen 24 Stunden mehr schafft. "
    "Du bekommst einen kompakten Snapshot seines Lebens (Finanzen, Termine, Todos, "
    "Ziele, Fristen, Fahrten, Gesundheit, Haus).\n\n"
    "Melde dich, wenn du EINE dieser Situationen siehst:\n"
    "1. Eine Entscheidung steht an, die du vorbereiten oder ihm abnehmen kannst.\n"
    "2. Etwas wird teurer / schlimmer / unwiederbringlich, wenn es liegen bleibt "
    "(Frist, Vertrag, Termin ohne Ort/Zeit, überfällige Sache).\n"
    "3. Mehrere Kleinigkeiten lassen sich in einem Rutsch erledigen.\n"
    "4. Du kannst etwas sofort tun, sobald Tim eine Option wählt.\n\n"
    "Sei NICHT übervorsichtig: wenn der Snapshot Inhalt hat und gerade nichts "
    "Dringendes offen ist, findest du trotzdem meist eine sinnvolle Anregung. "
    "Stell ruhig komplexe Fragen mit 2-5 Optionen - Ja/Nein ist oft zu simpel.\n"
    "Das Wertvollste: VERKNÜPFE Punkte aus verschiedenen Bereichen zu EINER "
    "Einsicht, statt sie einzeln abzuarbeiten. Beispiel: Todo 'Grafikkarte "
    "ausbauen' + Ziel 'Umzug Schweiz' + '190 Fahrten unklassifiziert' + "
    "anstehende Steuer -> ein Vorschlag, der das zusammenbringt. Ein guter "
    "Vorschlag spart Tim mehrere Handgriffe auf einmal.\n\n"
    "Du antwortest AUSSCHLIESSLICH mit JSON, HÖCHSTENS 3 Vorschläge, in genau "
    "dieser Form:\n"
    '{"proposals": [\n'
    '  {"kind": "wahl|bestaetigen|info",\n'
    '   "urgency": "hoch|mittel|niedrig",\n'
    '   "title": "kurze Überschrift (max 6 Wörter)",\n'
    '   "body": "GENAU EIN kurzer Satz: warum das jetzt kommt und was es spart",\n'
    '   "dedup": "stabiler-schluessel-ohne-datum",\n'
    '   "options": [\n'
    '      {"label": "Klartext für den Button", "action": {"type": "...", "params": {...}}}\n'
    "   ]}\n"
    "]}\n\n"
    "Halte body kurz - keine langen Erklärungen, kein Zeilenumbruch im Text.\n"
    "Regeln für options:\n"
    "- Bei kind=info: options weglassen oder leer.\n"
    "- Bei kind=bestaetigen/wahl: 2-5 Optionen, die LETZTE ist immer eine "
    'Ausweichoption ({"type":"dismiss"} oder {"type":"remind_later","params":{"days":N}}).\n'
    "- action.type MUSS aus dieser Liste sein, sonst nimm \"open\":\n"
    + proactive_actions.CATALOG_FOR_PROMPT + "\n\n"
    "- Keine Zahlen erfinden. Keine Anlageberatung. Kein Geld bewegen.\n"
    "- Wenn wirklich GAR NICHTS einen Ping wert ist: {\"proposals\": []}"
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
                           models.Todo.due_date < today).all())
        soon = (db.query(models.Todo)
                .filter(models.Todo.done.is_(False), models.Todo.due_date.isnot(None),
                        models.Todo.due_date >= today, models.Todo.due_date <= today + timedelta(days=2))
                .order_by(models.Todo.due_date).limit(5).all())
        if overdue:
            lines.append(f"Überfällige Todos ({len(overdue)}): "
                         + "; ".join(t.title for t in overdue[:6]))
        if soon:
            lines.append("Todos fällig in 2 Tagen: " + "; ".join(t.title for t in soon))
    except Exception:
        pass

    try:
        events = crud.get_upcoming_calendar_events(db, days=2, limit=8)
        if events:
            lines.append("Termine nächste 48 h: " + "; ".join(
                f"{e.title} ({e.start[:16].replace('T', ' ')})"
                + ("" if getattr(e, "location", None) else " [ohne Ort]")
                for e in events))
    except Exception:
        pass

    try:
        goals = (db.query(models.Goal)
                 .filter(models.Goal.status == "open")
                 .order_by(models.Goal.target_date.is_(None), models.Goal.target_date)
                 .limit(6).all())
        if goals:
            lines.append("Offene Ziele: " + "; ".join(
                f"#{g.id} {g.title}" + (f" (bis {g.target_date})" if g.target_date else "")
                for g in goals))
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
        veh = db.query(models.Vehicle).order_by(models.Vehicle.id).first()
        if veh:
            unkl = (db.query(models.VehicleTrip)
                    .filter_by(vehicle_id=veh.id, purpose="unbekannt").count())
            if unkl:
                lines.append(f"Fahrtenbuch: {unkl} Fahrt(en) noch nicht als "
                             f"geschäftlich/privat eingeordnet")
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

    try:
        from . import smarthome
        notes = smarthome.house_anomalies(settings)
        if notes:
            lines.append("Haus: " + " | ".join(notes[:4]))
    except Exception:
        pass

    try:
        recent = (db.query(models.ProactiveProposal)
                  .filter(models.ProactiveProposal.created_at >= datetime.utcnow() - timedelta(days=3))
                  .order_by(models.ProactiveProposal.id.desc()).limit(8).all())
        if recent:
            lines.append("Zuletzt schon vorgeschlagen (nicht wiederholen): "
                         + "; ".join(f"{p.title} [{p.status}]" for p in recent))
    except Exception:
        pass

    return "\n".join(lines)


def _avg(vals) -> float | None:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _health_lines(db) -> list[str]:
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
                note += f" – diese Woche deutlich weniger ({round(wk)} statt {round(prev)})"
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


def _feedback_hint(db) -> str:
    rows = (db.query(models.ProactiveFeedback)
            .order_by(models.ProactiveFeedback.id.desc()).limit(20).all())
    if not rows:
        return ""
    good = [r.text for r in rows if r.useful][:5]
    bad = [r.text for r in rows if not r.useful][:5]
    parts = []
    if bad:
        parts.append("Diese früheren Meldungen fand Tim UNNÖTIG - vermeide Ähnliches:\n- "
                     + "\n- ".join(bad))
    if good:
        parts.append("Diese fand er NÜTZLICH - mehr in die Richtung:\n- " + "\n- ".join(good))
    return ("\n\n".join(parts) + "\n\n") if parts else ""


def _hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode("utf-8")).hexdigest()[:16]


def _extract_json(raw: str) -> dict:
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        s = s[4:] if s[:4].lower() == "json" else s
    i, j = s.find("{"), s.rfind("}")
    if i == -1 or j == -1:
        return {}
    try:
        return json.loads(s[i:j + 1])
    except json.JSONDecodeError:
        return {}


def _sanitize(proposal: dict) -> dict | None:
    """Ein rohes LLM-Proposal in eine sichere, speicherbare Form bringen.
    Optionen mit unbekannter Aktion werden zu einer aktionslosen Info-Option
    degradiert; ist danach nichts Sinnvolles übrig, gilt der Vorschlag als
    reine Info."""
    title = (proposal.get("title") or "").strip()
    if not title:
        return None
    kind = proposal.get("kind") if proposal.get("kind") in ("info", "bestaetigen", "wahl") else "info"
    urgency = proposal.get("urgency") if proposal.get("urgency") in ("hoch", "mittel", "niedrig") else "mittel"
    body = (proposal.get("body") or "").strip() or None
    dedup = (proposal.get("dedup") or _hash(title))[:120]

    raw_opts = proposal.get("options") or []
    options = []
    for idx, o in enumerate(raw_opts[:5]):
        label = (o.get("label") or "").strip()
        if not label:
            continue
        action = o.get("action") if isinstance(o.get("action"), dict) else None
        if not proactive_actions.is_allowed(action):
            action = {"type": "open", "params": {}}
        options.append({"key": chr(ord("a") + idx), "label": label, "action": action})

    if kind != "info" and not options:
        kind = "info"
    if kind != "info" and all(o["action"]["type"] not in ("dismiss", "remind_later") for o in options):
        options.append({"key": chr(ord("a") + len(options)), "label": "Später erinnern",
                        "action": {"type": "remind_later", "params": {"days": 2}}})

    return {"kind": kind, "urgency": urgency, "title": title[:200],
            "body": body, "dedup_key": dedup, "options": options}


def think(db, settings, space_id: int) -> list[dict]:
    """Fragt die lokale KI und gibt eine Liste sanitisierter Proposal-Dicts
    zurück (noch nicht gespeichert)."""
    model = _chat_model(settings)
    if not (settings.ollama_url and model):
        return []
    snapshot = build_snapshot(db, settings, space_id)
    try:
        reply = ollama_client.chat(
            settings.ollama_url, model,
            [{"role": "system", "content": _feedback_hint(db) + _SYSTEM},
             {"role": "user", "content": "Snapshot:\n" + snapshot}],
            timeout=180, format="json", options={"num_predict": 1200},
        )
    except Exception:
        return []
    data = _extract_json(reply)
    out = []
    for p in (data.get("proposals") or [])[:3]:
        s = _sanitize(p) if isinstance(p, dict) else None
        if s:
            out.append(s)
    return out


def _recent_dedup_keys(db, days: int = 7) -> set[str]:
    since = datetime.utcnow() - timedelta(days=days)
    rows = (db.query(models.ProactiveProposal.dedup_key)
            .filter(models.ProactiveProposal.created_at >= since,
                    models.ProactiveProposal.dedup_key.isnot(None)).all())
    return {r[0] for r in rows}


def run(db, settings) -> list[models.ProactiveProposal]:
    """Scheduler-Einstieg: denkt nach, entdoppelt, speichert - gibt die NEUEN
    Vorschläge zurück (der Aufrufer verschickt sie per Telegram)."""
    snoozed = getattr(settings, "proactive_assistant_snoozed_until", None)
    if not (settings.proactive_assistant_enabled and settings.notifications_enabled):
        return []
    if snoozed and datetime.utcnow() < snoozed:
        return []

    spaces = crud.get_spaces(db)
    space_id = spaces[0].id if spaces else 1
    seen = _recent_dedup_keys(db)
    created: list[models.ProactiveProposal] = []
    for s in think(db, settings, space_id):
        if s["dedup_key"] in seen:
            continue
        seen.add(s["dedup_key"])
        row = models.ProactiveProposal(
            kind=s["kind"], urgency=s["urgency"], title=s["title"], body=s["body"],
            options_json=json.dumps(s["options"], ensure_ascii=False),
            dedup_key=s["dedup_key"], status="offen",
            expires_at=datetime.utcnow() + timedelta(days=7),
        )
        db.add(row)
        created.append(row)
    if created:
        settings.proactive_assistant_last_sent_at = datetime.utcnow()
        settings.proactive_assistant_last_text = created[0].title[:1000]
        db.commit()
    return created


def render(proposal: models.ProactiveProposal) -> str:
    """Menschlicher Text eines Vorschlags (Telegram-Body ohne Buttons /
    Web-Fallback)."""
    head = {"hoch": "❗", "mittel": "🤖", "niedrig": "💡"}.get(proposal.urgency, "🤖")
    parts = [f"{head} {proposal.title}"]
    if proposal.body:
        parts.append(proposal.body)
    opts = json.loads(proposal.options_json or "[]")
    for i, o in enumerate(opts, 1):
        parts.append(f"{i}. {o['label']}")
    return "\n".join(parts)


def answer(db, settings, proposal_id: int, key: str) -> str:
    """Tim hat eine Option gewählt (per Button-Callback oder Zahl). Aktion
    ausführen, Vorschlag abschließen, Ergebnistext zurückgeben."""
    p = db.query(models.ProactiveProposal).filter_by(id=proposal_id).first()
    if not p:
        return "Diesen Vorschlag gibt es nicht mehr."
    if p.status != "offen":
        return f"Schon erledigt ({p.status})."
    opts = json.loads(p.options_json or "[]")
    chosen = next((o for o in opts if o["key"] == key), None)
    if chosen is None and key.isdigit() and 1 <= int(key) <= len(opts):
        chosen = opts[int(key) - 1]
    if chosen is None:
        return "Diese Option kenne ich nicht."
    try:
        result = proactive_actions.execute(db, settings, chosen["action"])
    except Exception as exc:  # noqa: BLE001
        result = f"Konnte die Aktion nicht ausführen: {exc}"
    p.status = "beantwortet"
    p.chosen_key = chosen["key"]
    p.result_text = result
    p.answered_at = datetime.utcnow()
    db.commit()
    return result


# --- Rückwärtskompatibilität für den Testknopf (notify_settings.py) ---
def preview(db, settings) -> str:
    spaces = crud.get_spaces(db)
    space_id = spaces[0].id if spaces else 1
    for s in think(db, settings, space_id):
        opts = "\n".join(f"{i}. {o['label']}" for i, o in enumerate(s["options"], 1))
        return f"🤖 {s['title']}\n{s['body'] or ''}\n{opts}".strip()
    return ("Du hast diese Woche im Schnitt deutlich weniger Schritte gemacht als sonst "
            "und morgen steht ein Termin ohne Ort im Kalender.\n"
            "1. Beides als To-do notieren\n2. Nur den Termin\n3. Später erinnern")
