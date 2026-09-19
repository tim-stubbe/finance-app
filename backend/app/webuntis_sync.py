"""WebUntis-Stundenplan lesend nach Radicale spiegeln.

Die Quelle wird niemals verändert. Auf CalDAV werden ausschließlich stabile,
mit ``webuntis-`` beginnende Ressourcen angelegt, aktualisiert oder gelöscht.
"""

import hashlib
import json
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import requests

from . import radicale_sync

TIMEOUT = 25
CLIENT_NAME = "Kies"


class WebUntisError(RuntimeError):
    pass


def parse_share_url(url: str) -> dict:
    parsed = urlparse((url or "").strip())
    if not parsed.scheme.startswith("http") or not parsed.hostname:
        raise WebUntisError("Ungültiger WebUntis-Link")
    query = parse_qs(parsed.query)
    fragment_query = parse_qs(parsed.fragment.partition("?")[2])
    school = (query.get("school") or [""])[0]
    entity = (fragment_query.get("entityId") or [""])[0]
    if not school or not entity.isdigit():
        raise WebUntisError("Im Link fehlen Schule oder Stundenplan-ID")
    return {
        "base": f"{parsed.scheme}://{parsed.netloc}/WebUntis",
        "school": school,
        "entity_id": int(entity),
    }


def _rpc(session: requests.Session, endpoint: str, method: str, params: dict) -> dict | list:
    response = session.post(
        endpoint,
        json={"jsonrpc": "2.0", "id": CLIENT_NAME, "method": method, "params": params},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("error"):
        message = body["error"].get("message") or "WebUntis-Anfrage fehlgeschlagen"
        raise WebUntisError(message)
    return body.get("result")


def fetch_periods(share_url: str, username: str, password: str, start: date, end: date) -> list[dict]:
    """Liest den verlinkten Schülerplan. Der öffentliche Link der Schule
    verlangt derzeit trotzdem eine Anmeldung; Zugangsdaten bleiben serverseitig.
    """
    info = parse_share_url(share_url)
    if not username or not password:
        raise WebUntisError("Der öffentliche Link verlangt eine WebUntis-Anmeldung")
    session = requests.Session()
    session.headers.update({"User-Agent": "Kies/1.0"})
    endpoint = f"{info['base']}/jsonrpc.do?school={info['school']}"
    login = _rpc(session, endpoint, "authenticate", {
        "user": username, "password": password, "client": CLIENT_NAME,
    })
    if not isinstance(login, dict):
        raise WebUntisError("WebUntis-Anmeldung fehlgeschlagen")
    try:
        result = _rpc(session, endpoint, "getTimetable", {
            "options": {
                "startDate": int(start.strftime("%Y%m%d")),
                "endDate": int(end.strftime("%Y%m%d")),
                "element": {"id": info["entity_id"], "type": 5},
                "onlyBaseTimetable": False,
                "showBooking": True,
                "showInfo": True,
                "showSubstText": True,
                "showLsText": True,
                "showStudentgroup": True,
            }
        })
        return result if isinstance(result, list) else []
    finally:
        try:
            _rpc(session, endpoint, "logout", {})
        except Exception:
            pass


def _names(period: dict, key: str) -> list[str]:
    return [str(x.get("name") or x.get("longname") or "").strip()
            for x in (period.get(key) or []) if isinstance(x, dict) and (x.get("name") or x.get("longname"))]


def normalise_period(period: dict) -> dict | None:
    try:
        day = datetime.strptime(str(period["date"]), "%Y%m%d")
        start_raw, end_raw = int(period["startTime"]), int(period["endTime"])
        start = day.replace(hour=start_raw // 100, minute=start_raw % 100)
        end = day.replace(hour=end_raw // 100, minute=end_raw % 100)
        period_id = int(period["id"])
    except (KeyError, TypeError, ValueError):
        return None
    subjects = _names(period, "su")
    rooms = _names(period, "ro")
    teachers = _names(period, "te")
    cancelled = str(period.get("code") or "").lower() == "cancelled"
    subject = ", ".join(subjects) or "Unterricht"
    title = f"Entfällt · {subject}" if cancelled else subject
    notes = [x for x in (period.get("substText"), period.get("info"), period.get("lstext")) if x]
    return {
        "uid": f"webuntis-{period_id}@kies",
        "title": title,
        "start": start,
        "end": end,
        "location": ", ".join(rooms) or None,
        "description": " · ".join(["WebUntis"] + teachers + [str(x) for x in notes]),
        "cancelled": cancelled,
    }


def _escape(value: str) -> str:
    return radicale_sync._escape_text(value)


def build_event(event: dict) -> str:
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Kies//WebUntis//DE",
        "BEGIN:VEVENT", f"UID:{event['uid']}", f"DTSTAMP:{stamp}",
        f"LAST-MODIFIED:{stamp}", f"DTSTART:{event['start'].strftime('%Y%m%dT%H%M%S')}",
        f"DTEND:{event['end'].strftime('%Y%m%dT%H%M%S')}",
        f"SUMMARY:{_escape(event['title'])}", f"DESCRIPTION:{_escape(event['description'])}",
        "X-KIES-SOURCE:WEBUNTIS",
    ]
    if event.get("location"):
        lines.append(f"LOCATION:{_escape(event['location'])}")
    if event.get("cancelled"):
        lines.append("STATUS:CANCELLED")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


def _fingerprint(event: dict) -> str:
    relevant = {k: event.get(k) for k in ("title", "start", "end", "location", "description", "cancelled")}
    return hashlib.sha256(json.dumps(relevant, default=str, sort_keys=True).encode()).hexdigest()


def _summary(event: dict) -> dict:
    """Kleine, JSON-fähige Darstellung für verständliche Änderungsmeldungen."""
    return {
        "title": event.get("title") or "Unterricht",
        "start": event["start"].isoformat(timespec="minutes"),
        "end": event["end"].isoformat(timespec="minutes"),
        "location": event.get("location"),
        "cancelled": bool(event.get("cancelled")),
    }


def sync(settings, password: str, radicale_password: str, today: date | None = None) -> dict:
    today = today or date.today()
    start, end = today - timedelta(days=1), today + timedelta(days=28)
    periods = fetch_periods(settings.webuntis_url, settings.webuntis_username, password, start, end)
    events = [event for event in (normalise_period(p) for p in periods) if event]
    current = {event["uid"]: _fingerprint(event) for event in events}
    current_events = {event["uid"]: _summary(event) for event in events}
    try:
        stored = json.loads(settings.webuntis_state_json or "{}")
    except (TypeError, json.JSONDecodeError):
        stored = {}
    # Abwärtskompatibel zum alten Format {uid: fingerprint}.
    if isinstance(stored, dict) and "fingerprints" in stored:
        previous = stored.get("fingerprints") or {}
        previous_events = stored.get("events") or {}
    else:
        previous = stored if isinstance(stored, dict) else {}
        previous_events = {}
    calendar = settings.webuntis_calendar_url.rstrip("/") + "/"
    created = changed = removed = 0
    errors: list[str] = []
    details: list[dict] = []

    for event in events:
        resource = calendar + event["uid"] + ".ics"
        if previous.get(event["uid"]) == current[event["uid"]]:
            continue
        try:
            response = requests.get(resource, auth=(settings.radicale_username, radicale_password), timeout=TIMEOUT)
            etag = response.headers.get("ETag", "").strip('"') if response.status_code == 200 else None
            radicale_sync.put_ics(resource, settings.radicale_username, radicale_password, build_event(event), etag)
            if event["uid"] in previous:
                changed += 1
                details.append({"type": "geändert", "before": previous_events.get(event["uid"]),
                                "event": current_events[event["uid"]]})
            else:
                created += 1
                details.append({"type": "neu", "event": current_events[event["uid"]]})
        except Exception as exc:
            errors.append(f"{event['title']}: {type(exc).__name__}")

    for uid in set(previous) - set(current):
        if not uid.startswith("webuntis-"):
            continue
        try:
            radicale_sync.delete_ics(calendar + uid + ".ics", settings.radicale_username, radicale_password)
            removed += 1
            details.append({"type": "entfallen", "event": previous_events.get(uid), "uid": uid})
        except Exception as exc:
            errors.append(f"Entfernen {uid}: {type(exc).__name__}")

    if not errors:
        settings.webuntis_state_json = json.dumps(
            {"fingerprints": current, "events": current_events}, sort_keys=True
        )
        settings.webuntis_last_sync_at = datetime.utcnow()
    return {"created": created, "changed": changed, "removed": removed,
            "periods": len(events), "errors": errors, "details": details}
