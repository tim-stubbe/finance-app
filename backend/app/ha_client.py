"""Home-Assistant-Client (REST).

Bewusst dasselbe schlichte Muster wie ollama_client.py: modul-weite
Funktionen, synchrones `requests`, keine Klassen-Instanz. Die Aufrufer
(routers/smarthome.py, smarthome.py) holen URL/Token aus den Settings und
geben sie hier herein - dieses Modul kennt weder DB noch Settings.

WebSocket (Live-State-Push fuer die UI) ist noch NICHT drin - REST-Polling
reicht fuer Phase 1, siehe smarthome.py-Kopfkommentar "Naechste Schritte".
"""

import requests

# Zeitfenster bewusst kurz: ein Sprachbefehl, der 30 s auf HA wartet, ist
# unbrauchbar. Lieber schnell eine verstaendliche Fehlermeldung.
_TIMEOUT = 10


class HAError(Exception):
    """Fehler mit einer bereits deutschen, nutzbaren Meldung in `str(exc)`."""


def _base(url: str) -> str:
    return (url or "").rstrip("/")


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _request(method: str, url: str, token: str, path: str, *, json=None):
    if not _base(url):
        raise HAError("Keine Home-Assistant-URL hinterlegt (Einstellungen -> Smart Home).")
    if not token:
        raise HAError(
            "Kein Home-Assistant-Token hinterlegt. In HA unter Profil -> "
            "'Langlebige Zugangs-Tokens' erstellen und in den Einstellungen eintragen."
        )
    full = f"{_base(url)}/api{path}"
    try:
        resp = requests.request(method, full, headers=_headers(token), json=json, timeout=_TIMEOUT)
    except requests.exceptions.ConnectTimeout:
        raise HAError("Home Assistant hat nicht rechtzeitig geantwortet (Verbindungs-Timeout).")
    except requests.exceptions.ReadTimeout:
        raise HAError("Home Assistant hat nicht rechtzeitig geantwortet (Timeout).")
    except requests.exceptions.ConnectionError:
        raise HAError(f"Home Assistant ist nicht erreichbar unter {_base(url)}. Laeuft HA?")
    except requests.exceptions.RequestException as exc:
        raise HAError(f"Netzwerkfehler zu Home Assistant: {exc}")

    if resp.status_code == 401:
        raise HAError("Home Assistant lehnt den Token ab (401). Token abgelaufen oder falsch?")
    if resp.status_code == 403:
        raise HAError("Home Assistant verweigert den Zugriff (403).")
    if resp.status_code == 404:
        raise HAError(f"Home-Assistant-Objekt nicht gefunden: {path}")
    if not resp.ok:
        raise HAError(f"Home Assistant meldet einen Fehler ({resp.status_code}): {resp.text[:200]}")
    return resp


def check(url: str, token: str) -> bool:
    """True, wenn die HA-API mit dem Token erreichbar ist. Wirft nie."""
    try:
        return _request("GET", url, token, "/").ok
    except HAError:
        return False


def get_states(url: str, token: str) -> list:
    return _request("GET", url, token, "/states").json()


def get_state(url: str, token: str, entity_id: str) -> dict:
    return _request("GET", url, token, f"/states/{entity_id}").json()


def call_service(url: str, token: str, domain: str, service: str, data: dict) -> list:
    resp = _request("POST", url, token, f"/services/{domain}/{service}", json=data or {})
    try:
        return resp.json()
    except ValueError:
        return []


def list_automations(url: str, token: str) -> list:
    """Vorhandene HA-Automationen (aus /states gefiltert) - nur fuer den
    Prompt-Kontext ("was gibt es schon"), nicht sicherheitskritisch."""
    out = []
    for st in _request("GET", url, token, "/states").json():
        ent = st.get("entity_id", "")
        if ent.startswith("automation."):
            out.append({
                "entity_id": ent,
                "name": st.get("attributes", {}).get("friendly_name", ent),
                "state": st.get("state", ""),
            })
    return out


