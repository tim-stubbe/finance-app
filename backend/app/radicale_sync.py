"""To-Dos UND Kalender-Termine zweiseitig mit einem Radicale/CalDAV-Server
synchronisieren.

Bewusst keine CalDAV-Bibliothek (z.B. `caldav`/`icalendar`) - die hier
gebrauchten VTODO-/VEVENT-Teilmengen (UID/SUMMARY/STATUS/DUE/DTSTART/DTEND/
LOCATION/LAST-MODIFIED) sind klein genug, um sie direkt per HTTP zu lesen und
zu schreiben, passend zum Rest der App (Immich/PayPal/eBay laufen ebenfalls
ohne SDK direkt gegen die HTTP-APIs). Keine RRULE-Unterstützung - wiederkehrende
Termine werden nur als einzelne Instanz behandelt, nicht als Serie.

CalDAV-Grundlagen, die hier genutzt werden:
- PROPFIND (Depth: 1) auf die Liste -> alle Ressourcen + ETag.
- GET je Ressource -> iCalendar-Text (VCALENDAR mit einem VTODO/VEVENT).
- PUT (neu oder geändert) / DELETE einer Ressource.
"""

import re
import uuid
from datetime import datetime, date, timezone
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from sqlalchemy.orm import Session

from . import models

TIMEOUT = 20
_NS = {"d": "DAV:"}


def _auth(username: str, password: str):
    return (username, password) if username else None


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def list_resources(url: str, username: str, password: str) -> list[dict]:
    """PROPFIND über die Todo-Liste - liefert je Ressource href und ETag,
    ohne den Inhalt zu laden. So lässt sich vor dem Abholen erkennen, welche
    Ressourcen sich seit dem letzten Sync überhaupt geändert haben."""
    body = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop><d:getetag/><d:resourcetype/></d:prop>
</d:propfind>"""
    resp = requests.request(
        "PROPFIND", url.rstrip("/") + "/",
        data=body, auth=_auth(username, password), timeout=TIMEOUT,
        headers={"Content-Type": "application/xml; charset=utf-8", "Depth": "1"},
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = []
    for resp_el in root.findall("d:response", _NS):
        href = resp_el.findtext("d:href", default="", namespaces=_NS)
        etag_el = resp_el.find(".//d:getetag", _NS)
        is_collection = resp_el.find(".//d:resourcetype/d:collection", _NS) is not None
        if is_collection or not href.lower().endswith((".ics",)):
            continue
        etag = (etag_el.text or "").strip('"') if etag_el is not None and etag_el.text else None
        items.append({"href": href, "etag": etag})
    return items


def fetch_ics(base_url: str, href: str, username: str, password: str) -> str:
    """Holt den iCalendar-Text einer einzelnen Ressource. `href` ist relativ
    (aus PROPFIND) - gegen die Basis-URL des Servers aufgelöst, nicht gegen
    die der Todo-Liste, da Radicale absolute Pfade ab der Domain liefert."""
    resp = requests.get(urljoin(base_url, href), auth=_auth(username, password), timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text


def put_ics(url: str, username: str, password: str, ics: str, etag: str | None = None) -> str | None:
    """Legt eine Ressource an oder überschreibt sie. Ohne `etag` (neu
    angelegtes Todo) wird `If-None-Match: *` gesetzt, damit kein bereits
    bestehender Eintrag versehentlich überschrieben wird. Gibt den neuen ETag
    zurück, falls der Server ihn in der Antwort mitliefert."""
    headers = {"Content-Type": "text/calendar; charset=utf-8"}
    if etag:
        headers["If-Match"] = f'"{etag}"'
    else:
        headers["If-None-Match"] = "*"
    resp = requests.put(url, data=ics.encode("utf-8"), auth=_auth(username, password),
                         headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()
    new_etag = resp.headers.get("ETag")
    return new_etag.strip('"') if new_etag else None


def delete_ics(url: str, username: str, password: str) -> None:
    resp = requests.delete(url, auth=_auth(username, password), timeout=TIMEOUT)
    if resp.status_code not in (200, 204, 404):
        resp.raise_for_status()


def check_connection(url: str, username: str, password: str) -> int:
    """Verbindungstest - gibt die Anzahl gefundener Todo-Ressourcen zurück,
    wirft bei Fehlern (falsche Adresse, falsche Zugangsdaten)."""
    return len(list_resources(url, username, password))


# ---------- Minimaler VTODO-Parser/-Schreiber ----------

def _unfold(text: str) -> list[str]:
    """CalDAV faltet lange Zeilen mit einem Leerzeichen/Tab am Zeilenanfang
    der Fortsetzung - vor dem Parsen wieder zusammenfügen."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def parse_vtodo(ics: str) -> dict | None:
    """Liest die für den Sync relevanten Felder aus einem VTODO. Parameter
    nach einem `;` (z.B. `DUE;VALUE=DATE:...`) werden ignoriert - hier zählt
    nur der Wert nach dem letzten `:`."""
    fields: dict[str, str] = {}
    in_todo = False
    for line in _unfold(ics):
        if line == "BEGIN:VTODO":
            in_todo = True
            continue
        if line == "END:VTODO":
            break
        if not in_todo or ":" not in line:
            continue
        key, _, value = line.partition(":")
        name = key.split(";")[0].upper()
        fields[name] = value
    if "UID" not in fields:
        return None
    due = None
    if fields.get("DUE"):
        try:
            due = datetime.strptime(fields["DUE"][:8], "%Y%m%d").date()
        except ValueError:
            due = None
    return {
        "uid": fields["UID"],
        "title": fields.get("SUMMARY", "").strip() or "Ohne Titel",
        "done": fields.get("STATUS", "").upper() == "COMPLETED",
        "due_date": due,
    }


