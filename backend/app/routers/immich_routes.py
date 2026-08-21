"""Immich-Endpunkte (Fotobibliothek: Duplikate, Bildschirmfotos, Qualitäts-
Aufräumen, Personen).

Dreizehnter Schritt der Code-Modularisierung (siehe ROADMAP.md) - größter
und am wenigsten zusammenhängender Block bisher: die Settings-Endpunkte
(/settings/immich GET/PUT/DELETE) lagen ursprünglich um Webhook- und
Native-Sync-Einstellungen herum verstreut in main.py; die dazwischen
liegenden, fachlich unabhängigen Endpunkte bleiben unverändert dort.

`immich_credentials` (ohne führenden Unterstrich, anders als sonst intern)
wird auch von main._scheduled_immich_quality_scan gebraucht und deshalb
hier exportiert und in main.py zurückimportiert - gleiches Muster wie
`goal_out` bei routers/goals.py."""

import base64
import random
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import models, schemas, auth, bank_sync, immich, ollama_client
from ..database import get_db

immich_router = APIRouter(prefix="/api")


def immich_credentials(db: Session) -> tuple[str, str]:
    """Holt URL und entschlüsselten Schlüssel oder wirft einen sprechenden
    Fehler, wenn noch nichts eingerichtet ist."""
    s = auth.get_or_create_settings(db)
    if not s.immich_url or not s.immich_api_key_encrypted:
        raise HTTPException(
            400,
            "Immich ist noch nicht eingerichtet. Trage unter Einstellungen die "
            "Server-Adresse und einen API-Schlüssel ein.",
        )
    return s.immich_url, bank_sync.decrypt_secret(s.secret_key, s.immich_api_key_encrypted)


