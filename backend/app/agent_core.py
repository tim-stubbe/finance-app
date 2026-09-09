"""Kies Agent Core v1.

A small, explicit tool-calling orchestrator for the personal-assistant/Jarvis
use case. The model never receives the full Kies database. It starts with a
minimal system prompt and asks for narrowly scoped tools. Only each tool result
is returned to the model (privacy boundary / least-context principle).

The existing Jarvis fast paths (home control, simple todos, balances) remain
useful and cheap. This module handles the harder questions: combining private
facts, current web research, calendar/tasks and safe organisational actions.

Protocol expected from the local model:
  {"type":"tool","name":"get_account_balances","arguments":{}}
  {"type":"answer","reply":"..."}

Writes exposed in v1 are intentionally limited to low-risk organisational
writes (todo/calendar). Financial mutations, email sending and arbitrary smart
home calls are NOT exposed here. Smart home keeps its existing allowlist and
confirmation pipeline in smarthome.py / jarvis.py.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from . import bank_sync, crud, ollama_client, smarthome, websearch

MAX_TOOL_STEPS = 5
MAX_HISTORY_MESSAGES = 10
MAX_HISTORY_CHARS = 4000


@dataclass(frozen=True)
class ToolPolicy:
    name: str
    risk: str  # read | external_read | write_safe | propose_only
    description: str


TOOL_POLICIES: dict[str, ToolPolicy] = {
    "get_account_balances": ToolPolicy(
        "get_account_balances", "read",
        "Aktuelle Kontostände und Netto-Summe des aktiven Bereichs.",
    ),
    "get_recent_transactions": ToolPolicy(
        "get_recent_transactions", "read",
        "Letzte Buchungen; optional begrenzte Anzahl.",
    ),
    "get_monthly_spending": ToolPolicy(
        "get_monthly_spending", "read",
        "Ausgaben eines Monats inklusive Kategorien-Summen.",
    ),
    "get_calendar": ToolPolicy(
        "get_calendar", "read",
        "Anstehende Kalendereinträge für die nächsten N Tage.",
    ),
    "get_todos": ToolPolicy(
        "get_todos", "read",
        "Offene oder alle To-dos.",
    ),
    "create_todo": ToolPolicy(
        "create_todo", "write_safe",
        "Ein organisatorisches To-do anlegen.",
    ),
    "create_calendar_event": ToolPolicy(
        "create_calendar_event", "write_safe",
        "Einen Kalendertermin anlegen.",
    ),
    "search_web": ToolPolicy(
        "search_web", "external_read",
        "Aktuelle Internet-Recherche über den konfigurierten Suchanbieter.",
    ),
    "propose_finance_action": ToolPolicy(
        "propose_finance_action", "propose_only",
        "Finanzielle Änderung nur als Vorschlag formulieren; niemals ausführen.",
    ),
}

_RESEARCH_RE = re.compile(
    r"\b(steuer|steuerlich|finanzamt|werbungskosten|abschreib|absetzen|recht|rechtlich|gesetz|"
    r"kündigungsfrist|haftung|arbeitsrecht|mietrecht|verkehrsrecht|aktuell|heute|neueste|"
    r"nachrichten|zinssatz|freibetrag|grenze|regelung)\b",
    re.IGNORECASE,
)
_LEGAL_TAX_RE = re.compile(
    r"\b(steuer|steuerlich|finanzamt|werbungskosten|abschreib|absetzen|recht|rechtlich|gesetz|"
    r"kündigungsfrist|haftung|arbeitsrecht|mietrecht|verkehrsrecht)\b",
    re.IGNORECASE,
)


def _tool_catalog() -> str:
    return "\n".join(
        f"- {p.name} [{p.risk}]: {p.description}"
        for p in TOOL_POLICIES.values()
    )


def _system_prompt(settings) -> str:
    country = (getattr(settings, "residence_country", None) or "DE").upper()
    today = date.today().isoformat()
    return f"""Du bist Kies, der persönliche Assistent des Nutzers. Du arbeitest lokal über Ollama und bekommst private Daten NICHT pauschal, sondern nur über Tools.

