"""Backup, Restore und Wiederherstellungs-Dateien.

Achtzehnter Schritt der Code-Modularisierung (siehe ROADMAP.md), nach
investments/tax/debts/goals/trips/wishlist/personal/business_life/
budgets_alerts/deadlines/calendar_todos/categories/immich_routes/
bank_connections/enablebanking_ebay/mail_routes/spaces_accounts.

Bewusst NICHT mit hierher gezogen: /settings/backup (GET/PUT) und
_scheduled_auto_backup bleiben in main.py - PUT braucht den globalen
`scheduler` (main.py, für reschedule_job), der erst nach den Router-
Importen definiert wird und deshalb nicht zirkelfrei re-importierbar wäre
(gleiches Problem wie bei UPLOAD_DIR, siehe mail_routes.py-Docstring).

`write_backup_to_disk` (ohne führenden Unterstrich) wird von
main._scheduled_auto_backup gebraucht, deshalb exportiert und in main.py
zurückimportiert - gleiches Muster wie goal_out/immich_credentials/
run_mail_sync."""

import io
import os
import re
import shutil
import zipfile
from datetime import date, datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, File, Form, UploadFile
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.orm import Session

from .. import schemas, auth, bank_sync, backup_crypto
from ..database import get_db, DATA_DIR

# Eigenständig berechnet statt aus main importiert (main.py importiert diesen
# Router beim Start VOR der Stelle, an der main.UPLOAD_DIR definiert wird -
# ein Rückimport von dort wäre ein Zirkelbezug, siehe mail_routes.py).
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

backup_router = APIRouter(prefix="/api")


# ---------------- Backup / Restore (bereichsübergreifend) ----------------
def _build_backup_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        db_path = os.path.join(DATA_DIR, "finance.db")
        if os.path.exists(db_path):
            zf.write(db_path, "finance.db")
        if os.path.isdir(UPLOAD_DIR):
            for root, _, files in os.walk(UPLOAD_DIR):
                for fname in files:
                    full = os.path.join(root, fname)
                    rel = os.path.join("uploads", os.path.relpath(full, UPLOAD_DIR))
                    zf.write(full, rel)
    return buf.getvalue()


def _backup_passphrase(db: Session) -> str | None:
    """Entschluesselte Backup-Passphrase, falls konfiguriert - sonst None
    (dann bleiben die Backups nackte ZIPs, wie bisher)."""
    s = auth.get_or_create_settings(db)
    if not s.backup_passphrase_encrypted:
        return None
    return bank_sync.decrypt_secret(s.secret_key, s.backup_passphrase_encrypted)


def _package_backup(db: Session) -> tuple[bytes, str]:
    """Backup-Bytes + Dateiendung. Mit Passphrase -> KIESBK-Container (.kies),
    ohne -> ZIP."""
    data = _build_backup_zip_bytes()
    passphrase = _backup_passphrase(db)
    if passphrase:
        return backup_crypto.encrypt(data, passphrase), backup_crypto.ENCRYPTED_EXT
    return data, backup_crypto.PLAIN_EXT


@backup_router.get("/backup")
def backup(db: Session = Depends(get_db)):
    data, ext = _package_backup(db)
    filename = f"finanztool_backup_{date.today().isoformat()}{ext}"
    encrypted = ext == backup_crypto.ENCRYPTED_EXT
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/octet-stream" if encrypted else "application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


BACKUP_DIR = os.path.join(DATA_DIR, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)
# .kies = verschluesselter Container (siehe backup_crypto), .zip = wie bisher.
BACKUP_FILENAME_RE = re.compile(r"^auto_backup_\d{8}_\d{6}\.(?:zip|kies)$")
# Beleg-Dateinamen im Backup: nur harmlose Zeichen, kein Trenner, kein "..".
_UPLOAD_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


def write_backup_to_disk(db: Session, retention: int) -> schemas.BackupFileOut:
    data, ext = _package_backup(db)
    filename = f"auto_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}{ext}"
    full_path = os.path.join(BACKUP_DIR, filename)
    with open(full_path, "wb") as f:
        f.write(data)

    existing = sorted(f for f in os.listdir(BACKUP_DIR) if BACKUP_FILENAME_RE.fullmatch(f))
    excess = len(existing) - retention
    for old in existing[:max(excess, 0)]:
        os.remove(os.path.join(BACKUP_DIR, old))

    stat = os.stat(full_path)
    return schemas.BackupFileOut(
        filename=filename, size_bytes=stat.st_size,
        created_at=datetime.utcfromtimestamp(stat.st_mtime),
    )



