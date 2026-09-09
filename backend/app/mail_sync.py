"""Belege aus E-Mail-Anhängen holen.

Nutzt `imaplib` und `email` aus der Standardbibliothek - für "verbinde dich mit
einem Postfach und hol die Anhänge" braucht es keine zusätzliche Abhängigkeit.

Bewusst nur **lesender** Zugriff: Es wird nichts gelöscht, nichts verschoben
und nichts als gelesen markiert. Ein Fehler hier soll das Postfach nicht
verändern können. Dass ein Anhang schon geholt wurde, merkt sich stattdessen
die Datenbank (Message-ID + Dateiname), genau wie beim Bank-Import.
"""

import email
import imaplib
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

# Nur Formate, aus denen die bestehende Beleg-Auswertung etwas machen kann.
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"}
# Anhänge über dieser Grösse sind keine Belege, sondern etwas anderes.
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
# Überlappung beim Abholen: eine Mail, die während des letzten Laufs eintraf,
# ginge sonst verloren. Doppelte fängt die Datenbank ab.
OVERLAP = timedelta(days=1)


def _decode(value: str | None) -> str:
    """Betreff/Absender können in MIME-Wortkodierung vorliegen
    (=?UTF-8?B?...?=) - ohne Dekodierung stünde das kryptisch in der Liste."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _safe_extension(filename: str) -> str | None:
    match = re.search(r"(\.[A-Za-z0-9]{1,5})$", filename or "")
    if not match:
        return None
    ext = match.group(1).lower()
    return ext if ext in ALLOWED_EXTENSIONS else None


def connect(host: str, port: int, user: str, password: str) -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(host, port or 993)
    conn.login(user, password)
    return conn


def check_connection(host: str, port: int, user: str, password: str, folder: str) -> dict:
    """Prüft Zugangsdaten und Ordner und liefert eine sprechende Rückmeldung."""
    conn = connect(host, port, user, password)
    try:
        status, data = conn.select(folder or "INBOX", readonly=True)
        if status != "OK":
            # Ordnernamen sind serverabhängig ("Gesendet" vs "[Gmail]/..."), das
            # ist der häufigste Einrichtungsfehler - deshalb Liste mitgeben.
            _, boxes = conn.list()
            namen = [_decode(b.decode(errors="replace")).split(' "/" ')[-1].strip('"')
                     for b in (boxes or [])][:25]
            raise ValueError(
                f"Ordner „{folder}“ nicht gefunden. Verfügbar: {', '.join(namen)}"
            )
        return {"folder": folder or "INBOX", "message_count": int(data[0])}
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def fetch_attachments(host: str, port: int, user: str, password: str,
                      folder: str, since: datetime | None) -> list[dict]:
    """Holt Anhänge aus Mails ab einem Stichtag.

    Gibt Wörterbücher zurück (Message-ID, Absender, Betreff, Datum, Dateiname,
    Inhalt) - das Speichern passiert bewusst ausserhalb, damit dieses Modul
    nichts über Datenbank oder Dateisystem wissen muss.
    """
    conn = connect(host, port, user, password)
    ergebnisse: list[dict] = []
    try:
        # readonly: siehe Modulkommentar - das Postfach bleibt unangetastet,
        # insbesondere werden Mails nicht als gelesen markiert.
        status, _ = conn.select(folder or "INBOX", readonly=True)
        if status != "OK":
            raise ValueError(f"Ordner „{folder}“ konnte nicht geöffnet werden.")

        if since:
            stichtag = (since - OVERLAP).strftime("%d-%b-%Y")
            status, data = conn.search(None, "SINCE", stichtag)
        else:
            # Erster Lauf: nicht das gesamte Postfach durchgehen, sondern die
            # letzten 90 Tage - alles andere dauert bei grossen Postfächern
            # minutenlang und liefert vor allem Uraltes.
            stichtag = (datetime.utcnow() - timedelta(days=90)).strftime("%d-%b-%Y")
            status, data = conn.search(None, "SINCE", stichtag)
        if status != "OK":
            return []

        for num in (data[0].split() if data and data[0] else []):
            status, raw = conn.fetch(num, "(RFC822)")
            if status != "OK" or not raw or not raw[0]:
                continue
            msg = email.message_from_bytes(raw[0][1])

            message_id = msg.get("Message-ID") or f"ohne-id-{num.decode()}"
            absender = _decode(msg.get("From"))
            betreff = _decode(msg.get("Subject"))
            try:
                mail_datum = parsedate_to_datetime(msg.get("Date"))
                if mail_datum and mail_datum.tzinfo:
                    mail_datum = mail_datum.replace(tzinfo=None)
            except Exception:
                mail_datum = None

            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                dateiname = _decode(part.get_filename())
                if not dateiname:
                    continue
                if not _safe_extension(dateiname):
                    continue
                inhalt = part.get_payload(decode=True)
                if not inhalt or len(inhalt) > MAX_ATTACHMENT_BYTES:
                    continue
                ergebnisse.append({
                    "message_id": message_id.strip(),
                    "sender": absender,
                    "subject": betreff,
                    "mail_date": mail_datum,
                    "filename": dateiname,
                    "content_type": part.get_content_type(),
                    "content": inhalt,
                })
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return ergebnisse