HEUTE: {today}
WOHNSITZ/RECHTSRAUM: {country}

Ziele:
- Fragen direkt und präzise beantworten.
- Für private Fakten nur die nötigen Kies-Tools aufrufen. Keine Kontostände, Termine oder Ausgaben erfinden.
- Für aktuelle Steuer-/Rechtsfragen und andere zeitabhängige Fakten zuerst search_web nutzen. Nenne danach die wichtigsten Quellen im Text knapp; die API liefert Quellen zusätzlich strukturiert.
- Steuer/Recht: fundierte Orientierung, Rechtsraum und Stand beachten. Keine verbindliche Rechts-/Steuerberatung behaupten.
- Organisatorische Low-Risk-Aktionen (To-do/Termin) darfst du direkt über die entsprechenden Tools ausführen, wenn die Nutzerabsicht eindeutig ist.
- Finanzielle Änderungen werden NIE ausgeführt. Nutze dafür höchstens propose_finance_action.
- E-Mails senden und Smart-Home-Aktionen gehören NICHT zu deinen Tools hier. Smart Home läuft separat durch die bestehende Sicherheits-/Bestätigungspipeline.
- Hole so wenig private Daten wie nötig. Wenn ein Tool-Ergebnis ausreicht, fordere nicht vorsorglich weitere Daten an.

VERFÜGBARE TOOLS:
{_tool_catalog()}

Antworte bei jedem Planungsschritt ausschließlich als JSON, ohne Markdown:
1) Tool-Aufruf: {{"type":"tool","name":"<tool>","arguments":{{...}}}}
2) Finale Antwort: {{"type":"answer","reply":"<Antwort auf Deutsch>"}}