def create_automation(url: str, token: str, automation_id: str, body: dict) -> dict:
    """Legt/aktualisiert eine Automation ueber die HA-Config-API an. Setzt
    voraus, dass HA die (bei HA OS standardmaessig aktive) `config`-Integration
    hat und Automationen im UI-Modus fuehrt."""
    try:
        resp = _request(
            "POST", url, token, f"/config/automation/config/{automation_id}", json=body
        )
    except HAError as exc:
        if "404" in str(exc) or "405" in str(exc):
            raise HAError(
                "Die HA-Config-API ist nicht verfuegbar (config-Integration "
                "aktiv? Automationen im UI-Modus?). Das YAML kann stattdessen "
                "manuell in automations.yaml eingetragen werden."
            )
        raise
    try:
        return resp.json()
    except ValueError:
        return {}


def reload_automations(url: str, token: str) -> None:
    _request("POST", url, token, "/services/automation/reload", json={})


def create_scene(url: str, token: str, scene_id: str, body: dict) -> dict:
    """Persistente HA-Szene ueber die Config-API (wie create_automation).
    Setzt die aktive config-Integration voraus."""
    try:
        resp = _request(
            "POST", url, token, f"/config/scene/config/{scene_id}", json=body
        )
    except HAError as exc:
        if "404" in str(exc) or "405" in str(exc):
            raise HAError(
                "Die HA-Config-API ist nicht verfuegbar (config-Integration "
                "aktiv? Szenen im UI-Modus?)."
            )
        raise
    try:
        return resp.json()
    except ValueError:
        return {}


def reload_scenes(url: str, token: str) -> None:
    _request("POST", url, token, "/services/scene/reload", json={})


def get_logbook(url: str, token: str, hours: int = 24, entity=None) -> list:
    """HA-Logbook der letzten `hours` Stunden, optional auf eine Entity
    gefiltert. Nur lesend, fuer die Timeline-Ansicht."""
    from datetime import datetime, timedelta
    start = (datetime.utcnow() - timedelta(hours=max(1, hours))).strftime("%Y-%m-%dT%H:%M:%S")
    path = f"/logbook/{start}"
    if entity:
        path += f"?entity={entity}"
    try:
        return _request("GET", url, token, path).json()
    except HAError:
        return []


def get_history(url: str, token: str, entity_ids: list, hours: int = 24) -> dict:
    """Verlauf (Zustandswechsel) der letzten `hours` Stunden je entity_id, über
    den REST-Endpunkt /history/period. Rückgabe: {entity_id: [{"t": iso,
    "v": state}, ...]}. Fehlschlag -> leeres Dict (UI zeigt Leerzustand)."""
    from datetime import datetime, timedelta
    if not entity_ids:
        return {}
    start = (datetime.utcnow() - timedelta(hours=max(1, hours))).strftime("%Y-%m-%dT%H:%M:%S")
    filt = ",".join(entity_ids)
    path = f"/history/period/{start}?filter_entity_id={filt}&minimal_response&significant_changes_only"
    try:
        raw = _request("GET", url, token, path).json()
    except HAError:
        return {}
    out: dict = {}
    for series in raw or []:
        if not series:
            continue
        ent = series[0].get("entity_id")
        if not ent:
            continue
        out[ent] = [
            {"t": row.get("last_changed") or row.get("last_updated"), "v": row.get("state")}
            for row in series if row.get("state") not in (None, "unknown", "unavailable")
        ]
    return out


def area_map(url: str, token: str) -> dict:
    """Entity-ID -> Bereichsname, ueber den Template-Endpunkt (Area-Registry
    ist per REST sonst nicht zugaenglich). Fehlschlag ist unkritisch - dann
    eben ohne Bereichs-Info im Katalog."""
    template = (
        "{% set ns = namespace(rows=[]) %}"
        "{% for e in states | map(attribute='entity_id') %}"
        "{% set a = area_name(e) %}"
        "{% if a %}{% set ns.rows = ns.rows + [e ~ '|' ~ a] %}{% endif %}"
        "{% endfor %}{{ ns.rows | join('\\n') }}"
    )
    try:
        resp = _request("POST", url, token, "/template", json={"template": template})
    except HAError:
        return {}
    out = {}
    for line in resp.text.splitlines():
        if "|" in line:
            ent, area = line.split("|", 1)
            out[ent.strip()] = area.strip()
    return out