def build_vtodo(uid: str, title: str, done: bool, due_date: date | None) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//finance-app//todos//DE",
        "BEGIN:VTODO",
        f"UID:{uid}",
        f"DTSTAMP:{_now_stamp()}",
        f"LAST-MODIFIED:{_now_stamp()}",
        f"SUMMARY:{_escape_text(title)}",
        f"STATUS:{'COMPLETED' if done else 'NEEDS-ACTION'}",
    ]
    if done:
        lines.append(f"COMPLETED:{_now_stamp()}")
    if due_date:
        lines.append(f"DUE;VALUE=DATE:{due_date.strftime('%Y%m%d')}")
    lines += ["END:VTODO", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


def build_vevent(
    uid: str, title: str, start: datetime, end: datetime | None, location: str | None, all_day: bool
) -> str:
    if all_day:
        dtstart = f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}"
        dtend = f"DTEND;VALUE=DATE:{(end or start).strftime('%Y%m%d')}"
    else:
        dtstart = f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}"
        dtend = f"DTEND:{(end or start).strftime('%Y%m%dT%H%M%S')}" if end else None
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//finance-app//calendar//DE",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_now_stamp()}",
        f"LAST-MODIFIED:{_now_stamp()}",
        dtstart,
    ]
    if dtend:
        lines.append(dtend)
    lines.append(f"SUMMARY:{_escape_text(title)}")
    if location:
        lines.append(f"LOCATION:{_escape_text(location)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


def _escape_text(value: str) -> str:
    return re.sub(r"([,;\\])", r"\\\1", value).replace("\n", "\\n")


def new_uid() -> str:
    return f"{uuid.uuid4()}@finance-app"


def _parse_ical_datetime(value: str) -> tuple[datetime, bool]:
    """Liest DTSTART/DTEND: entweder ein reines Datum (ganztägiger Termin,
    z.B. "20260820") oder Datum+Zeit ("20260820T140000" bzw. mit "Z" für UTC).
    Gibt (datetime, all_day) zurück."""
    value = value.strip()
    if "T" not in value:
        return datetime.strptime(value, "%Y%m%d"), True
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc), False
    return datetime.strptime(value, "%Y%m%dT%H%M%S"), False


def parse_vevent(ics: str) -> dict | None:
    """Liest die für die Anzeige relevanten Felder aus einem VEVENT. Wie bei
    parse_vtodo werden Parameter nach `;` (z.B. Zeitzonen-Angaben) ignoriert -
    für eine reine Anzeige im Digest/Hub reicht der rohe Zeitstempel."""
    fields: dict[str, str] = {}
    in_event = False
    for line in _unfold(ics):
        if line == "BEGIN:VEVENT":
            in_event = True
            continue
        if line == "END:VEVENT":
            break
        if not in_event or ":" not in line:
            continue
        key, _, value = line.partition(":")
        name = key.split(";")[0].upper()
        fields[name] = value
    if "UID" not in fields or "DTSTART" not in fields:
        return None
    try:
        start, all_day = _parse_ical_datetime(fields["DTSTART"])
    except ValueError:
        return None
    end = None
    if fields.get("DTEND"):
        try:
            end, _ = _parse_ical_datetime(fields["DTEND"])
        except ValueError:
            end = None
    return {
        "uid": fields["UID"],
        "title": fields.get("SUMMARY", "").strip() or "Ohne Titel",
        "start": start,
        "end": end,
        "location": fields.get("LOCATION", "").strip() or None,
        "all_day": all_day,
    }