Tool-Argumente:
- get_account_balances: {{}}
- get_recent_transactions: {{"limit": 10}}
- get_monthly_spending: {{"year": 2026, "month": 9}}
- get_calendar: {{"days": 7}}
- get_todos: {{"include_done": false}}
- create_todo: {{"title":"...","due_date":"YYYY-MM-DD oder null"}}
- create_calendar_event: {{"title":"...","start":"ISO-8601","end":"ISO-8601 oder null","location":"... oder null","all_day":false}}
- search_web: {{"query":"gezielte Suchanfrage"}}
- propose_finance_action: {{"summary":"..."}}
"""


def _clean_history(history: list[dict] | None) -> list[dict]:
    if not history:
        return []
    cleaned: list[dict] = []
    for item in history[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(item, dict) or item.get("role") not in ("user", "assistant"):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        cleaned.append({"role": item["role"], "content": content[:MAX_HISTORY_CHARS]})
    return cleaned


def _parse_plan(raw: str) -> dict:
    try:
        obj = smarthome.parse_json_lenient(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # A useful fallback for models that ignored the JSON-only instruction:
    # treat their prose as the final answer instead of breaking the chat.
    text = re.sub(r"```(?:json)?", "", raw or "").replace("```", "").strip()
    return {"type": "answer", "reply": text or "Ich konnte die Anfrage nicht sauber einordnen."}


def _websearch_configured(settings) -> bool:
    if getattr(settings, "websearch_provider", "brave") == "searxng":
        return bool(getattr(settings, "searxng_url", None))
    return bool(getattr(settings, "brave_search_api_key_encrypted", None))


def _search_web(settings, query: str) -> list[dict]:
    if getattr(settings, "websearch_provider", "brave") == "searxng":
        return websearch.search_searxng(settings.searxng_url, query)
    key = bank_sync.decrypt_secret(settings.secret_key, settings.brave_search_api_key_encrypted)
    return websearch.search_brave(key, query)


def _serialize_date(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _execute_tool(db: Session, settings, space_id: int, name: str, args: dict) -> tuple[dict, list[dict], list[dict]]:
    """Return (tool_result, sources, actions)."""
    if name not in TOOL_POLICIES:
        return {"ok": False, "error": f"Unbekanntes Tool: {name}"}, [], []

    if name == "get_account_balances":
        rows = []
        total = 0.0
        for account in crud.get_accounts(db, space_id):
            balance = float(crud.account_balance(db, account))
            total += balance
            rows.append({
                "id": account.id,
                "name": account.name,
                "type": getattr(account.type, "value", str(account.type)),
                "balance_eur": round(balance, 2),
                "is_business": bool(getattr(account, "is_business", False)),
            })
        return {"ok": True, "accounts": rows, "accounts_total_eur": round(total, 2)}, [], []

    if name == "get_recent_transactions":
        try:
            limit = max(1, min(int(args.get("limit", 10)), 50))
        except (TypeError, ValueError):
            limit = 10
        txs = list(crud.get_transactions(db, space_id))[:limit]
        data = []
        for tx in txs:
            account = getattr(tx, "account", None)
            category = getattr(tx, "category", None)
            data.append({
                "id": tx.id,
                "date": _serialize_date(tx.date),
                "amount_eur": round(float(tx.amount), 2),
                "description": tx.description,
                "account": getattr(account, "name", None),
                "category": getattr(category, "name", None),
                "is_transfer": bool(getattr(tx, "is_transfer", False)),
            })
        return {"ok": True, "transactions": data}, [], []

    if name == "get_monthly_spending":
        today = date.today()
        try:
            year = int(args.get("year", today.year))
            month = int(args.get("month", today.month))
            if not 1 <= month <= 12:
                raise ValueError
        except (TypeError, ValueError):
            return {"ok": False, "error": "year/month ungültig"}, [], []
        by_category: dict[str, float] = defaultdict(float)
        total = 0.0
        count = 0
        for tx in crud.get_transactions(db, space_id):
            tx_date = tx.date
            if not tx_date or tx_date.year != year or tx_date.month != month:
                continue
            if getattr(tx, "is_transfer", False) or float(tx.amount) >= 0:
                continue
            amount = abs(float(tx.amount))
            total += amount
            count += 1
            category = getattr(getattr(tx, "category", None), "name", None) or "Ohne Kategorie"
            by_category[category] += amount
        cats = sorted(
            ({"category": k, "amount_eur": round(v, 2)} for k, v in by_category.items()),
            key=lambda x: x["amount_eur"], reverse=True,
        )
        return {
            "ok": True, "year": year, "month": month,
            "total_spending_eur": round(total, 2), "transaction_count": count,
            "categories": cats[:20],
        }, [], []

    if name == "get_calendar":
        try:
            days = max(1, min(int(args.get("days", 7)), 60))
        except (TypeError, ValueError):
            days = 7
        events = crud.get_upcoming_calendar_events(db, days=days, limit=30)
        return {"ok": True, "days": days, "events": [{
            "id": e.id, "title": e.title, "start": _serialize_date(e.start),
            "end": _serialize_date(getattr(e, "end", None)),
            "location": getattr(e, "location", None), "all_day": bool(getattr(e, "all_day", False)),
        } for e in events]}, [], []

    if name == "get_todos":
        include_done = bool(args.get("include_done", False))
        todos = crud.get_todos(db, include_done)
        return {"ok": True, "todos": [{
            "id": t.id, "title": t.title, "done": bool(t.done),
            "due_date": _serialize_date(getattr(t, "due_date", None)),
        } for t in todos[:50]]}, [], []

    if name == "create_todo":
        title = str(args.get("title") or "").strip()
        if not title:
            return {"ok": False, "error": "title fehlt"}, [], []
        due = None
        raw_due = args.get("due_date")
        if raw_due:
            try:
                due = date.fromisoformat(str(raw_due)[:10])
            except ValueError:
                return {"ok": False, "error": "due_date muss YYYY-MM-DD sein"}, [], []
        todo = crud.create_todo(db, title, due)
        action = {"type": "todo_created", "id": todo.id, "title": todo.title}
        return {"ok": True, "todo": action | {"due_date": _serialize_date(due)}}, [], [action]

    if name == "create_calendar_event":
        title = str(args.get("title") or "").strip()
        raw_start = args.get("start")
        if not title or not raw_start:
            return {"ok": False, "error": "title und start sind erforderlich"}, [], []
        try:
            start = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(args["end"]).replace("Z", "+00:00")) if args.get("end") else None
        except ValueError:
            return {"ok": False, "error": "start/end müssen ISO-8601 sein"}, [], []
        calendar_url = None
        configured = getattr(settings, "radicale_calendar_url", None)
        if configured:
            calendar_url = str(configured).split(",")[0].strip() or None
        event = crud.create_calendar_event(
            db, title, start, end,
            str(args.get("location") or "").strip() or None,
            bool(args.get("all_day", False)), calendar_url,
        )
        action = {"type": "calendar_event_created", "id": event.id, "title": event.title}
        return {"ok": True, "event": action | {"start": _serialize_date(start), "end": _serialize_date(end)}}, [], [action]

    if name == "search_web":
        query = str(args.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "query fehlt"}, [], []
        if not _websearch_configured(settings):
            return {"ok": False, "error": "Keine Web-Suche eingerichtet (Brave oder SearXNG)."}, [], []
        try:
            results = _search_web(settings, query)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Web-Suche fehlgeschlagen: {exc}"}, [], []
        sources = [
            {"title": r.get("title"), "url": r.get("url"), "snippet": r.get("snippet")}
            for r in results if r.get("url")
        ]
        return {"ok": True, "query": query, "results": sources}, sources, []

    if name == "propose_finance_action":
        summary = str(args.get("summary") or "").strip()
        if not summary:
            return {"ok": False, "error": "summary fehlt"}, [], []
        action = {"type": "finance_proposal", "summary": summary, "requires_confirmation": True, "executed": False}
        return {"ok": True, "proposal": action}, [], [action]

    return {"ok": False, "error": "Tool nicht implementiert"}, [], []


def _forced_research_query(text: str, settings) -> str | None:
    if not _RESEARCH_RE.search(text):
        return None
    country = (getattr(settings, "residence_country", None) or "DE").upper()
    qualifier = "aktuelle Rechtslage" if _LEGAL_TAX_RE.search(text) else "aktuell"
    return f"{text} {country} {qualifier} {date.today().year}"


def handle(
    db: Session,
    settings,
    text: str,
    space_id: int,
    *,
    history: list[dict] | None = None,
) -> dict:
    """Run one agent turn and return the common Jarvis-style response shape."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "domain": "agent", "reply": "Bitte sag oder schreib mir, wobei ich helfen soll.", "actions": []}
    if not getattr(settings, "ollama_url", None) or not getattr(settings, "ollama_model", None):
        return {"ok": False, "domain": "agent", "reply": "Kein lokales Ollama-Modell eingerichtet.", "actions": []}

    messages: list[dict] = [{"role": "system", "content": _system_prompt(settings)}]
    messages.extend(_clean_history(history))
    messages.append({"role": "user", "content": text})

    trace: list[dict] = []
    sources: list[dict] = []
    actions: list[dict] = []
    used_tools: set[str] = set()
    seen_calls: set[tuple[str, str]] = set()

    # Current tax/legal/current-information questions are researched before the
    # first model answer. This prevents a small local model from confidently
    # answering from stale training data.
    forced_query = _forced_research_query(text, settings)
    if forced_query:
        result, new_sources, new_actions = _execute_tool(db, settings, space_id, "search_web", {"query": forced_query})
        trace.append({"tool": "search_web", "risk": "external_read", "arguments": {"query": forced_query}, "ok": result.get("ok", False)})
        sources.extend(new_sources)
        actions.extend(new_actions)
        used_tools.add("search_web")
        messages.append({"role": "user", "content": "TOOL_RESULT search_web:\n" + json.dumps(result, ensure_ascii=False, default=str)})

    for _ in range(MAX_TOOL_STEPS):
        try:
            raw = ollama_client.chat(settings.ollama_url, settings.ollama_model, messages, timeout=180)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False, "domain": "agent", "reply": f"Das lokale KI-Modell ist gerade nicht erreichbar: {exc}",
                "actions": actions, "sources": sources, "tool_trace": trace,
            }

        plan = _parse_plan(raw)
        if plan.get("type") != "tool":
            reply = str(plan.get("reply") or raw or "Ok.").strip()
            return {
                "ok": True, "domain": "agent", "reply": reply,
                "actions": actions, "sources": sources, "tool_trace": trace,
                "privacy": {"full_database_shared": False, "tools_used": sorted(used_tools)},
            }

        name = str(plan.get("name") or "").strip()
        args = plan.get("arguments") if isinstance(plan.get("arguments"), dict) else {}
        policy = TOOL_POLICIES.get(name)

        # Loop detection: a model that repeats the exact same tool call instead
        # of progressing would otherwise burn through MAX_TOOL_STEPS without
        # new information. Stop early and force a final answer instead.
        call_signature = (name, json.dumps(args, sort_keys=True, default=str))
        if call_signature in seen_calls:
            messages.append({"role": "user", "content": (
                f"TOOL_RESULT {name}: Dieser Tool-Aufruf mit denselben Argumenten wurde bereits "
                "ausgeführt. Antworte jetzt final als JSON vom Typ answer mit den bereits vorliegenden Ergebnissen."
            )})
            trace.append({"tool": name, "risk": policy.risk if policy else "unknown", "arguments": args, "ok": False, "note": "duplicate_call_skipped"})
            continue
        seen_calls.add(call_signature)

        try:
            result, new_sources, new_actions = _execute_tool(db, settings, space_id, name, args)
        except Exception as exc:  # noqa: BLE001
            # A single failing tool (DB error, unexpected data shape, ...) must
            # not crash the whole agent turn - surface it to the model like any
            # other tool error so it can explain or try something else.
            result, new_sources, new_actions = {"ok": False, "error": f"Tool-Fehler: {exc}"}, [], []
        trace.append({
            "tool": name,
            "risk": policy.risk if policy else "unknown",
            "arguments": args,
            "ok": bool(result.get("ok")),
        })
        sources.extend(s for s in new_sources if s.get("url") not in {x.get("url") for x in sources})
        actions.extend(new_actions)
        used_tools.add(name)
        messages.append({"role": "assistant", "content": json.dumps(plan, ensure_ascii=False)})
        messages.append({"role": "user", "content": f"TOOL_RESULT {name}:\n" + json.dumps(result, ensure_ascii=False, default=str)})

    # Hard stop: never permit an accidental endless tool loop.
    messages.append({"role": "user", "content": "Keine weiteren Tools. Antworte jetzt final als JSON vom Typ answer mit den bereits vorliegenden Ergebnissen."})
    try:
        raw = ollama_client.chat(settings.ollama_url, settings.ollama_model, messages, timeout=120)
        plan = _parse_plan(raw)
        reply = str(plan.get("reply") or raw or "Ich habe die nötigen Daten gesammelt, konnte die Antwort aber nicht sauber formatieren.").strip()
    except Exception as exc:  # noqa: BLE001
        reply = f"Ich habe die nötigen Daten gesammelt, aber die finale Antwort ist fehlgeschlagen: {exc}"
    return {
        "ok": True, "domain": "agent", "reply": reply,
        "actions": actions, "sources": sources, "tool_trace": trace,
        "privacy": {"full_database_shared": False, "tools_used": sorted(used_tools)},
    }
