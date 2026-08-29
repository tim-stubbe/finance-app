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

Nachtraeglich (nach Schritt 26, der ai_assistant.py mit websearch_configured
exportierte) noch hinzugefuegt: /ai/auto-categorize/run-now +
run_ai_maintenance_for_space (vorher _run_ai_maintenance_for_space, ohne
fuehrenden Unterstrich exportiert, da main._scheduled_ai_maintenance ihn
weiterhin braucht) sowie /integrations/status - beide waren vorher noch in
main.py, weil ihre jeweilige main.py-only-Abhaengigkeit noch nicht aufgeloest
war. Jetzt sind es reine Paket-Imports, keine main.py-Abhaengigkeit mehr.

Bewusst NICHT mit hierher gezogen:
- /settings/sync-schedule (PUT) - braucht main.scheduler (zirkulär,
  scheduler wird erst nach den Router-Importen definiert)"""

import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from .. import models, schemas, crud, auth, bank_sync, notifications, prices, ai_auto, scalable_sync, net_guard
from ..database import get_db
from .ai_assistant import websearch_configured

settings_misc_router = APIRouter(prefix="/api")
# Eigener Router NUR für den n8n-Webhook-Empfänger (siehe unten) - der ist
# bewusst öffentlich (eigenes Secret im Header statt Login, siehe Docstring
# dort), alles andere in dieser Datei braucht ab jetzt eine Session (siehe
# main.py: settings_misc_router bekommt dependencies=[Depends(auth.
# require_auth)], webhook_public_router explizit NICHT).
webhook_public_router = APIRouter(prefix="/api")


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
        url = (data.searxng_url or "").strip() or None
        if url:
            try:
                net_guard.validate_external_url(url)  # SSRF-Schutz (nur http/https, kein Link-Local/Metadata)
            except net_guard.UnsafeURLError as e:
                raise HTTPException(400, str(e))
        settings.searxng_url = url
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
    # Secret wird bewusst NICHT mehr bei jedem GET im Klartext zurückgegeben
    # (Sicherheitsprüfung: XSS/Session-Diebstahl hätte sonst durch simples
    # Abrufen dieser Seite Zugriff aufs Secret) - nur noch direkt nach
    # "Neu generieren" (siehe regenerate_webhook_secret unten), das ist der
    # einzige Moment, an dem der Nutzer es wirklich sehen/kopieren muss.
    s = auth.get_or_create_settings(db)
    return schemas.WebhookSettingsOut(secret=None, configured=bool(s.n8n_webhook_secret_encrypted))


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
    # Gleiche Begründung wie bei get_webhook_settings oben - Secret nur noch
    # direkt nach "Neu generieren" im Klartext, nicht bei jedem GET.
    s = auth.get_or_create_settings(db)
    return schemas.WebhookSettingsOut(secret=None, configured=bool(s.native_sync_secret_encrypted))


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


@webhook_public_router.post("/webhook/business-issue", response_model=schemas.BusinessIssueOut)
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


def run_ai_maintenance_for_space(db: Session, space_id: int, settings: models.Settings) -> schemas.AutoCategorizeRunResult:
    """Umbuchungen erkennen + (falls eingeschaltet) unkategorisierte Buchungen per
    KI zuordnen. Gemeinsam genutzt vom stündlichen Job und vom manuellen 'Jetzt
    ausführen'-Button, damit beide garantiert dasselbe tun."""
    transfers_marked = crud.detect_and_mark_transfers(db, space_id)
    if transfers_marked:
        settings.transfers_marked_since_digest = (settings.transfers_marked_since_digest or 0) + transfers_marked
        db.commit()
    if not settings.auto_categorize_enabled:
        return schemas.AutoCategorizeRunResult(transfers_marked=transfers_marked, categorized=0, skipped=0)
    result = ai_auto.auto_categorize(db, space_id, settings)
    return schemas.AutoCategorizeRunResult(
        transfers_marked=transfers_marked, categorized=result.categorized,
        skipped=result.skipped, queued=result.queued, error=result.error,
    )