def sync_calendar(db: Session, url: str, username: str, password: str) -> dict:
    """Zweiseitig, analog zu sync() für Todos (siehe dort für die Begründung
    der Push-vor-Pull-Reihenfolge). Alle Schritte sind auf DIESEN Kalender
    beschraenkt (Pfad-Praefix aus der URL) - der Nutzer bindet mehrere
    Kalender-Collections gleichzeitig ein (main.py ruft sync_calendar
    entsprechend mehrfach auf), alle landen in derselben calendar_events-
    Tabelle. Ohne diese Eingrenzung wuerde jeder Aufruf faelschlich Termine
    der JEWEILS ANDEREN Kalender pushen/loeschen. Keine RRULE-Unterstuetzung -
    wiederkehrende Termine werden nur als einzelne Instanz behandelt."""
    pushed, pulled, errors = 0, 0, []
    calendar_path = urlparse(url).path

    def in_this_calendar(event: models.CalendarEvent) -> bool:
        if event.calendar_url:
            return event.calendar_url == url
        return bool(event.href) and event.href.startswith(calendar_path)

    # 1) Lokale Löschungen hochladen.
    for event in db.query(models.CalendarEvent).filter(models.CalendarEvent.pending_delete.is_(True)).all():
        if not in_this_calendar(event):
            continue
        try:
            if event.href:
                delete_ics(urljoin(url, event.href), username, password)
            db.delete(event)
            pushed += 1
        except Exception as e:
            errors.append(f"Löschen von '{event.title}': {e}")
    db.commit()

    # 2) Lokale Neuanlagen/Änderungen hochladen.
    to_push = (
        db.query(models.CalendarEvent)
        .filter(
            models.CalendarEvent.calendar_url == url,
            (models.CalendarEvent.href.is_(None)) |
            (models.CalendarEvent.last_synced_at.is_(None)) |
            (models.CalendarEvent.updated_at > models.CalendarEvent.last_synced_at),
        )
        .all()
    )
    for event in to_push:
        try:
            ics = build_vevent(event.uid, event.title, event.start, event.end, event.location, event.all_day)
            if event.href:
                new_etag = put_ics(urljoin(url, event.href), username, password, ics, event.etag)
            else:
                href = url.rstrip("/") + f"/{event.uid}.ics"
                new_etag = put_ics(href, username, password, ics)
                event.href = href
            if new_etag:
                event.etag = new_etag
            event.last_synced_at = datetime.utcnow()
            pushed += 1
        except Exception as e:
            errors.append(f"Speichern von '{event.title}': {e}")
    db.commit()

    # 3) Serverstand holen und mit lokal abgleichen.
    try:
        remote = list_resources(url, username, password)
    except Exception as e:
        errors.append(f"Kalender nicht erreichbar: {e}")
        return {"pushed": pushed, "pulled": pulled, "errors": errors}

    local_by_href = {
        e.href: e for e in db.query(models.CalendarEvent)
        .filter(models.CalendarEvent.href.isnot(None), models.CalendarEvent.href.like(f"{calendar_path}%"))
        .all()
    }
    seen_hrefs = set()
    for item in remote:
        seen_hrefs.add(item["href"])
        local = local_by_href.get(item["href"])
        if local and local.etag == item["etag"]:
            # calendar_url fehlt noch bei Einträgen aus der Zeit vor dem
            # Zwei-Wege-Sync (nur gelesen, nie geschrieben) - ohne Nachtragen
            # würde ein lokales Bearbeiten so eines alten Termins nie den
            # Weg zurück zum Server finden (siehe to_push-Filter oben).
            if not local.calendar_url:
                local.calendar_url = url
                db.commit()
            continue
        try:
            ics = fetch_ics(url, item["href"], username, password)
            parsed = parse_vevent(ics)
        except Exception as e:
            errors.append(f"Laden von {item['href']}: {e}")
            continue
        if not parsed:
            continue
        existing = db.query(models.CalendarEvent).filter(models.CalendarEvent.uid == parsed["uid"]).first()
        if existing:
            # Nur übernehmen, wenn seit dem letzten Sync keine lokale Änderung
            # aussteht - die wäre gerade eben in Schritt 2 schon hochgeladen
            # worden und hätte denselben ETag zur Folge gehabt.
            if existing.last_synced_at and existing.updated_at > existing.last_synced_at:
                continue
            existing.title = parsed["title"]
            existing.start = parsed["start"]
            existing.end = parsed["end"]
            existing.location = parsed["location"]
            existing.all_day = parsed["all_day"]
            existing.calendar_url = url
            existing.href = item["href"]
            existing.etag = item["etag"]
            existing.last_synced_at = datetime.utcnow()
        else:
            db.add(models.CalendarEvent(
                uid=parsed["uid"], title=parsed["title"], start=parsed["start"], end=parsed["end"],
                location=parsed["location"], all_day=parsed["all_day"], calendar_url=url,
                href=item["href"], etag=item["etag"], last_synced_at=datetime.utcnow(),
            ))
        pulled += 1
    db.commit()

    # 4) Am Server gelöschte Termine auch lokal entfernen (nur bei bereits
    # synchronisierten Einträgen).
    for href, local in local_by_href.items():
        if href not in seen_hrefs and local.last_synced_at:
            db.delete(local)
    db.commit()

    return {"pushed": pushed, "pulled": pulled, "errors": errors}


