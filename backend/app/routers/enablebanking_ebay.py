"""Enable Banking (Open-Banking-Aggregator, z.B. C24, Finom) + eBay (Verkäufe
als Konto).

Fünfzehnter Schritt der Code-Modularisierung (siehe ROADMAP.md), nach
investments/tax/debts/goals/trips/wishlist/personal/business_life/
budgets_alerts/deadlines/calendar_todos/categories/immich_routes/
bank_connections. Beide OAuth-artige Anbindungen (Redirect + Callback statt
direktem PIN/API-Key wie bei bank_connections.py) standen im selben
main.py-Abschnitt. Reine Verschiebung ohne Verhaltensänderung."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import schemas, crud, auth, bank_sync, enablebanking_sync, ebay_sync
from ..database import get_db

enablebanking_ebay_router = APIRouter(prefix="/api")


# ---------------- Enable Banking (Open-Banking-Aggregator, z.B. C24, Finom) ----------------
@enablebanking_ebay_router.get("/settings/enablebanking", response_model=schemas.EnableBankingSettingsOut)
def get_enablebanking_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.EnableBankingSettingsOut(
        app_id=settings.enablebanking_app_id,
        private_key_set=bool(settings.enablebanking_private_key_encrypted),
        redirect_base_url=settings.enablebanking_redirect_base_url,
    )


@enablebanking_ebay_router.put("/settings/enablebanking", response_model=schemas.EnableBankingSettingsOut)
def update_enablebanking_settings(data: schemas.EnableBankingSettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.enablebanking_app_id = data.app_id
    settings.enablebanking_private_key_encrypted = bank_sync.encrypt_secret(settings.secret_key, data.private_key)
    settings.enablebanking_redirect_base_url = data.redirect_base_url.strip().rstrip("/") if data.redirect_base_url else None
    db.commit()
    return schemas.EnableBankingSettingsOut(
        app_id=settings.enablebanking_app_id, private_key_set=True,
        redirect_base_url=settings.enablebanking_redirect_base_url,
    )


@enablebanking_ebay_router.get("/enablebanking/aspsps", response_model=List[schemas.AspspOut])
def search_aspsps(country: str, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    if not settings.enablebanking_app_id or not settings.enablebanking_private_key_encrypted:
        raise HTTPException(400, "Bitte zuerst Enable-Banking-App-ID und privaten Schlüssel in den Einstellungen hinterlegen")
    private_key = bank_sync.decrypt_secret(settings.secret_key, settings.enablebanking_private_key_encrypted)
    try:
        aspsps = enablebanking_sync.list_aspsps(settings.enablebanking_app_id, private_key, country.upper())
    except Exception as e:
        raise HTTPException(400, f"Enable-Banking-Fehler: {e}")
    return [
        schemas.AspspOut(name=a.get("name", ""), country=a.get("country", country.upper()), logo=a.get("logo"))
        for a in aspsps
    ]


@enablebanking_ebay_router.get("/enablebanking/connections", response_model=List[schemas.EnableBankingConnectionOut])
def list_enablebanking_connections(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.get_enablebanking_connections(db, space_id)


@enablebanking_ebay_router.post("/enablebanking/connections", response_model=schemas.EnableBankingAuthStart)
def create_enablebanking_connection(data: schemas.EnableBankingConnectionCreate, request: Request, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not crud.get_account(db, data.account_id, space_id):
        raise HTTPException(400, "Ziel-Konto existiert nicht in diesem Bereich")
    settings = auth.get_or_create_settings(db)
    if not settings.enablebanking_app_id or not settings.enablebanking_private_key_encrypted:
        raise HTTPException(400, "Bitte zuerst Enable-Banking-App-ID und privaten Schlüssel in den Einstellungen hinterlegen")
    private_key = bank_sync.decrypt_secret(settings.secret_key, settings.enablebanking_private_key_encrypted)

    state = uuid.uuid4().hex
    conn = crud.create_enablebanking_connection(db, space_id, data.account_id, data.aspsp_name, data.aspsp_country, state)
    # Enable Banking verlangt für Live-Apps eine https-Redirect-URL, die exakt mit
    # der im Portal hinterlegten übereinstimmt - die App selbst läuft aber nur über
    # http. redirect_base_url erlaubt eine feste Override-Adresse (z.B. einen
    # separaten https-Proxy), statt sich auf die zufällig aufgerufene Adresse zu
    # verlassen, die nie https sein wird.
    base = settings.enablebanking_redirect_base_url or str(request.base_url).rstrip("/")
    redirect_url = f"{base}/api/enablebanking/callback"
    try:
        url = enablebanking_sync.start_auth(
            settings.enablebanking_app_id, private_key, data.aspsp_name, data.aspsp_country, redirect_url, state,
        )
    except Exception as e:
        crud.delete_enablebanking_connection(db, conn.id, space_id)
        raise HTTPException(400, f"Enable-Banking-Fehler: {e}")
    return schemas.EnableBankingAuthStart(id=conn.id, url=url)


@enablebanking_ebay_router.get("/enablebanking/callback")
def enablebanking_callback(code: str = None, state: str = None, error: str = None, db: Session = Depends(get_db)):
    if not state:
        return RedirectResponse(url="/?enablebanking_error=missing_state")
    conn = crud.get_enablebanking_connection_by_state(db, state)
    if not conn:
        return RedirectResponse(url="/?enablebanking_error=unknown_state")
    if error or not code:
        conn.status = "error"
        conn.last_sync_status = f"Autorisierung abgebrochen oder fehlgeschlagen: {error or 'kein Code erhalten'}"
        db.commit()
        return RedirectResponse(url=f"/?enablebanking_done={conn.id}")
    settings = auth.get_or_create_settings(db)
    private_key = bank_sync.decrypt_secret(settings.secret_key, settings.enablebanking_private_key_encrypted)
    enablebanking_sync.finalize_connection(db, conn, settings.enablebanking_app_id, private_key, code)
    return RedirectResponse(url=f"/?enablebanking_done={conn.id}")


@enablebanking_ebay_router.delete("/enablebanking/connections/{connection_id}")
def remove_enablebanking_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.delete_enablebanking_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "Verbindung nicht gefunden")
    return {"ok": True}


@enablebanking_ebay_router.post("/enablebanking/connections/{connection_id}/sync", response_model=schemas.SyncResult)
def sync_enablebanking_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.get_enablebanking_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "Verbindung nicht gefunden")
    if conn.status != "linked":
        raise HTTPException(400, "Verbindung ist noch nicht abgeschlossen (Bank-Autorisierung ausstehend)")
    settings = auth.get_or_create_settings(db)
    private_key = bank_sync.decrypt_secret(settings.secret_key, settings.enablebanking_private_key_encrypted)
    result = enablebanking_sync.sync(db, conn, settings.enablebanking_app_id, private_key)
    return schemas.SyncResult(imported=result.get("imported", 0), skipped=result.get("skipped", 0), error=result.get("error"))


# ---------------- eBay (Verkäufe als Konto) ----------------
@enablebanking_ebay_router.get("/settings/ebay", response_model=schemas.EbaySettingsOut)
def get_ebay_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.EbaySettingsOut(
        app_id=settings.ebay_app_id,
        cert_id_set=bool(settings.ebay_cert_id_encrypted),
        ru_name=settings.ebay_ru_name,
    )


@enablebanking_ebay_router.put("/settings/ebay", response_model=schemas.EbaySettingsOut)
def update_ebay_settings(data: schemas.EbaySettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.ebay_app_id = data.app_id
    settings.ebay_cert_id_encrypted = bank_sync.encrypt_secret(settings.secret_key, data.cert_id)
    settings.ebay_ru_name = data.ru_name
    db.commit()
    return schemas.EbaySettingsOut(app_id=settings.ebay_app_id, cert_id_set=True, ru_name=settings.ebay_ru_name)


@enablebanking_ebay_router.get("/ebay/connections", response_model=List[schemas.EbayConnectionOut])
def list_ebay_connections(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    return crud.get_ebay_connections(db, space_id)


@enablebanking_ebay_router.post("/ebay/connections", response_model=schemas.EbayAuthStart)
def create_ebay_connection(data: schemas.EbayConnectionCreate, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    if not crud.get_account(db, data.account_id, space_id):
        raise HTTPException(400, "Ziel-Konto existiert nicht in diesem Bereich")
    settings = auth.get_or_create_settings(db)
    if not settings.ebay_app_id or not settings.ebay_cert_id_encrypted or not settings.ebay_ru_name:
        raise HTTPException(400, "Bitte zuerst App-ID, Cert-ID und RuName in den Einstellungen hinterlegen")

    state = uuid.uuid4().hex
    conn = crud.create_ebay_connection(db, space_id, data.account_id, state)
    url = ebay_sync.build_consent_url(settings.ebay_app_id, settings.ebay_ru_name, state)
    return schemas.EbayAuthStart(id=conn.id, url=url)


@enablebanking_ebay_router.get("/ebay/callback")
def ebay_callback(code: str = None, state: str = None, error: str = None, db: Session = Depends(get_db)):
    if not state:
        return RedirectResponse(url="/?ebay_error=missing_state")
    conn = crud.get_ebay_connection_by_state(db, state)
    if not conn:
        return RedirectResponse(url="/?ebay_error=unknown_state")
    if error or not code:
        conn.status = "error"
        conn.last_sync_status = f"Autorisierung abgebrochen oder fehlgeschlagen: {error or 'kein Code erhalten'}"
        db.commit()
        return RedirectResponse(url=f"/?ebay_done={conn.id}")
    settings = auth.get_or_create_settings(db)
    cert_id = bank_sync.decrypt_secret(settings.secret_key, settings.ebay_cert_id_encrypted)
    ebay_sync.finalize_connection(db, conn, settings.ebay_app_id, cert_id, settings.ebay_ru_name, code)
    return RedirectResponse(url=f"/?ebay_done={conn.id}")


@enablebanking_ebay_router.delete("/ebay/connections/{connection_id}")
def remove_ebay_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.delete_ebay_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "Verbindung nicht gefunden")
    return {"ok": True}


@enablebanking_ebay_router.post("/ebay/connections/{connection_id}/sync", response_model=schemas.SyncResult)
def sync_ebay_connection(connection_id: int, db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    conn = crud.get_ebay_connection(db, connection_id, space_id)
    if not conn:
        raise HTTPException(404, "Verbindung nicht gefunden")
    if conn.status != "connected":
        raise HTTPException(400, "Verbindung ist noch nicht abgeschlossen (eBay-Autorisierung ausstehend)")
    settings = auth.get_or_create_settings(db)
    cert_id = bank_sync.decrypt_secret(settings.secret_key, settings.ebay_cert_id_encrypted)
    result = ebay_sync.sync(db, conn, settings.ebay_app_id, cert_id)
    return schemas.SyncResult(imported=result.get("imported", 0), skipped=result.get("skipped", 0), error=result.get("error"))