@backup_router.get("/backups", response_model=List[schemas.BackupFileOut])
def list_backups():
    items = []
    for fname in os.listdir(BACKUP_DIR):
        if not BACKUP_FILENAME_RE.fullmatch(fname):
            continue
        stat = os.stat(os.path.join(BACKUP_DIR, fname))
        items.append(schemas.BackupFileOut(
            filename=fname, size_bytes=stat.st_size,
            created_at=datetime.utcfromtimestamp(stat.st_mtime),
        ))
    items.sort(key=lambda b: b.created_at, reverse=True)
    return items


@backup_router.post("/backups/run", response_model=schemas.BackupFileOut)
def run_backup_now(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return write_backup_to_disk(db, settings.backup_retention)


def _resolve_backup_path(filename: str) -> str:
    """Backup-Dateiname -> Pfad einer TATSAECHLICH in BACKUP_DIR liegenden
    Datei. Der zurueckgegebene Pfad wird aus einem `os.listdir`-Eintrag
    zusammengesetzt, nie aus der Anfrage - damit gibt es keinen Taint-Flow
    von der URL zum Dateizugriff (Traversal ist strukturell unmoeglich, und
    CodeQL/py/path-injection sieht das auch so)."""
    wanted = os.path.basename(filename)
    for entry in os.listdir(BACKUP_DIR):
        if entry == wanted and BACKUP_FILENAME_RE.fullmatch(entry):
            return os.path.join(BACKUP_DIR, entry)
    raise HTTPException(404, "Backup nicht gefunden")


@backup_router.get("/backups/{filename}")
def download_backup(filename: str):
    full = _resolve_backup_path(filename)
    if not os.path.exists(full):
        raise HTTPException(404, "Backup nicht gefunden")
    return FileResponse(full, media_type="application/zip", filename=os.path.basename(full))


@backup_router.delete("/backups/{filename}")
def delete_backup(filename: str):
    full = _resolve_backup_path(filename)
    if os.path.exists(full):
        os.remove(full)
    return {"ok": True}


@backup_router.post("/restore")
def restore(file: UploadFile = File(...), passphrase: str = Form("")):
    content = file.file.read()

    if backup_crypto.is_encrypted(content):
        if not passphrase.strip():
            raise HTTPException(400, "Dieses Backup ist verschlüsselt – bitte die Passphrase angeben.")
        try:
            content = backup_crypto.decrypt(content, passphrase)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(400, "Ungültige Backup-Datei")
    if "finance.db" not in zf.namelist():
        raise HTTPException(400, "Backup enthält keine finance.db")

    db_path = os.path.join(DATA_DIR, "finance.db")
    if os.path.exists(db_path):
        shutil.copy2(db_path, db_path + ".bak")

    zf.extract("finance.db", DATA_DIR)
    # Bewusst NICHT zf.extract(name, DATA_DIR) - ein präpariertes Zip mit
    # z.B. "uploads/../../etc/cron.d/x" würde damit außerhalb von UPLOAD_DIR
    # landen (Zip-Slip). Uploads liegen ohnehin immer flach ohne Unterordner
    # (siehe main.upload_receipt) - deshalb hier auf den Basename reduziert
    # und wie bei _resolve_backup_path() oben zusätzlich per realpath gegen
    # UPLOAD_DIR abgesichert, bevor der Inhalt selbst geschrieben wird.
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    upload_root = os.path.realpath(UPLOAD_DIR)
    for name in zf.namelist():
        if not (name.startswith("uploads/") and not name.endswith("/")):
            continue
        safe_name = os.path.basename(name)
        # Strikte Allowlist: keine Trenner, kein ".." - damit ist der Ziel-
        # pfad strukturell auf UPLOAD_DIR beschraenkt (Zip-Slip unmoeglich).
        if not _UPLOAD_NAME_RE.fullmatch(safe_name):
            continue
        target = os.path.join(upload_root, safe_name)
        if os.path.realpath(target) != os.path.join(upload_root, safe_name):
            continue
        with zf.open(name) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)

    return {
        "ok": True,
        "message": "Wiederhergestellt. Bitte den Container neu starten (docker compose restart), damit die Daten geladen werden.",
    }