@settings_misc_router.post("/ai/auto-categorize/run-now", response_model=schemas.AutoCategorizeRunResult)
def run_auto_categorize_now(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    settings = auth.get_or_create_settings(db)
    return run_ai_maintenance_for_space(db, space_id, settings)


# ---------------- Einrichtungsstatus der Anbindungen ----------------
@settings_misc_router.get("/integrations/status", response_model=schemas.IntegrationStatusOut)
def integrations_status(db: Session = Depends(get_db)):
    """Zeigt, welche Anbindungen einsatzbereit sind und welche noch Zugangsdaten
    brauchen. Bewusst nur eine Prüfung der hinterlegten Einstellungen, kein
    Verbindungstest: die Übersicht wird bei jedem Seitenaufruf geladen und darf
    nicht auf externen Servern hängen bleiben."""
    s = auth.get_or_create_settings(db)

    # Anzahl der Pflichtfelder je Anbindung. Fehlen alle, ist die Anbindung gar
    # nicht eingerichtet ("missing"); fehlen nur einzelne, wurde sie angefangen
    # ("partial") - das ist der Fall, den man beim Einrichten leicht übersieht.
    FIELD_COUNT = {
        "ollama": 2, "telegram": 2, "twilio": 4, "brave": 1,
        "fints": 2, "enablebanking": 3, "bitvavo": 1, "paypal": 1,
        "immich": 2, "mail": 3, "ebay": 3, "radicale": 2, "scalable": 1,
    }

    def entry(key, name, purpose, missing, optional=True, enabled=True, detail_ok=""):
        if missing:
            status = "missing" if len(missing) >= FIELD_COUNT[key] else "partial"
        elif not enabled:
            status = "off"
        else:
            status = "ok"
        detail = {
            "ok": detail_ok or "Einsatzbereit.",
            "off": "Vollständig eingerichtet, aber abgeschaltet.",
            "partial": "Angefangen, aber noch nicht nutzbar.",
            "missing": "Noch nicht eingerichtet.",
        }[status]
        return schemas.IntegrationStatusItem(
            key=key, name=name, purpose=purpose, status=status,
            detail=detail, missing=missing, optional=optional,
        )

    items = []

    missing = []
    if not s.ollama_url:
        missing.append("Server-Adresse")
    if not s.ollama_model:
        missing.append("Modell")
    items.append(entry(
        "ollama", "Ollama (KI)",
        "KI-Chat, automatische Kategorisierung, Beleg-Auswertung, Antworten des Telegram-Bots",
        missing, optional=False,
    ))

    missing = []
    if not s.telegram_bot_token_encrypted:
        missing.append("Bot-Token")
    if not s.telegram_chat_id:
        missing.append("Chat-ID")
    items.append(entry(
        "telegram", "Telegram",
        "Benachrichtigungen zu Zielen, Cashflow und Budgets; Fragen per Chat",
        missing, enabled=s.notifications_enabled,
    ))

    missing = [label for label, value in (
        ("Account SID", s.twilio_account_sid),
        ("Auth-Token", s.twilio_auth_token_encrypted),
        ("Absendernummer", s.twilio_from_number),
        ("Zielnummer", s.twilio_to_number),
    ) if not value]
    items.append(entry(
        "twilio", "Twilio (Anrufe)",
        "Echte Anrufe bei zeitkritischen Lagen – kostenpflichtig",
        missing, enabled=s.calls_enabled,
    ))

    items.append(entry(
        "brave", "Web-Suche (Brave/SearXNG)",
        "Websuche im KI-Chat",
        [] if websearch_configured(s) else (["SearXNG-URL"] if s.websearch_provider == "searxng" else ["API-Schlüssel"]),
    ))

    missing = []
    if not s.fints_product_id:
        missing.append("Produkt-ID")
    if db.query(models.BankConnection).count() == 0:
        missing.append("mindestens eine Bank-Verbindung")
    items.append(entry(
        "fints", "Bank (FinTS)",
        "Umsätze deutscher Banken automatisch abholen",
        missing,
    ))

    missing = []
    if not s.enablebanking_app_id:
        missing.append("Anwendungs-ID")
    if not s.enablebanking_private_key_encrypted:
        missing.append("Privater Schlüssel")
    if db.query(models.EnableBankingConnection).count() == 0:
        missing.append("mindestens eine Verbindung")
    items.append(entry(
        "enablebanking", "Enable Banking (PSD2)",
        "Banken ohne FinTS anbinden",
        missing,
    ))

    n_bitvavo = db.query(models.BitvavoConnection).count()
    items.append(entry(
        "bitvavo", "Bitvavo",
        "Krypto-Bestände automatisch abgleichen",
        [] if n_bitvavo else ["mindestens eine Verbindung"],
        detail_ok=f"{n_bitvavo} Verbindung{'en' if n_bitvavo != 1 else ''} eingerichtet.",
    ))

    n_paypal = db.query(models.PayPalConnection).count()
    items.append(entry(
        "paypal", "PayPal",
        "PayPal-Umsätze automatisch abholen",
        [] if n_paypal else ["mindestens eine Verbindung"],
        detail_ok=f"{n_paypal} Verbindung{'en' if n_paypal != 1 else ''} eingerichtet.",
    ))

    missing = []
    if not s.ebay_app_id:
        missing.append("App-ID")
    if not s.ebay_cert_id_encrypted:
        missing.append("Cert-ID")
    if not s.ebay_ru_name:
        missing.append("RuName")
    n_ebay = db.query(models.EbayConnection).filter(models.EbayConnection.status == "connected").count()
    if not missing and n_ebay == 0:
        missing.append("mindestens eine Verbindung")
    items.append(entry(
        "ebay", "eBay",
        "Verkäufe wie ein Konto einbinden",
        missing,
        detail_ok=f"{n_ebay} Verbindung{'en' if n_ebay != 1 else ''} verbunden." if n_ebay else None,
    ))

    missing = []
    if not s.radicale_url:
        missing.append("Server-Adresse")
    if not s.radicale_password_encrypted:
        missing.append("Zugangsdaten")
    n_todos = db.query(models.Todo).count()
    items.append(entry(
        "radicale", "To-Dos (Radicale)",
        "To-Dos zweiseitig mit dem Handy synchronisieren",
        missing,
        detail_ok=f"{n_todos} To-Do{'s' if n_todos != 1 else ''} synchronisiert." if n_todos else None,
    ))

    missing = []
    if not s.immich_url:
        missing.append("Server-Adresse")
    if not s.immich_api_key_encrypted:
        missing.append("API-Schlüssel")
    items.append(entry(
        "immich", "Immich (Fotos)",
        "Doppelte Fotos finden und nach Bestätigung aufräumen",
        missing,
    ))

    missing = [label for label, value in (
        ("IMAP-Server", s.imap_host),
        ("Benutzername", s.imap_user),
        ("Passwort", s.imap_password_encrypted),
    ) if not value]
    items.append(entry(
        "mail", "E-Mail-Postfach",
        "Belege aus Anhängen holen und Buchungen zuordnen",
        missing, enabled=s.mail_enabled,
    ))

    missing = [] if s.scalable_enabled else ["Aktivieren + einmaliger Login im Container"]
    items.append(entry(
        "scalable", "Scalable Capital (Investments)",
        "Positionen und Käufe/Verkäufe automatisch abgleichen",
        missing,
        detail_ok=s.scalable_last_sync_status or "Einsatzbereit.",
    ))

    return schemas.IntegrationStatusOut(
        items=items,
        ready=sum(1 for i in items if i.status == "ok"),
        incomplete=sum(1 for i in items if i.status in ("missing", "partial")),
    )


# ---------------- Scalable Capital (Investments) ----------------
# Login laeuft bewusst NICHT durch diese Route (siehe scalable_sync.py-
# Docstring: Device-Code-Flow, "human-oriented", einmalig per
# `docker exec -it ... sc login --local-read-only` im Container). Hier nur
# an/aus schalten (nachdem der Login extern gemacht wurde) + manueller Sync.
@settings_misc_router.get("/settings/scalable", response_model=schemas.ScalableSettingsOut)
def get_scalable_settings(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    return schemas.ScalableSettingsOut(
        enabled=s.scalable_enabled, last_sync_at=s.scalable_last_sync_at,
        last_sync_status=s.scalable_last_sync_status,
    )


@settings_misc_router.put("/settings/scalable", response_model=schemas.ScalableSettingsOut)
def update_scalable_settings(data: schemas.ScalableSettingsUpdate, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    s.scalable_enabled = data.enabled
    db.commit()
    return schemas.ScalableSettingsOut(
        enabled=s.scalable_enabled, last_sync_at=s.scalable_last_sync_at,
        last_sync_status=s.scalable_last_sync_status,
    )


@settings_misc_router.post("/scalable/sync", response_model=schemas.ScalableSyncResult)
def sync_scalable_now(db: Session = Depends(get_db), space_id: int = Depends(auth.get_active_space_id)):
    s = auth.get_or_create_settings(db)
    if not s.scalable_enabled:
        raise HTTPException(400, "Scalable Capital ist nicht aktiviert (Einstellungen → Weitere Verbindungen).")
    try:
        result = scalable_sync.sync(db, s, space_id)
    except Exception as e:
        s.scalable_last_sync_status = f"Fehler: {e}"
        db.commit()
        return schemas.ScalableSyncResult(created=0, updated=0, lots_added=0, error=str(e))
    return schemas.ScalableSyncResult(**result)