# ---------- Zwei-Wege-Abgleich ----------

def sync(db: Session, url: str, username: str, password: str) -> dict:
    """Gleicht die lokale `todos`-Tabelle mit der Radicale-Liste ab.

    Reihenfolge bewusst: erst lokale Löschungen/Änderungen hochladen, dann
    vom Server holen - so gewinnt bei einem Konflikt (am Handy UND hier
    geändert, ohne dass zwischendurch synchronisiert wurde) die zuletzt lokal
    gespeicherte Fassung, statt von einer veralteten Serverkopie überschrieben
    zu werden. Bei einem einzelnen Nutzer auf einer persönlichen Liste ist das
    Risiko eines echten Konflikts gering - eine ausgefeiltere Merge-Logik wäre
    hier Aufwand ohne echten Nutzen.
    """
    pushed, pulled, errors = 0, 0, []

    # 1) Lokale Löschungen hochladen.
    for todo in db.query(models.Todo).filter(models.Todo.pending_delete.is_(True)).all():
        try:
            if todo.href:
                delete_ics(urljoin(url, todo.href), username, password)
            db.delete(todo)
            pushed += 1
        except Exception as e:
            errors.append(f"Löschen von '{todo.title}': {e}")
    db.commit()

    # 2) Lokale Neuanlagen/Änderungen hochladen.
    to_push = (
        db.query(models.Todo)
        .filter(
            (models.Todo.href.is_(None)) |
            (models.Todo.last_synced_at.is_(None)) |
            (models.Todo.updated_at > models.Todo.last_synced_at)
        )
        .all()
    )
    for todo in to_push:
        try:
            ics = build_vtodo(todo.uid, todo.title, todo.done, todo.due_date)
            if todo.href:
                new_etag = put_ics(urljoin(url, todo.href), username, password, ics, todo.etag)
            else:
                href = url.rstrip("/") + f"/{todo.uid}.ics"
                new_etag = put_ics(href, username, password, ics)
                todo.href = href
            if new_etag:
                todo.etag = new_etag
            todo.last_synced_at = datetime.utcnow()
            pushed += 1
        except Exception as e:
            errors.append(f"Speichern von '{todo.title}': {e}")
    db.commit()

    # 3) Serverstand holen und mit lokal abgleichen.
    try:
        remote = list_resources(url, username, password)
    except Exception as e:
        errors.append(f"Radicale nicht erreichbar: {e}")
        return {"pushed": pushed, "pulled": pulled, "errors": errors}

    local_by_href = {t.href: t for t in db.query(models.Todo).filter(models.Todo.href.isnot(None)).all()}
    seen_hrefs = set()
    for item in remote:
        seen_hrefs.add(item["href"])
        local = local_by_href.get(item["href"])
        # Unverändert seit dem letzten Abgleich (gleicher ETag) - nichts zu tun.
        if local and local.etag == item["etag"]:
            continue
        try:
            ics = fetch_ics(url, item["href"], username, password)
            parsed = parse_vtodo(ics)
        except Exception as e:
            errors.append(f"Laden von {item['href']}: {e}")
            continue
        if not parsed:
            continue

        existing = db.query(models.Todo).filter(models.Todo.uid == parsed["uid"]).first()
        if existing:
            # Nur übernehmen, wenn seit dem letzten Sync keine lokale Änderung
            # aussteht - die wäre gerade eben in Schritt 2 schon hochgeladen
            # worden und hätte denselben ETag zur Folge gehabt.
            if existing.last_synced_at and existing.updated_at > existing.last_synced_at:
                continue
            existing.title = parsed["title"]
            existing.done = parsed["done"]
            existing.due_date = parsed["due_date"]
            existing.href = item["href"]
            existing.etag = item["etag"]
            existing.last_synced_at = datetime.utcnow()
        else:
            db.add(models.Todo(
                uid=parsed["uid"], title=parsed["title"], done=parsed["done"],
                due_date=parsed["due_date"], href=item["href"], etag=item["etag"],
                last_synced_at=datetime.utcnow(),
            ))
        pulled += 1
    db.commit()

    # 4) Am Server gelöschte Todos auch lokal entfernen (nur bei bereits
    # synchronisierten Einträgen - eine gerade erst lokal angelegte, noch
    # ungesehene Ressource wird nie gelöscht).
    for href, local in local_by_href.items():
        if href not in seen_hrefs and local.last_synced_at:
            db.delete(local)
    db.commit()

    return {"pushed": pushed, "pulled": pulled, "errors": errors}
