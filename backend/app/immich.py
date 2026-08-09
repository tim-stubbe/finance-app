"""Immich-Anbindung - Aufräum-Vorschläge für die eigene Fotobibliothek.

Bewusst als reine Anbindung gebaut, nicht als Nachbau: Immich erkennt Duplikate
bereits selbst über sein eigenes Machine-Learning-Modell. Hier wird dieses
Ergebnis nur abgeholt, aufbereitet angezeigt und - nach ausdrücklicher
Bestätigung durch den Nutzer - über die Immich-API angewendet.

Zwei Sicherheitsentscheidungen, die bewusst so getroffen sind:

1. **Niemals ungefragt löschen.** Es gibt hier keine Funktion, die ohne
   Zutun des Nutzers Bilder entfernt. Die Auswahl trifft immer der Mensch.
2. **Papierkorb statt endgültig.** Ausgewählte Bilder wandern in Immichs
   eigenen Papierkorb und lassen sich dort zurückholen. `force=true` (das in
   Immich am Papierkorb vorbei endgültig löscht) wird in diesem Modul nirgends
   gesetzt - das ist Absicht, nicht Vergesslichkeit.

Der API-Schlüssel verlässt niemals den Server: Vorschaubilder holt das Backend
und reicht sie an den Browser weiter (siehe `fetch_thumbnail`), damit der
Schlüssel nicht im Frontend landen muss.
"""

import requests

TIMEOUT = 20
# Immichs Vorschaubild-Groessen. "thumbnail" reicht fuer die Kachelansicht und
# haelt die Uebertragung klein - bei Duplikatgruppen werden viele Bilder
# gleichzeitig geladen.
THUMBNAIL_SIZE = "thumbnail"


def _base(url: str) -> str:
    """Normalisiert die Server-Adresse. Der Nutzer trägt in den Einstellungen
    typischerweise die Adresse ein, unter der er Immich im Browser aufruft -
    mit oder ohne abschließenden Schrägstrich, mit oder ohne /api."""
    url = (url or "").strip().rstrip("/")
    if url.endswith("/api"):
        url = url[:-4]
    return url


def _headers(api_key: str) -> dict:
    return {"x-api-key": api_key, "Accept": "application/json"}


