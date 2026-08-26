"""Sammel-Sync aller Verbindungen (FinTS, Bitvavo, PayPal, Enable Banking,
eBay, Scalable Capital) - manueller Trigger per Knopfdruck.

Fuenfundzwanzigster Schritt der Code-Modularisierung (siehe ROADMAP.md),
nach investments/tax/debts/goals/trips/wishlist/personal/business_life/
budgets_alerts/deadlines/calendar_todos/categories/immich_routes/
bank_connections/enablebanking_ebay/mail_routes/spaces_accounts/
backup_restore/export_import/analytics/settings_misc/notify_settings/
dashboard/profile_ollama.

`sync_all_connections` (ohne fuehrenden Unterstrich wie die anderen
main.py-Rueckimporte) wird auch von main._scheduled_bank_sync und
main._scheduled_digest gebraucht, deshalb exportiert und in main.py
zurueckimportiert - gleiches Muster wie goal_out/immich_credentials/
run_mail_sync/write_backup_to_disk/HOLDING_ASSET_TYPE_ALIASES."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import schemas, crud, auth, bank_sync, exchange_sync, paypal_sync, enablebanking_sync, ebay_sync, scalable_sync
from ..database import get_db

sync_all_router = APIRouter(prefix="/api")


# ---------------- Automatischer Sync (Bank, Bitvavo, PayPal, Enable Banking) ----------------
def sync_all_connections(db, settings):
    """Synct alle Bank-/Broker-/Marktplatz-Verbindungen (FinTS, Bitvavo,
    PayPal, Enable Banking, eBay, Scalable Capital) - bewusst OHNE Kurs-
    Refresh der UEBRIGEN (manuell gepflegten) Investments (das ist ein
    separater, nutzer-getriggerter Schritt, siehe POST /holdings/refresh-
    prices) - Scalable-Positionen bekommen ihren Kurs stattdessen direkt aus
    der Depot-Antwort mit (siehe scalable_sync.py), wie schon Bitvavo es tut.
    Gemeinsam genutzt vom taeglichen
    _scheduled_bank_sync UND vom Digest (siehe _scheduled_digest), der vor
    jeder Meldung frische Zahlen braucht statt auf den naechsten taeglichen
    Sync zu warten. Jede Verbindung isoliert in try/except, damit eine
    fehlschlagende Verbindung die anderen nicht blockiert."""
    if settings.fints_product_id:
        for conn in crud.get_all_bank_connections(db):
            try:
                pin = bank_sync.decrypt_pin(settings.secret_key, conn.pin_encrypted)
                since = conn.last_sync_at.date() if conn.last_sync_at else date.today() - timedelta(days=90)
                bank_sync.start_sync(db, conn, pin, settings.fints_product_id, since)
            except Exception as e:
                conn.last_sync_status = f"Fehler beim automatischen Sync: {e}"
                db.commit()

    for bv_conn in crud.get_all_bitvavo_connections(db):
        try:
            api_key = bank_sync.decrypt_secret(settings.secret_key, bv_conn.api_key_encrypted)
            api_secret = bank_sync.decrypt_secret(settings.secret_key, bv_conn.api_secret_encrypted)
            exchange_sync.sync(db, bv_conn, api_key, api_secret, bv_conn.space_id)
        except Exception as e:
            bv_conn.last_sync_status = f"Fehler beim automatischen Sync: {e}"
            db.commit()

    for pp_conn in crud.get_all_paypal_connections(db):
        try:
            client_id = bank_sync.decrypt_secret(settings.secret_key, pp_conn.client_id_encrypted)
            client_secret = bank_sync.decrypt_secret(settings.secret_key, pp_conn.client_secret_encrypted)
            paypal_sync.sync(db, pp_conn, client_id, client_secret)
        except Exception as e:
            pp_conn.last_sync_status = f"Fehler beim automatischen Sync: {e}"
            db.commit()

    if settings.enablebanking_app_id and settings.enablebanking_private_key_encrypted:
        private_key = bank_sync.decrypt_secret(settings.secret_key, settings.enablebanking_private_key_encrypted)
        for eb_conn in crud.get_all_enablebanking_connections(db):
            if eb_conn.status != "linked":
                continue
            try:
                enablebanking_sync.sync(db, eb_conn, settings.enablebanking_app_id, private_key)
            except Exception as e:
                eb_conn.last_sync_status = f"Fehler beim automatischen Sync: {e}"
                db.commit()

    if settings.ebay_app_id and settings.ebay_cert_id_encrypted:
        cert_id = bank_sync.decrypt_secret(settings.secret_key, settings.ebay_cert_id_encrypted)
        for eb_conn in crud.get_all_ebay_connections(db):
            if eb_conn.status != "connected":
                continue
            try:
                ebay_sync.sync(db, eb_conn, settings.ebay_app_id, cert_id)
            except Exception as e:
                eb_conn.last_sync_status = f"Fehler beim automatischen Sync: {e}"
                db.commit()

    if settings.scalable_enabled:
        space_id = settings.scalable_space_id or (crud.get_spaces(db)[0].id if crud.get_spaces(db) else None)
        if space_id:
            try:
                scalable_sync.sync(db, settings, space_id)
            except Exception as e:
                settings.scalable_last_sync_status = f"Fehler: {e}"
                db.commit()


@sync_all_router.post("/sync-all", response_model=schemas.SyncAllResult)
def sync_all_connections_now(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    """Stößt denselben Sync an, den sonst nur der tägliche Job und der Digest
    vor jeder Meldung auslösen (siehe sync_all_connections) - manuell per
    Knopfdruck statt zu warten. Das Ergebnis wird aus last_sync_status/-at je
    Verbindung gelesen, die sync_all_connections für jede Verbindung ohnehin
    schon setzt (Erfolg wie Fehlschlag), statt die leicht unterschiedlichen
    Rückgabewerte der einzelnen sync()-Funktionen selbst zu vereinheitlichen."""
    settings = auth.get_or_create_settings(db)
    sync_all_connections(db, settings)

    results = []
    for conn in crud.get_all_bank_connections(db):
        results.append(schemas.SyncAllConnectionResult(name=conn.name, kind="Bank (FinTS)", status=conn.last_sync_status))
    for conn in crud.get_all_bitvavo_connections(db):
        results.append(schemas.SyncAllConnectionResult(name=conn.name, kind="Bitvavo", status=conn.last_sync_status))
    for conn in crud.get_all_paypal_connections(db):
        results.append(schemas.SyncAllConnectionResult(name=conn.name, kind="PayPal", status=conn.last_sync_status))
    for conn in crud.get_all_enablebanking_connections(db):
        results.append(schemas.SyncAllConnectionResult(name=conn.aspsp_name, kind="Enable Banking", status=conn.last_sync_status))
    for conn in crud.get_all_ebay_connections(db):
        results.append(schemas.SyncAllConnectionResult(name=conn.ebay_username or "eBay", kind="eBay", status=conn.last_sync_status))
    return schemas.SyncAllResult(connections=results)
