"""Verstreute Settings + Meta-Endpunkte: FinTS-Produkt-ID, Auto-
Kategorisierung (An/Aus), Web-Suche (Brave/SearXNG), Anzeige-Währung,
Wohnsitzland, Wechselkurs, eingehender n8n-Webhook (Secret + Business-
Issue-Empfang), nativer macOS/iOS-Sync-Secret, Versions-Check (laufende
vs. neueste veröffentlichte Version via ghcr.io).

Einundzwanzigster Schritt der Code-Modularisierung (siehe ROADMAP.md),
nach investments/tax/debts/goals/trips/wishlist/personal/business_life/
budgets_alerts/deadlines/calendar_todos/categories/immich_routes/
bank_connections/enablebanking_ebay/mail_routes/spaces_accounts/
backup_restore/export_import/analytics. Mehrere kleine, in main.py
zwischen Sync-Zeitplan/Auto-Kategorisierung-Trigger/AI-Endpunkten
verstreute Settings-Blöcke, hier gebündelt statt einzeln.

Bewusst NICHT mit hierher gezogen:
- /settings/sync-schedule (PUT) - braucht main.scheduler (zirkulär,
  scheduler wird erst nach den Router-Importen definiert)
- /ai/auto-categorize/run-now - braucht main._run_ai_maintenance_for_space
  (dieselbe Zirkularitaet)
- /integrations/status - braucht main._websearch_configured (Teil des
  /ai-Abschnitts, der komplett in main.py bleibt)"""

import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from .. import models, schemas, crud, auth, bank_sync, notifications, prices
from ..database import get_db

settings_misc_router = APIRouter(prefix="/api")


# ---------------- FinTS Bank-Sync ----------------
@settings_misc_router.get("/settings/fints")
def get_fints_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return {"fints_product_id": settings.fints_product_id}