def server_version(url: str) -> dict:
    """Erreichbarkeitsprüfung. Braucht bewusst keinen Schlüssel - so lässt sich
    unterscheiden, ob der Server nicht erreichbar oder nur der Schlüssel falsch
    ist. Genau diese Unterscheidung fehlt sonst bei der Fehlersuche."""
    resp = requests.get(f"{_base(url)}/api/server/version", timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def check_connection(url: str, api_key: str) -> dict:
    """Prüft Erreichbarkeit UND Schlüssel und liefert eine sprechende Meldung."""
    version = server_version(url)
    resp = requests.get(
        f"{_base(url)}/api/duplicates", headers=_headers(api_key), timeout=TIMEOUT
    )
    if resp.status_code in (401, 403):
        raise ValueError(
            "Server erreichbar, aber der API-Schlüssel wurde abgelehnt. "
            "Stimmt der Schlüssel, und hat er Rechte für Bilder und Duplikate?"
        )
    resp.raise_for_status()
    v = version
    return {
        "version": f"{v.get('major')}.{v.get('minor')}.{v.get('patch')}",
        "duplicate_groups": len(resp.json() or []),
    }


def trash_config(url: str, api_key: str) -> dict:
    """Liest Immichs Papierkorb-Einstellung.

    Das ist sicherheitsrelevant, nicht bloß Information: Immichs
    `resolve`-Endpunkt entscheidet **anhand dieser Server-Einstellung**, ob
    aussortierte Bilder in den Papierkorb wandern oder sofort endgültig
    verschwinden (`isForce = !trash.enabled`, siehe duplicate.service.ts).
    Ist der Papierkorb in Immich abgeschaltet, löscht derselbe Aufruf also
    unwiderruflich - ohne dass hier im Code irgendetwas anders aussähe.
    Deshalb wird das vor jedem Anwenden geprüft, nicht einmalig angenommen.
    """
    resp = requests.get(
        f"{_base(url)}/api/system-config", headers=_headers(api_key), timeout=TIMEOUT
    )
    resp.raise_for_status()
    trash = (resp.json() or {}).get("trash") or {}
    return {"enabled": bool(trash.get("enabled")), "days": trash.get("days")}


def list_duplicates(url: str, api_key: str) -> list[dict]:
    """Holt die von Immich erkannten Duplikatgruppen.

    Antwortformat je Gruppe: `duplicateId`, `assets` (vollständige Asset-Objekte)
    und `suggestedKeepAssetIds` - Immichs eigener Vorschlag, welche Bilder
    behalten werden sollten. Dieser Vorschlag wird übernommen und dem Nutzer als
    Vorauswahl angeboten, statt eine eigene Heuristik zu erfinden.
    """
    resp = requests.get(
        f"{_base(url)}/api/duplicates", headers=_headers(api_key), timeout=TIMEOUT
    )
    resp.raise_for_status()
    return resp.json() or []


def fetch_thumbnail(url: str, api_key: str, asset_id: str, size: str = THUMBNAIL_SIZE) -> tuple[bytes, str]:
    """Lädt ein Vorschaubild und gibt Bytes + Content-Type zurück.

    Läuft absichtlich über den Server: Würde der Browser die Bilder direkt bei
    Immich holen, müsste der API-Schlüssel im Frontend liegen.

    `size="preview"` liefert eine groessere, aber immer noch komprimierte
    Fassung fuer die Lupen-Ansicht - "original" waere bei einem 8064x6048-HEIC-
    Foto ein zweistelliges MB-Downloaad nur zum Vergleichen, unnoetig langsam.
    """
    resp = requests.get(
        f"{_base(url)}/api/assets/{asset_id}/thumbnail",
        headers={"x-api-key": api_key},
        params={"size": size},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "image/jpeg")


def resolve_duplicates(url: str, api_key: str, groups: list[dict]) -> list[dict]:
    """Wendet die Auswahl des Nutzers an: markierte Bilder in den Papierkorb,
    die Gruppe gilt danach als erledigt.

    `groups` je Eintrag: `duplicateId`, `keepAssetIds`, `trashAssetIds`.
    Immichs eigener Endpunkt erledigt beides in einem Schritt - damit kann kein
    Zwischenzustand entstehen, in dem Bilder schon weg sind, die Gruppe aber
    noch offen ist.
    """
    resp = requests.post(
        f"{_base(url)}/api/duplicates/resolve",
        headers=_headers(api_key),
        json={"groups": groups},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json() or []


def dismiss_duplicate(url: str, api_key: str, duplicate_id: str) -> None:
    """Blendet eine Gruppe aus, ohne irgendein Bild anzufassen - für den Fall,
    dass es gar keine echten Duplikate sind (z.B. bewusst mehrere ähnliche
    Aufnahmen)."""
    resp = requests.delete(
        f"{_base(url)}/api/duplicates/{duplicate_id}",
        headers=_headers(api_key),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()


# Dateinamensmuster, unter denen Betriebssysteme Bildschirmfotos ablegen.
# Bewusst über den Dateinamen erkannt statt über ein Bildmodell: das ist
# nachvollziehbar, kostet keine Rechenzeit und liegt nicht daneben. Ein
# Vision-Modell müsste 683 Bilder ansehen, um dasselbe schlechter zu wissen.
SCREENSHOT_PATTERNS = ["Screenshot", "Bildschirmfoto", "Screen Shot", "Screenshot_"]


def find_screenshots(url: str, api_key: str) -> list[dict]:
    """Sucht alle Bildschirmfotos anhand des Dateinamens.

    Immichs Suche liefert seitenweise (`nextPage`); es wird komplett
    durchgeblättert, weil die Gesamtmenge klein ist (real: knapp 700) und die
    Altersauswertung sonst nur auf einem Ausschnitt basieren würde.
    """
    seen: dict[str, dict] = {}
    for pattern in SCREENSHOT_PATTERNS:
        page = 1
        while page:
            resp = requests.post(
                f"{_base(url)}/api/search/metadata",
                headers=_headers(api_key),
                json={"originalFileName": pattern, "size": 1000,
                      "page": page, "withExif": True},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            block = (resp.json() or {}).get("assets") or {}
            for item in block.get("items") or []:
                # Über mehrere Muster hinweg entdoppeln.
                seen[item["id"]] = item
            nxt = block.get("nextPage")
            page = int(nxt) if nxt else None
    return list(seen.values())


def trash_assets(url: str, api_key: str, asset_ids: list[str]) -> None:
    """Verschiebt Bilder in den Papierkorb.

    `force` ist hier fest auf False - laut Immich-Quelltext (asset.service.ts)
    entscheidet genau dieses Feld zwischen `AssetStatus.Trashed` (holbar) und
    `AssetStatus.Deleted` (weg). Es wird bewusst ausgeschrieben statt
    weggelassen, damit beim Lesen sofort klar ist, was passiert.
    """
    resp = requests.delete(
        f"{_base(url)}/api/assets",
        headers=_headers(api_key),
        json={"ids": asset_ids, "force": False},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()


# ---------- Bildähnlichkeit ----------
# Immich gruppiert Duplikate, sagt aber nicht, WIE ähnlich zwei Bilder sind.
# Genau das ist beim Aussortieren die entscheidende Information: 99 % heisst
# "praktisch dasselbe Bild", 70 % heisst "zwei Aufnahmen derselben Szene".
#
# Verfahren: Differenz-Hash (dHash) über das Vorschaubild. Bewusst kein
# Bildmodell - ein Hash ist deterministisch, in Millisekunden gerechnet und
# beantwortet exakt die gestellte Frage ("wie gleich sehen die aus"). Ein
# neuronales Netz würde hier nur raten, was es sowieso nicht besser weiss.
HASH_SIZE = 8  # ergibt 8x8 Vergleiche = 64 Bit


def _dhash(image_bytes: bytes) -> int:
    """Differenz-Hash: verkleinert das Bild auf 9x8 Graustufen und setzt je
    Pixelpaar ein Bit, ob links heller ist als rechts. Unempfindlich gegen
    Grösse, Kompression und leichte Helligkeitsunterschiede - genau das, was
    zwei Kopien desselben Fotos unterscheidet (bzw. eben nicht).

    Nutzt Pillow statt PyMuPDF: Immich liefert seine Vorschaubilder als WebP
    aus, das PyMuPDF nicht dekodieren kann.
    """
    from io import BytesIO
    from PIL import Image

    img = Image.open(BytesIO(image_bytes)).convert("L").resize(
        (HASH_SIZE + 1, HASH_SIZE), Image.LANCZOS
    )
    px = img.load()
    bits = 0
    for y in range(HASH_SIZE):
        for x in range(HASH_SIZE):
            bits = (bits << 1) | (1 if px[x, y] > px[x + 1, y] else 0)
    return bits


def similarity_percent(hash_a: int, hash_b: int) -> float:
    """Übereinstimmung zweier Hashes in Prozent (64 Bit Hamming-Abstand)."""
    unterschiede = bin(hash_a ^ hash_b).count("1")
    return round((1 - unterschiede / (HASH_SIZE * HASH_SIZE)) * 100, 1)


# Hashes je Asset zwischenspeichern. Ein Bild ändert sich nicht, also muss es
# nie zweimal geladen und gerechnet werden - beim Blättern durch die Gruppen
# spart das den Grossteil der Netzwerkzugriffe.
_hash_cache: dict[str, int] = {}


def asset_hash(url: str, api_key: str, asset_id: str) -> int:
    if asset_id not in _hash_cache:
        content, _ = fetch_thumbnail(url, api_key, asset_id)
        _hash_cache[asset_id] = _dhash(content)
    return _hash_cache[asset_id]


def asset_summary(asset: dict) -> dict:
    """Reduziert ein Immich-Asset auf das, was für die Entscheidung
    „welches behalte ich" wirklich zählt - Dateigröße und Auflösung sind die
    beiden Kriterien, nach denen man Duplikate normalerweise auswählt."""
    exif = asset.get("exifInfo") or {}
    return {
        "id": asset.get("id"),
        "file_name": asset.get("originalFileName"),
        "type": asset.get("type"),
        "created_at": asset.get("fileCreatedAt"),
        "size_bytes": exif.get("fileSizeInByte"),
        "width": exif.get("exifImageWidth"),
        "height": exif.get("exifImageHeight"),
        "camera": " ".join(x for x in [exif.get("make"), exif.get("model")] if x) or None,
    }