@immich_router.get("/settings/immich", response_model=schemas.ImmichSettingsOut)
def get_immich_settings(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    return schemas.ImmichSettingsOut(
        url=s.immich_url, api_key_set=bool(s.immich_api_key_encrypted),
        skip_confirm=s.immich_skip_confirm,
    )


@immich_router.put("/settings/immich", response_model=schemas.ImmichSettingsOut)
def update_immich_settings(data: schemas.ImmichSettingsUpdate, db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    s.immich_url = data.url.strip()
    # Leeres Feld = Schlüssel unverändert lassen. Sonst müsste man ihn bei jeder
    # kleinen Adressänderung erneut aus Immich heraussuchen.
    if data.api_key:
        s.immich_api_key_encrypted = bank_sync.encrypt_secret(s.secret_key, data.api_key)
    s.immich_skip_confirm = data.skip_confirm
    db.commit()
    return schemas.ImmichSettingsOut(
        url=s.immich_url, api_key_set=bool(s.immich_api_key_encrypted),
        skip_confirm=s.immich_skip_confirm,
    )



@immich_router.delete("/settings/immich", response_model=schemas.ImmichSettingsOut)
def remove_immich_settings(db: Session = Depends(get_db)):
    s = auth.get_or_create_settings(db)
    s.immich_url = None
    s.immich_api_key_encrypted = None
    db.commit()
    return schemas.ImmichSettingsOut(url=None, api_key_set=False)


@immich_router.post("/immich/test", response_model=schemas.ImmichTestResult)
def test_immich(db: Session = Depends(get_db)):
    """Zeigt Fehler bewusst im Klartext an statt sie zu schlucken - eine
    falsche Adresse oder ein abgelehnter Schlüssel liesse sich sonst nicht
    debuggen (gleiches Muster wie beim Telegram-/Twilio-Test)."""
    s = auth.get_or_create_settings(db)
    if not s.immich_url:
        return schemas.ImmichTestResult(ok=False, error="Keine Server-Adresse hinterlegt.")
    if not s.immich_api_key_encrypted:
        return schemas.ImmichTestResult(ok=False, error="Kein API-Schlüssel hinterlegt.")
    try:
        key = bank_sync.decrypt_secret(s.secret_key, s.immich_api_key_encrypted)
        info = immich.check_connection(s.immich_url, key)
        return schemas.ImmichTestResult(ok=True, **info)
    except Exception as e:
        return schemas.ImmichTestResult(ok=False, error=str(e))


# Eine echte Bibliothek liefert schnell mehrere tausend Gruppen (hier real:
# 5.501 Gruppen / 24.143 Aufnahmen, ~6 MB JSON). Alles auf einmal auszuliefern
# und zu rendern legt den Browser lahm, deshalb seitenweise.
DUPLICATES_PAGE_SIZE = 20
# Einzelne Gruppen sind real bis zu 841 Aufnahmen gross - das sind dann keine
# echten Duplikate mehr, sondern eine Serienaufnahme o.ae. Fuer die Anzeige
# gekuerzt; die Gesamtzahl steht weiterhin in `asset_count`.
MAX_ASSETS_PER_GROUP = 24
# Nur die ersten paar Bilder einer Gruppe fuer die Sortierung vergleichen -
# manche Gruppen haben real bis zu 841 Aufnahmen, das waeren sonst hunderte
# Paar-Vergleiche pro Gruppe allein fuer die Reihenfolge einer einzigen Seite.
MAX_ASSETS_FOR_SORT_SIMILARITY = 6


def _best_similarity(url: str, api_key: str, assets: list[dict]) -> float | None:
    """Bester paarweiser Ähnlichkeitswert innerhalb einer Gruppe (fuer die
    Sortierung der Duplikate-Seite, siehe immich_duplicates). None, wenn kein
    einziges Bild dieser Gruppe hashbar war (Netzwerkfehler o.ae.) - eine
    einzelne kaputte Gruppe darf die restliche Seite nicht blockieren."""
    hashes = []
    for a in assets[:MAX_ASSETS_FOR_SORT_SIMILARITY]:
        try:
            hashes.append(immich.asset_hash(url, api_key, a["id"]))
        except Exception:
            continue
    if len(hashes) < 2:
        return None
    return max(
        immich.similarity_percent(hashes[i], hashes[j])
        for i in range(len(hashes)) for j in range(i + 1, len(hashes))
    )


@immich_router.get("/immich/stats", response_model=schemas.ImmichStatsOut)
def immich_stats(db: Session = Depends(get_db)):
    """Kurzer Überblick über die ganze Bibliothek oben im Fotos-Tab. Braucht
    Admin-Rechte auf Immich-Seite - fehlen die, wird das nicht als Fehler
    behandelt, sondern die Kennzahlen bleiben einfach ausgeblendet."""
    url, key = immich_credentials(db)
    try:
        stats = immich.server_statistics(url, key)
    except Exception:
        return schemas.ImmichStatsOut(available=False)
    return schemas.ImmichStatsOut(**stats, available=True)


_IMMICH_AI_MAX_IMAGES = 4


@immich_router.post("/immich/ai-suggestion", response_model=schemas.ImmichAiSuggestionResult)
def immich_ai_suggestion(data: schemas.ImmichAiSuggestionRequest, db: Session = Depends(get_db)):
    """Lässt das Vision-Modell kurz einschätzen, warum ein Foto zum Aufräumen
    taugt bzw. (bei mehreren Bildern) welches einer Duplikat-Gruppe am besten
    ist. Bewusst rein auf Anfrage (Klick), nie automatisch für ganze Listen -
    ein Vision-Modell pro Bild ist auf bescheidener Hardware langsam, und
    niemand braucht eine KI-Begründung für jedes der hunderten Fotos."""
    settings = auth.get_or_create_settings(db)
    model = settings.beleg_chat_model or settings.ollama_model
    if not settings.ollama_url or not model:
        return schemas.ImmichAiSuggestionResult(error="Bitte zuerst Ollama-Server-URL und Modell in den Einstellungen hinterlegen")
    asset_ids = data.asset_ids[:_IMMICH_AI_MAX_IMAGES]
    if not asset_ids:
        return schemas.ImmichAiSuggestionResult(error="Keine Aufnahme ausgewählt")

    url, key = immich_credentials(db)
    images = []
    for asset_id in asset_ids:
        try:
            content, _ = immich.fetch_thumbnail(url, key, asset_id, size="preview")
        except Exception as e:
            return schemas.ImmichAiSuggestionResult(error=f"Vorschaubild konnte nicht geladen werden: {e}")
        images.append(base64.b64encode(content).decode())

    if len(images) == 1:
        prompt = (
            "Das ist ein Foto aus einer privaten Fotobibliothek, das als möglicher "
            "Aufräum-Kandidat markiert wurde (z.B. unscharf, wirkt wie Bildschirmfoto "
            "oder Beleg statt Erinnerungsfoto, oder leer/uninteressant). Schätze in "
            "maximal 2 kurzen Sätzen auf Deutsch ein, ob das Foto wirklich zum Löschen "
            "taugt und warum (oder warum nicht, falls es doch ein Erinnerungswert-Foto ist)."
        )
    else:
        labels = ", ".join(f"Bild {i + 1}" for i in range(len(images)))
        prompt = (
            f"Das sind {len(images)} sehr ähnliche Fotos ({labels}) aus einer Duplikat-Gruppe "
            "einer privaten Fotobibliothek. Schätze in maximal 2 kurzen Sätzen auf Deutsch ein, "
            "welches davon (nach Bildnummer) am besten ist (Schärfe, Bildausschnitt, Belichtung) "
            "und damit behalten werden sollte."
        )
    try:
        reply = ollama_client.chat(
            settings.ollama_url, model,
            [{"role": "user", "content": prompt, "images": images}],
            timeout=900,
        )
    except Exception as e:
        return schemas.ImmichAiSuggestionResult(error=str(e))
    return schemas.ImmichAiSuggestionResult(reason=reply[:600])


@immich_router.get("/immich/duplicates", response_model=schemas.ImmichDuplicatesOut)
def immich_duplicates(
    offset: int = 0,
    limit: int = DUPLICATES_PAGE_SIZE,
    db: Session = Depends(get_db),
):
    url, key = immich_credentials(db)
    try:
        raw = immich.list_duplicates(url, key)
    except Exception as e:
        raise HTTPException(502, f"Immich nicht erreichbar oder Schlüssel abgelehnt: {e}")

    # Byte-identische Gruppen (checksum-Duplikate, "100% Übereinstimmung") immer
    # zuerst. Das passiert VOR der Seiten-Aufteilung, damit das über die ganze
    # Bibliothek gilt und nicht nur innerhalb der gerade geladenen Seite.
    raw.sort(key=lambda g: not immich.has_exact_duplicate(g.get("assets") or []))

    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    total_assets = sum(len(g.get("assets") or []) for g in raw)
    page = raw[offset:offset + limit]

    groups = []
    for g in page:
        all_assets = g.get("assets") or []
        shown = [immich.asset_summary(a) for a in all_assets[:MAX_ASSETS_PER_GROUP]]
        exact = immich.has_exact_duplicate(all_assets)
        best = 100.0 if exact else _best_similarity(url, key, shown)
        groups.append((schemas.ImmichDuplicateGroupOut(
            duplicate_id=g.get("duplicateId"),
            assets=[schemas.ImmichAssetOut(**a) for a in shown],
            suggested_keep_ids=g.get("suggestedKeepAssetIds") or [],
            asset_count=len(all_assets),
            best_similarity_percent=best,
        ), exact, best if best is not None else -1.0))

    # Innerhalb der Seite absteigend nach Ähnlichkeit - 100%-Treffer sind durch
    # die Vorsortierung oben ohnehin schon vorne, `exact` haelt das beim Sortieren
    # zusaetzlich stabil, falls eine Seite mehrere davon enthaelt. Eine echte
    # Sortierung über ALLE tausenden Gruppen hinweg würde bedeuten, für jede
    # ungeprüfte Gruppe erst Bilder herunterzuladen und zu hashen (siehe
    # immich_similarity-Docstring zur selben Falle) - deshalb nur pro Seite,
    # mit Hash-Cache über Seitenaufrufe hinweg (siehe immich._hash_cache).
    groups.sort(key=lambda item: (not item[1], -item[2]))
    groups = [g for g, _exact, _score in groups]
    # Fehlschlag hier darf die Anzeige nicht blockieren - die Sperre beim
    # tatsächlichen Anwenden greift ohnehin unabhängig davon.
    try:
        trash = immich.trash_config(url, key)
    except Exception:
        trash = {"enabled": True, "days": None}

    return schemas.ImmichDuplicatesOut(
        groups=groups, total_groups=len(raw), total_assets=total_assets,
        trash_enabled=trash["enabled"], trash_days=trash["days"],
        offset=offset, limit=limit, has_more=offset + limit < len(raw),
    )


@immich_router.get("/immich/thumbnail/{asset_id}")
def immich_thumbnail(asset_id: str, size: str = "thumbnail", db: Session = Depends(get_db)):
    """Reicht ein Vorschaubild durch, damit der API-Schlüssel den Server nie
    verlässt. Der Browser sieht nur diese eigene Adresse.

    `size=preview` wird von der Lupen-Ansicht genutzt (siehe fetch_thumbnail);
    hier auf die von Immich unterstuetzten Werte eingeschraenkt, weil der
    Parameter direkt vom Browser kommt.
    """
    if size not in ("thumbnail", "preview"):
        raise HTTPException(400, "Ungültige Bildgröße")
    url, key = immich_credentials(db)
    try:
        content, content_type = immich.fetch_thumbnail(url, key, asset_id, size=size)
    except Exception as e:
        raise HTTPException(502, f"Vorschaubild nicht ladbar: {e}")
    # Kurzer Cache: beim Blättern durch viele Gruppen werden dieselben Bilder
    # sonst mehrfach über den Umweg Server neu geholt.
    return Response(content=content, media_type=content_type,
                    headers={"Cache-Control": "private, max-age=300"})


@immich_router.post("/immich/duplicates/resolve", response_model=schemas.ImmichResolveResult)
def immich_resolve(data: schemas.ImmichResolveRequest, db: Session = Depends(get_db)):
    """Wendet die vom Nutzer bestätigte Auswahl an. Bilder wandern in Immichs
    Papierkorb und sind dort wiederherstellbar - endgültiges Löschen passiert
    hier bewusst nie."""
    url, key = immich_credentials(db)

    # Zuerst prüfen, ob Immichs Papierkorb überhaupt aktiv ist. Immich
    # entscheidet anhand dieser Server-Einstellung, ob aussortierte Bilder
    # wiederherstellbar bleiben oder sofort unwiderruflich weg sind - der
    # Aufruf von hier sieht in beiden Fällen identisch aus. Ohne diese Prüfung
    # würde ein Umlegen des Schalters in Immich diese Funktion still von
    # "aufräumen" zu "endgültig vernichten" machen.
    try:
        trash = immich.trash_config(url, key)
    except Exception as e:
        raise HTTPException(502, f"Papierkorb-Einstellung nicht prüfbar, abgebrochen: {e}")
    if not trash["enabled"]:
        raise HTTPException(
            400,
            "Abgebrochen: In Immich ist der Papierkorb abgeschaltet. Aussortierte "
            "Bilder wären sofort unwiderruflich gelöscht statt wiederherstellbar. "
            "Aktiviere den Papierkorb in Immich (Administration → Einstellungen → "
            "Papierkorb), dann klappt es. Es wurde nichts geändert.",
        )

    payload = []
    for g in data.groups:
        # Schutz gegen einen Bedienfehler oder einen Fehler im Frontend: eine
        # Gruppe, in der ALLES weggeworfen wird, ist immer ein Versehen - der
        # Sinn ist, genau ein Bild zu behalten.
        # Kein Zwang mehr zu "mindestens ein Bild bleibt" - der Nutzer soll
        # bewusst auch eine ganze Gruppe leeren koennen, wenn keine der
        # Aufnahmen etwas taugt. Immichs eigene Pruefung verlangt nur, dass
        # jedes Bild in GENAU einer der beiden Listen steht (siehe Overlap-
        # Pruefung gleich darunter) - eine leere keep_ids-Liste ist dafuer
        # bereits gueltig.
        overlap = set(g.keep_ids) & set(g.trash_ids)
        if overlap:
            raise HTTPException(
                400,
                "Ein Bild wurde gleichzeitig zum Behalten und zum Wegwerfen markiert. "
                "Abgebrochen, es wurde nichts geändert.",
            )
        payload.append({
            "duplicateId": g.duplicate_id,
            "keepAssetIds": g.keep_ids,
            "trashAssetIds": g.trash_ids,
        })

    try:
        immich.resolve_duplicates(url, key, payload)
    except Exception as e:
        raise HTTPException(502, f"Immich hat die Änderung abgelehnt: {e}")

    return schemas.ImmichResolveResult(
        resolved_groups=len(payload),
        trashed_assets=sum(len(g.trash_ids) for g in data.groups),
    )


# Ähnlichkeit nur für überschaubare Gruppen rechnen: jedes Bild muss dafür
# einmal geladen werden. Bei den real vorkommenden Riesengruppen (bis 841
# Aufnahmen) wären das hunderte Abrufe für eine Zahl, die dort ohnehin nichts
# aussagt - solche Gruppen sind keine echten Duplikate.
MAX_ASSETS_FOR_SIMILARITY = 12


@immich_router.get("/immich/duplicates/{duplicate_id}/similarity",
                response_model=schemas.ImmichSimilarityOut)
def immich_similarity(duplicate_id: str, asset_ids: str, db: Session = Depends(get_db)):
    """Rechnet aus, wie stark sich die Bilder einer Gruppe gleichen.

    `asset_ids` (kommagetrennt) kommt vom Frontend mit, das die Liste aus der
    ohnehin schon geladenen Gruppe kennt. Frueher wurde hier stattdessen bei
    JEDER Anfrage Immichs komplette Duplikat-Liste neu abgerufen, nur um darin
    die eine gesuchte Gruppe wiederzufinden - bei einer grossen Bibliothek
    (real: 5.500 Gruppen, mehrere MB) macht das 20 Anfragen pro Seite 20 volle
    Neuabrufe. Das legte den Server bei jedem Seitenaufruf spuerbar lahm und
    liess Anfragen haengen bleiben - im Browser sichtbar als voellig
    unzusammenhaengend wirkender Fehler ("access control checks" in Safari
    fuer eine schlicht zu langsam gewordene Verbindung)."""
    ids = [i for i in asset_ids.split(",") if i]
    if not ids:
        raise HTTPException(400, "Keine Bild-IDs übergeben.")
    url, key = immich_credentials(db)
    if len(ids) > MAX_ASSETS_FOR_SIMILARITY:
        return schemas.ImmichSimilarityOut(
            duplicate_id=duplicate_id, pairs={},
            error=f"Zu viele Aufnahmen ({len(ids)}) für einen sinnvollen Vergleich.",
        )

    hashes = {}
    fehler = []
    for asset_id in ids:
        try:
            hashes[asset_id] = immich.asset_hash(url, key, asset_id)
        except Exception as e:
            # Ein einzelnes nicht ladbares Bild darf die Gruppe nicht
            # unbrauchbar machen - aber der Grund muss sichtbar bleiben.
            # Vorher wurde hier stillschweigend weitergemacht, wodurch ein
            # nicht lesbares Bildformat als "leeres Ergebnis ohne Fehler"
            # ankam und wie ein Anzeigefehler aussah.
            fehler.append(f"{type(e).__name__}: {e}")

    pairs = {
        a: {b: immich.similarity_percent(hashes[a], hashes[b])
            for b in hashes if b != a}
        for a in hashes
    }
    err = None
    if fehler:
        err = f"{len(fehler)} von {len(ids)} Bildern nicht vergleichbar ({fehler[0][:80]})"
    return schemas.ImmichSimilarityOut(duplicate_id=duplicate_id, pairs=pairs, error=err)


SCREENSHOT_PAGE_SIZE = 60


@immich_router.get("/immich/screenshots", response_model=schemas.ImmichScreenshotsOut)
def immich_screenshots(
    older_than_months: int = 0,
    offset: int = 0,
    limit: int = SCREENSHOT_PAGE_SIZE,
    db: Session = Depends(get_db),
):
    """Listet Bildschirmfotos, optional nur solche ab einem gewissen Alter."""
    url, key = immich_credentials(db)
    try:
        raw = immich.find_screenshots(url, key)
    except Exception as e:
        raise HTTPException(502, f"Immich nicht erreichbar oder Schlüssel abgelehnt: {e}")

    def taken(a: dict) -> str:
        return a.get("fileCreatedAt") or ""

    # Altersverteilung immer über den kompletten Bestand rechnen, nicht über
    # die gefilterte Auswahl - sonst zeigt die Übersicht nur sich selbst.
    heute = date.today()
    by_age = {"6m": 0, "1j": 0, "2j": 0, "alle": len(raw)}
    for a in raw:
        d = taken(a)[:10]
        if not d:
            continue
        try:
            alter_tage = (heute - date.fromisoformat(d)).days
        except ValueError:
            continue
        if alter_tage >= 180:
            by_age["6m"] += 1
        if alter_tage >= 365:
            by_age["1j"] += 1
        if alter_tage >= 730:
            by_age["2j"] += 1

    gefiltert = raw
    if older_than_months > 0:
        grenze = heute - timedelta(days=int(older_than_months * 30.44))
        gefiltert = [a for a in raw
                     if taken(a)[:10] and taken(a)[:10] < grenze.isoformat()]

    # Älteste zuerst - die sind am ehesten entbehrlich.
    gefiltert.sort(key=taken)

    total_size = sum((a.get("exifInfo") or {}).get("fileSizeInByte") or 0 for a in gefiltert)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    page = gefiltert[offset:offset + limit]

    try:
        trash = immich.trash_config(url, key)
    except Exception:
        trash = {"enabled": True, "days": None}

    return schemas.ImmichScreenshotsOut(
        assets=[schemas.ImmichAssetOut(**immich.asset_summary(a)) for a in page],
        total=len(gefiltert),
        total_size_bytes=total_size,
        by_age=by_age,
        offset=offset, limit=limit, has_more=offset + limit < len(gefiltert),
        trash_enabled=trash["enabled"], trash_days=trash["days"],
    )


@immich_router.post("/immich/screenshots/trash", response_model=schemas.ImmichTrashResult)
def immich_trash_screenshots(data: schemas.ImmichTrashRequest, db: Session = Depends(get_db)):
    """Verschiebt ausgewählte Bildschirmfotos in Immichs Papierkorb."""
    url, key = immich_credentials(db)
    if not data.asset_ids:
        raise HTTPException(400, "Es wurde nichts ausgewählt.")

    # Gleiche Sperre wie beim Auflösen von Duplikaten. Hier zusätzlich
    # abgesichert dadurch, dass `trash_assets` `force=False` fest setzt - aber
    # ein abgeschalteter Papierkorb hiesse, dass Immich das Weggeworfene sofort
    # endgültig entsorgt, und dann soll dieser Weg gar nicht erst offenstehen.
    try:
        trash = immich.trash_config(url, key)
    except Exception as e:
        raise HTTPException(502, f"Papierkorb-Einstellung nicht prüfbar, abgebrochen: {e}")
    if not trash["enabled"]:
        raise HTTPException(
            400,
            "Abgebrochen: In Immich ist der Papierkorb abgeschaltet. Aussortierte "
            "Bilder wären sofort unwiderruflich gelöscht. Es wurde nichts geändert.",
        )

    # Nur echte Bildschirmfotos annehmen. Ohne diese Prüfung könnte über diesen
    # Endpunkt jedes beliebige Bild der Bibliothek weggeworfen werden - die IDs
    # kommen schliesslich aus dem Browser.
    try:
        erlaubt = {a["id"]: a for a in immich.find_screenshots(url, key)}
    except Exception as e:
        raise HTTPException(502, f"Abgleich mit Immich fehlgeschlagen: {e}")
    unbekannt = [i for i in data.asset_ids if i not in erlaubt]
    if unbekannt:
        raise HTTPException(
            400,
            f"{len(unbekannt)} der ausgewählten Bilder sind keine Bildschirmfotos. "
            "Abgebrochen, es wurde nichts geändert.",
        )

    freed = sum((erlaubt[i].get("exifInfo") or {}).get("fileSizeInByte") or 0
                for i in data.asset_ids)
    try:
        immich.trash_assets(url, key, data.asset_ids)
    except Exception as e:
        raise HTTPException(502, f"Immich hat die Änderung abgelehnt: {e}")
    return schemas.ImmichTrashResult(trashed=len(data.asset_ids), freed_bytes=freed)


PHOTOS_PAGE_SIZE = 60


@immich_router.get("/immich/photos", response_model=schemas.ImmichPhotosOut)
def immich_photos(offset: int = 0, limit: int = PHOTOS_PAGE_SIZE, shuffle: bool = False, db: Session = Depends(get_db)):
    """Blaettert ohne jeden Filter durch die gesamte Bibliothek - fuer den
    Swipe-Modus 'Alle Fotos', der bewusst nicht wie Screenshots/Unschaerfe auf
    einen engeren Kandidaten-Ausschnitt beschraenkt ist, sondern wirklich jedes
    Foto zeigt."""
    url, key = immich_credentials(db)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    if shuffle:
        # Immich kennt keine "random"-Sortierung (nur asc/desc) - stattdessen
        # bei jedem Aufruf eine zufaellige Seite aus der ganzen Bibliothek
        # ziehen und ihren Inhalt zusaetzlich mischen. Das offset-Argument wird
        # hier bewusst ignoriert (jeder Aufruf ist unabhaengig "zufaellig"),
        # has_more bleibt True - es gibt kein Ende, nur den naechsten Zufallsgriff.
        try:
            total = max(1, immich.server_statistics(url, key).get("photos", 0))
        except Exception:
            total = 1
        page_num = random.randint(1, max(1, (total + limit - 1) // limit))
    else:
        # Immichs eigene Seitenzaehlung ist 1-basiert und pro Seite fest an `limit`
        # gebunden - offset muss daher ein Vielfaches von limit sein. Das ist die
        # einzige Art, wie das Frontend diesen Endpunkt tatsaechlich aufruft
        # (0, 60, 120, ... - siehe SWIPE_CONFIG).
        page_num = offset // limit + 1
    try:
        raw, has_more = immich.list_assets_page(url, key, page_num, size=limit)
    except Exception as e:
        raise HTTPException(502, f"Immich nicht erreichbar oder Schlüssel abgelehnt: {e}")
    if shuffle:
        random.shuffle(raw)
        has_more = True
    try:
        trash = immich.trash_config(url, key)
    except Exception:
        trash = {"enabled": True, "days": None}
    return schemas.ImmichPhotosOut(
        assets=[schemas.ImmichAssetOut(**immich.asset_summary(a)) for a in raw],
        offset=offset, limit=limit, has_more=has_more,
        trash_enabled=trash["enabled"], trash_days=trash["days"],
    )


@immich_router.post("/immich/photos/trash", response_model=schemas.ImmichTrashResult)
def immich_trash_photos(data: schemas.ImmichTrashRequest, db: Session = Depends(get_db)):
    """Wirft Fotos aus dem Swipe-Modus 'Alle Fotos' weg. Anders als bei
    Screenshots/Unschaerfe gibt es hier keinen engeren Kandidatenkreis, gegen
    den sich die IDs serverseitig gegenpruefen liessen - jedes Foto der
    Bibliothek ist hier ein gueltiges Ziel, genau wie beim Aufloesen einer
    Duplikat-Gruppe."""
    url, key = immich_credentials(db)
    if not data.asset_ids:
        raise HTTPException(400, "Es wurde nichts ausgewählt.")
    try:
        trash = immich.trash_config(url, key)
    except Exception as e:
        raise HTTPException(502, f"Papierkorb-Einstellung nicht prüfbar, abgebrochen: {e}")
    if not trash["enabled"]:
        raise HTTPException(
            400,
            "Abgebrochen: In Immich ist der Papierkorb abgeschaltet. Aussortierte "
            "Bilder wären sofort unwiderruflich gelöscht. Es wurde nichts geändert.",
        )
    try:
        immich.trash_assets(url, key, data.asset_ids)
    except Exception as e:
        raise HTTPException(502, f"Immich hat die Änderung abgelehnt: {e}")
    return schemas.ImmichTrashResult(trashed=len(data.asset_ids), freed_bytes=0)


QUALITY_PAGE_SIZE = 60


@immich_router.get("/immich/quality", response_model=schemas.ImmichQualityOut)
def immich_quality(offset: int = 0, limit: int = QUALITY_PAGE_SIZE, reason: str = "", db: Session = Depends(get_db)):
    """Listet vom Hintergrund-Scan erkannte unscharfe/leere Fotos.

    Liest aus dem lokalen Zwischenspeicher (immich_quality_flags), nicht live
    aus Immich - bei ~24.000 Fotos waere ein Scan bei jedem Seitenaufruf viel
    zu langsam. Siehe _scheduled_immich_quality_scan für den Hintergrund-Job.
    """
    url, key = immich_credentials(db)
    alle = db.query(models.ImmichQualityFlag).filter(models.ImmichQualityFlag.dismissed.is_(False)).all()

    by_reason: dict[str, int] = {}
    for f in alle:
        by_reason[f.reason] = by_reason.get(f.reason, 0) + 1

    # Nach Grund filtern, BEVOR die Seite geschnitten wird - sonst waere die
    # Zaehlung "wie viele Seiten gibt es" beim Filtern falsch.
    gefiltert = [f for f in alle if not reason or f.reason == reason]
    total_size = sum(f.size_bytes or 0 for f in gefiltert)

    # Neueste zuerst - bei unscharfen/leeren Fotos ist kein "Alter" wie bei
    # Screenshots ausschlaggebend, sondern schlicht, dass sie ueberhaupt
    # gefunden wurden.
    gefiltert.sort(key=lambda f: f.scanned_at, reverse=True)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    page = gefiltert[offset:offset + limit]

    try:
        trash = immich.trash_config(url, key)
    except Exception:
        trash = {"enabled": True, "days": None}
    settings = auth.get_or_create_settings(db)

    return schemas.ImmichQualityOut(
        assets=[schemas.ImmichQualityAssetOut(
            id=f.asset_id, file_name=f.file_name, created_at=f.created_at_immich,
            size_bytes=f.size_bytes, width=f.width, height=f.height,
            reason=f.reason, score=f.score,
        ) for f in page],
        total=len(gefiltert), total_size_bytes=total_size, by_reason=by_reason,
        offset=offset, limit=limit, has_more=offset + limit < len(gefiltert),
        trash_enabled=trash["enabled"], trash_days=trash["days"],
        scan_page=settings.immich_quality_scan_page,
    )


@immich_router.post("/immich/quality/trash", response_model=schemas.ImmichTrashResult)
def immich_trash_quality(data: schemas.ImmichTrashRequest, db: Session = Depends(get_db)):
    """Verschiebt ausgewählte unscharfe/leere Fotos in Immichs Papierkorb."""
    url, key = immich_credentials(db)
    if not data.asset_ids:
        raise HTTPException(400, "Es wurde nichts ausgewählt.")

    try:
        trash = immich.trash_config(url, key)
    except Exception as e:
        raise HTTPException(502, f"Papierkorb-Einstellung nicht prüfbar, abgebrochen: {e}")
    if not trash["enabled"]:
        raise HTTPException(
            400,
            "Abgebrochen: In Immich ist der Papierkorb abgeschaltet. Aussortierte "
            "Bilder wären sofort unwiderruflich gelöscht. Es wurde nichts geändert.",
        )

    # Nur Fotos annehmen, die der eigene Scan tatsächlich markiert hat - die
    # IDs kommen aus dem Browser und duerfen nicht ungeprueft an Immich
    # weitergereicht werden.
    erlaubt = {
        f.asset_id: f for f in db.query(models.ImmichQualityFlag)
        .filter(models.ImmichQualityFlag.asset_id.in_(data.asset_ids)).all()
    }
    unbekannt = [i for i in data.asset_ids if i not in erlaubt]
    if unbekannt:
        raise HTTPException(
            400,
            f"{len(unbekannt)} der ausgewählten Bilder sind nicht als unnötig markiert. "
            "Abgebrochen, es wurde nichts geändert.",
        )

    freed = sum(erlaubt[i].size_bytes or 0 for i in data.asset_ids)
    try:
        immich.trash_assets(url, key, data.asset_ids)
    except Exception as e:
        raise HTTPException(502, f"Immich hat die Änderung abgelehnt: {e}")

    for i in data.asset_ids:
        db.delete(erlaubt[i])
    db.commit()
    return schemas.ImmichTrashResult(trashed=len(data.asset_ids), freed_bytes=freed)


@immich_router.delete("/immich/quality/{asset_id}")
def immich_dismiss_quality(asset_id: str, db: Session = Depends(get_db)):
    """Blendet ein Foto aus der Liste aus, ohne es anzufassen ("ist doch okay")."""
    flag = db.query(models.ImmichQualityFlag).filter(models.ImmichQualityFlag.asset_id == asset_id).first()
    if not flag:
        raise HTTPException(404, "Nicht gefunden.")
    flag.dismissed = True
    db.commit()
    return {"ok": True}


@immich_router.get("/immich/people", response_model=schemas.ImmichPeopleOut)
def immich_people(db: Session = Depends(get_db)):
    """Benannte Personen aus Immichs eigener Gesichtserkennung, als weiterer
    Filter zum gezielten Aufräumen ("alle Fotos von X ansehen")."""
    url, key = immich_credentials(db)
    try:
        people = immich.list_people(url, key)
    except Exception as e:
        raise HTTPException(502, f"Immich nicht erreichbar oder Schlüssel abgelehnt: {e}")
    return schemas.ImmichPeopleOut(people=[schemas.ImmichPersonOut(**p) for p in people])


@immich_router.get("/immich/people/{person_id}/thumbnail")
def immich_person_thumbnail(person_id: str, db: Session = Depends(get_db)):
    url, key = immich_credentials(db)
    try:
        content, content_type = immich.fetch_person_thumbnail(url, key, person_id)
    except Exception as e:
        raise HTTPException(502, f"Immich nicht erreichbar: {e}")
    return Response(content=content, media_type=content_type)


@immich_router.get("/immich/people/{person_id}/assets", response_model=schemas.ImmichPersonAssetsOut)
def immich_person_assets(person_id: str, page: int = 1, db: Session = Depends(get_db)):
    url, key = immich_credentials(db)
    try:
        items, has_more = immich.person_assets(url, key, person_id, page)
    except Exception as e:
        raise HTTPException(502, f"Immich nicht erreichbar oder Schlüssel abgelehnt: {e}")
    try:
        trash = immich.trash_config(url, key)
    except Exception:
        trash = {"enabled": True, "days": None}
    return schemas.ImmichPersonAssetsOut(
        assets=[schemas.ImmichAssetOut(**immich.asset_summary(a)) for a in items],
        page=page, has_more=has_more,
        trash_enabled=trash["enabled"], trash_days=trash["days"],
    )


@immich_router.post("/immich/people/{person_id}/trash", response_model=schemas.ImmichTrashResult)
def immich_trash_person_assets(person_id: str, data: schemas.ImmichTrashRequest, db: Session = Depends(get_db)):
    """Verschiebt ausgewählte Fotos einer Person in Immichs Papierkorb."""
    url, key = immich_credentials(db)
    if not data.asset_ids:
        raise HTTPException(400, "Es wurde nichts ausgewählt.")

    try:
        trash = immich.trash_config(url, key)
    except Exception as e:
        raise HTTPException(502, f"Papierkorb-Einstellung nicht prüfbar, abgebrochen: {e}")
    if not trash["enabled"]:
        raise HTTPException(
            400,
            "Abgebrochen: In Immich ist der Papierkorb abgeschaltet. Aussortierte "
            "Bilder wären sofort unwiderruflich gelöscht. Es wurde nichts geändert.",
        )

    # Wie bei den Screenshots: nur IDs annehmen, die wirklich zu dieser Person
    # gehören - die IDs kommen aus dem Browser und dürfen nicht ungeprüft an
    # Immich weitergereicht werden. Dafür alle Seiten der Person durchsuchen.
    erlaubt: dict[str, dict] = {}
    page = 1
    while True:
        try:
            items, has_more = immich.person_assets(url, key, person_id, page)
        except Exception as e:
            raise HTTPException(502, f"Abgleich mit Immich fehlgeschlagen: {e}")
        for a in items:
            erlaubt[a["id"]] = a
        if not has_more or set(data.asset_ids) <= set(erlaubt):
            break
        page += 1
    unbekannt = [i for i in data.asset_ids if i not in erlaubt]
    if unbekannt:
        raise HTTPException(
            400,
            f"{len(unbekannt)} der ausgewählten Bilder gehören nicht zu dieser Person. "
            "Abgebrochen, es wurde nichts geändert.",
        )

    freed = sum((erlaubt[i].get("exifInfo") or {}).get("fileSizeInByte") or 0 for i in data.asset_ids)
    try:
        immich.trash_assets(url, key, data.asset_ids)
    except Exception as e:
        raise HTTPException(502, f"Immich hat die Änderung abgelehnt: {e}")
    return schemas.ImmichTrashResult(trashed=len(data.asset_ids), freed_bytes=freed)


@immich_router.delete("/immich/duplicates/{duplicate_id}")
def immich_dismiss(duplicate_id: str, db: Session = Depends(get_db)):
    """Gruppe ausblenden, ohne ein Bild anzufassen."""
    url, key = immich_credentials(db)
    try:
        immich.dismiss_duplicate(url, key, duplicate_id)
    except Exception as e:
        raise HTTPException(502, f"Immich hat die Änderung abgelehnt: {e}")
    return {"ok": True}