@settings_misc_router.put("/settings/fints")
def update_fints_settings(data: schemas.FintsSettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.fints_product_id = data.fints_product_id
    db.commit()
    return {"fints_product_id": settings.fints_product_id}

# ---------------- Automatisierung (Umbuchungen + Auto-Kategorisierung) ----------------
@settings_misc_router.get("/settings/auto-categorize", response_model=schemas.AutoCategorizeSettingsOut)
def get_auto_categorize_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.AutoCategorizeSettingsOut(enabled=settings.auto_categorize_enabled)


@settings_misc_router.put("/settings/auto-categorize", response_model=schemas.AutoCategorizeSettingsOut)
def update_auto_categorize_settings(data: schemas.AutoCategorizeSettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.auto_categorize_enabled = data.enabled
    db.commit()
    return schemas.AutoCategorizeSettingsOut(enabled=settings.auto_categorize_enabled)

def _websearch_settings_out(settings: models.Settings) -> schemas.WebSearchSettingsOut:
    return schemas.WebSearchSettingsOut(
        provider=settings.websearch_provider,
        api_key_set=bool(settings.brave_search_api_key_encrypted),
        searxng_url=settings.searxng_url,
    )


@settings_misc_router.get("/settings/websearch", response_model=schemas.WebSearchSettingsOut)
def get_websearch_settings(db: Session = Depends(get_db)):
    return _websearch_settings_out(auth.get_or_create_settings(db))


@settings_misc_router.put("/settings/websearch", response_model=schemas.WebSearchSettingsOut)
def update_websearch_settings(data: schemas.WebSearchSettingsUpdate, db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    if data.api_key:
        settings.brave_search_api_key_encrypted = bank_sync.encrypt_secret(settings.secret_key, data.api_key)
    db.commit()
    return _websearch_settings_out(settings)


@settings_misc_router.delete("/settings/websearch", response_model=schemas.WebSearchSettingsOut)
def remove_websearch_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    settings.brave_search_api_key_encrypted = None
    db.commit()
    return _websearch_settings_out(settings)


@settings_misc_router.put("/settings/websearch/provider", response_model=schemas.WebSearchSettingsOut)
def update_websearch_provider(data: schemas.WebSearchProviderUpdate, db: Session = Depends(get_db)):
    if data.provider not in ("brave", "searxng"):
        raise HTTPException(400, "Unbekannter Anbieter (brave/searxng)")
    settings = auth.get_or_create_settings(db)
    settings.websearch_provider = data.provider
    if data.provider == "searxng":
        settings.searxng_url = (data.searxng_url or "").strip() or None
    db.commit()
    return _websearch_settings_out(settings)


# ---------------- Anzeige-Währung (rein Frontend-Umrechnung, gespeichert bleibt EUR) ----------------
@settings_misc_router.get("/settings/currency", response_model=schemas.CurrencySettingsOut)
def get_currency_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.CurrencySettingsOut(currency=settings.display_currency)


@settings_misc_router.put("/settings/currency", response_model=schemas.CurrencySettingsOut)
def update_currency_settings(data: schemas.CurrencySettingsUpdate, db: Session = Depends(get_db)):
    currency = data.currency.upper().strip()
    if currency not in ("EUR", "CHF"):
        raise HTTPException(400, "Nur EUR oder CHF werden unterstützt")
    settings = auth.get_or_create_settings(db)
    settings.display_currency = currency
    db.commit()
    return schemas.CurrencySettingsOut(currency=settings.display_currency)


# ---------------- Wohnsitzland (blendet landesspezifische Anbindungen in den Einstellungen ein/aus) ----------------
@settings_misc_router.get("/settings/country", response_model=schemas.CountrySettingsOut)
def get_country_settings(db: Session = Depends(get_db)):
    settings = auth.get_or_create_settings(db)
    return schemas.CountrySettingsOut(country=settings.residence_country)


@settings_misc_router.put("/settings/country", response_model=schemas.CountrySettingsOut)
def update_country_settings(data: schemas.CountrySettingsUpdate, db: Session = Depends(get_db)):
    country = data.country.upper().strip()
    if country not in ("DE", "CH"):
        raise HTTPException(400, "Nur DE oder CH werden unterstützt")
    settings = auth.get_or_create_settings(db)
    settings.residence_country = country
    db.commit()
    return schemas.CountrySettingsOut(country=settings.residence_country)


@settings_misc_router.get("/fx/rate", response_model=schemas.FxRateOut)
def get_fx_rate(to: str = "CHF"):
    to = to.upper().strip()
    try:
        rate = prices.get_cached_fx_rate("EUR", to)
    except Exception as e:
        raise HTTPException(502, f"Wechselkurs EUR/{to} gerade nicht verfügbar: {e}")
    return schemas.FxRateOut(from_currency="EUR", to_currency=to, rate=rate)


# ---------------- Eingehender Webhook (z.B. n8n meldet E-Mail-Ereignisse) ----------------
@settings_misc_router.get("/settings/webhook", response_model=schemas.WebhookSettingsOut)
def get_webhook_settings(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    if not s.n8n_webhook_secret_encrypted:
        return schemas.WebhookSettingsOut(secret=None, configured=False)
    secret = bank_sync.decrypt_secret(s.secret_key, s.n8n_webhook_secret_encrypted)
    return schemas.WebhookSettingsOut(secret=secret, configured=True)


@settings_misc_router.post("/settings/webhook/regenerate", response_model=schemas.WebhookSettingsOut)
def regenerate_webhook_secret(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    new_secret = secrets.token_urlsafe(32)
    s.n8n_webhook_secret_encrypted = bank_sync.encrypt_secret(s.secret_key, new_secret)
    db.commit()
    return schemas.WebhookSettingsOut(secret=new_secret, configured=True)


@settings_misc_router.delete("/settings/webhook")
def remove_webhook_secret(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    s.n8n_webhook_secret_encrypted = None
    db.commit()
    return {"ok": True}


# ---------------- Nativer macOS-Client (Offline-Sync) ----------------
@settings_misc_router.get("/settings/native-sync", response_model=schemas.WebhookSettingsOut)
def get_native_sync_settings(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    if not s.native_sync_secret_encrypted:
        return schemas.WebhookSettingsOut(secret=None, configured=False)
    secret = bank_sync.decrypt_secret(s.secret_key, s.native_sync_secret_encrypted)
    return schemas.WebhookSettingsOut(secret=secret, configured=True)


@settings_misc_router.post("/settings/native-sync/regenerate", response_model=schemas.WebhookSettingsOut)
def regenerate_native_sync_secret(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    new_secret = secrets.token_urlsafe(32)
    s.native_sync_secret_encrypted = bank_sync.encrypt_secret(s.secret_key, new_secret)
    db.commit()
    return schemas.WebhookSettingsOut(secret=new_secret, configured=True)


@settings_misc_router.delete("/settings/native-sync")
def remove_native_sync_secret(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    s.native_sync_secret_encrypted = None
    db.commit()
    return {"ok": True}


@settings_misc_router.post("/webhook/business-issue", response_model=schemas.BusinessIssueOut)
def webhook_create_business_issue(
    data: schemas.WebhookIssueCreate, db: Session = Depends(get_db),
    x_webhook_secret: Optional[str] = Header(None),
):
    """Nimmt fertige Ereignisse von außen entgegen (z.B. n8n, das E-Mails
    ausgewertet hat) und legt sie als offenen Punkt bei einem Business-Projekt
    an - Kies wertet die E-Mails NICHT selbst aus (Nutzerentscheidung, das
    bleibt bei n8n), sondern ist hier nur Empfänger des fertigen Ergebnisses.
    Kein space_id/Session-Cookie wie bei den übrigen Endpunkten (der Aufrufer
    ist kein eingeloggter Browser), stattdessen ein geteiltes Secret im
    Header - secrets.compare_digest statt "==", um eine Timing-Angriffsfläche
    gar nicht erst zu eröffnen, auch wenn das Netz (Tailscale/Docker intern)
    ohnehin schon nicht öffentlich erreichbar ist."""
    s = auth.get_or_create_settings(db)
    if not s.n8n_webhook_secret_encrypted:
        raise HTTPException(403, "Webhook ist noch nicht eingerichtet (Einstellungen → Weitere Verbindungen).")
    expected = bank_sync.decrypt_secret(s.secret_key, s.n8n_webhook_secret_encrypted)
    if not x_webhook_secret or not secrets.compare_digest(x_webhook_secret, expected):
        raise HTTPException(403, "Ungültiges Secret.")

    project, error = crud.find_business_project_by_name(db, data.project)
    if error:
        raise HTTPException(404, error)
    issue = crud.create_business_issue(db, project.id, data.title, data.notes)
    notifications.notify(s, f"📧 Neue Meldung bei „{project.name}“: {data.title}")
    return issue


# Ergebnis kurz zwischenspeichern - dieser Endpunkt wird bei jedem Seitenaufruf
# abgefragt, ein anonymer GHCR-Blick fuer jeden davon waere unnoetig und bei
# vielen Tabs/Nutzern schnell spuerbar langsam.
_latest_version_cache: dict = {"checked_at": None, "result": None}
GHCR_IMAGE = "tim-stubbe/finance-app"


def _fetch_latest_published_sha() -> schemas.LatestVersionOut:
    """Fragt anonym bei ghcr.io nach dem git-SHA-Label des aktuell
    veroeffentlichten :latest-Images. Braucht dafuer, dass das Paket wirklich
    oeffentlich ist (siehe Docker-LABEL im Dockerfile) - ist es das (noch)
    nicht, kommt sauber `available=False` zurueck statt eines Fehlers, der wie
    ein Problem im eigenen System aussehen wuerde."""
    try:
        token_resp = requests.get(
            "https://ghcr.io/token",
            params={"service": "ghcr.io", "scope": f"repository:{GHCR_IMAGE}:pull"},
            timeout=5,
        )
        token = token_resp.json().get("token") if token_resp.ok else None
        if not token:
            return schemas.LatestVersionOut(available=False, error="Paket nicht öffentlich abrufbar")

        manifest_headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.docker.distribution.manifest.v2+json, "
                      "application/vnd.docker.distribution.manifest.list.v2+json, "
                      "application/vnd.oci.image.manifest.v1+json, "
                      "application/vnd.oci.image.index.v1+json",
        }
        manifest_resp = requests.get(
            f"https://ghcr.io/v2/{GHCR_IMAGE}/manifests/latest",
            headers=manifest_headers, timeout=5,
        )
        manifest_resp.raise_for_status()
        manifest = manifest_resp.json()

        # Multi-Architektur-Image: das docker-publish.yml-Buildx baut fuer
        # mehrere Plattformen, "latest" zeigt deshalb auf eine Index-Liste statt
        # direkt auf ein einzelnes Manifest - amd64 heraussuchen (das laeuft auf
        # der TrueNAS-Box).
        if "manifests" in manifest:
            eintrag = next(
                (m for m in manifest["manifests"]
                 if m.get("platform", {}).get("architecture") == "amd64"),
                manifest["manifests"][0],
            )
            manifest_resp = requests.get(
                f"https://ghcr.io/v2/{GHCR_IMAGE}/manifests/{eintrag['digest']}",
                headers=manifest_headers, timeout=5,
            )
            manifest_resp.raise_for_status()
            manifest = manifest_resp.json()

        config_digest = manifest["config"]["digest"]

        config_resp = requests.get(
            f"https://ghcr.io/v2/{GHCR_IMAGE}/blobs/{config_digest}",
            headers={"Authorization": f"Bearer {token}"}, timeout=5,
        )
        config_resp.raise_for_status()
        sha = config_resp.json().get("config", {}).get("Labels", {}).get(
            "org.opencontainers.image.revision")
        if not sha:
            return schemas.LatestVersionOut(available=False, error="Kein Revisions-Label im Image")
        return schemas.LatestVersionOut(available=True, git_sha=sha, git_sha_short=sha[:7])
    except Exception as e:
        return schemas.LatestVersionOut(available=False, error=str(e))


@settings_misc_router.get("/version/latest", response_model=schemas.LatestVersionOut)
def get_latest_version():
    now = datetime.utcnow()
    if (_latest_version_cache["checked_at"]
            and now - _latest_version_cache["checked_at"] < timedelta(minutes=10)):
        return _latest_version_cache["result"]
    result = _fetch_latest_published_sha()
    _latest_version_cache["checked_at"] = now
    _latest_version_cache["result"] = result
    return result


@settings_misc_router.get("/version", response_model=schemas.VersionOut)
def get_version():
    """Welcher Stand tatsächlich läuft - unabhängig davon, ob ein Update
    (Watchtower oder manuell) wirklich angekommen ist oder ob eine sichtbare
    Änderung schlicht an einem alten, nicht aktualisierten Container liegt."""
    sha = os.environ.get("GIT_SHA", "dev")
    return schemas.VersionOut(
        git_sha=sha,
        git_sha_short=sha[:7],
        build_date=os.environ.get("BUILD_DATE") or None,
    )
