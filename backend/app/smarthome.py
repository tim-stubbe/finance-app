"""Smart-Home-Assistent - Bruecke Home Assistant <-> Ollama.

Teil des "Life OS" (siehe CLAUDE.md), bewusst als eigenes Modul neben den
Finanz-Domaenen - keine Vermischung mit crud.py/Buchungslogik. Die einzige
KI ist die lokale Ollama-Instanz aus den Settings (kein Cloud-LLM).

Datenfluss (process_command):

    Text
     -> Schnellpfad: Alias/Anzeigename + Stichwort-Intent
        -> genau 1 Geraet + erlaubter Service  -> HA-Service direkt, fertig
        -> mehrere Kandidaten                  -> Rueckfrage
     -> sonst LLM-Pfad: gefilterter Geraete-Katalog an Ollama, JSON-Intent
        -> control  -> validieren, ggf. Rueckfrage/Bestaetigung, dann HA
        -> query    -> Auskunft aus den States (Antworttext vom Modell)
        -> chat     -> freie Antwort
        -> clarify  -> Rueckfrage

Prinzipien: schnelle Pfade ohne LLM wo moeglich; im Zweifel nachfragen
statt das falsche Licht schalten; jede Aktion wird protokolliert
(SmartHomeAction).

Live-Zustaende laufen ueber smarthome_ws.py (HA-WebSocket-Cache); _get_states
liest bevorzugt daraus. Voice (voice/), Grundriss (smarthome-floorplan.js) und
KI-Automationen (smarthome_automations.py) sind eigene Module.
"""

import json
import re
from datetime import datetime, timezone

from . import ha_client, ollama_client, smarthome_ws


def _get_states(settings):
    """Bevorzugt die per WebSocket live gehaltenen Zustaende (smarthome_ws),
    faellt auf REST zurueck, wenn der Cache nicht frisch ist."""
    cached = smarthome_ws.cached_states()
    if cached is not None:
        return cached
    return ha_client.get_states(settings.homeassistant_url, _token(settings))

# --------------------------------------------------------------------------
# Policy / Allowlist
# --------------------------------------------------------------------------

DEFAULT_ALLOWED_DOMAINS = [
    "light", "switch", "climate", "cover", "fan",
    "media_player", "scene", "script", "input_boolean",
]

# (domain, service)-Paare, die ohne weitere Freigabe erlaubt sind. Alles was
# hier NICHT steht, wird abgelehnt - kein "erlaube alles per Default".
DEFAULT_ALLOWED_SERVICES = {
    ("light", "turn_on"), ("light", "turn_off"), ("light", "toggle"),
    ("switch", "turn_on"), ("switch", "turn_off"), ("switch", "toggle"),
    ("input_boolean", "turn_on"), ("input_boolean", "turn_off"), ("input_boolean", "toggle"),
    ("fan", "turn_on"), ("fan", "turn_off"), ("fan", "toggle"),
    ("cover", "open_cover"), ("cover", "close_cover"), ("cover", "stop_cover"),
    ("climate", "set_temperature"), ("climate", "turn_on"), ("climate", "turn_off"),
    ("media_player", "media_play"), ("media_player", "media_pause"),
    ("media_player", "media_stop"), ("media_player", "volume_set"),
    ("media_player", "turn_on"), ("media_player", "turn_off"),
    ("scene", "turn_on"),
    ("script", "turn_on"),
}

# Nie erlaubt, auch nicht ueber die erweiterbare Allowlist - potenziell
# destruktiv / sicherheitsrelevant.
BLOCKED_SERVICES = {
    ("homeassistant", "stop"), ("homeassistant", "restart"),
    ("hassio", "host_reboot"), ("hassio", "host_shutdown"),
    ("lock", "unlock"), ("lock", "open"),
    ("alarm_control_panel", "alarm_disarm"),
}


def service_allowed(domain: str, service: str, extra_allowed=None) -> bool:
    if (domain, service) in BLOCKED_SERVICES:
        return False
    if (domain, service) in DEFAULT_ALLOWED_SERVICES:
        return True
    for entry in extra_allowed or []:
        if entry.strip() == f"{domain}.{service}":
            return True
    return False


# --------------------------------------------------------------------------
# Schnellpfad: Stichwort-Intent
# --------------------------------------------------------------------------

_ON_WORDS = ["an", "ein", "einschalten", "anschalten", "anmachen", "aktivier", "starte", "start"]
_OFF_WORDS = ["aus", "ausschalten", "abschalten", "ausmachen", "deaktivier", "stopp", "stop", "stoppe"]
_OPEN_WORDS = ["hoch", "auf", "oeffne", "öffne", "hochfahren"]
_CLOSE_WORDS = ["runter", "zu", "schliesse", "schließe", "runterfahren", "herunter"]


def _has_word(text: str, words) -> bool:
    return any(re.search(r"\b" + re.escape(w), text) for w in words)


def parse_fast_intent(text: str):
    """Erkennt simple, eindeutige Steuer-Absichten ohne LLM.

    Rueckgabe z.B. {"action": "turn_off"} oder
    {"action": "set_brightness", "value": 30} oder
    {"action": "set_temperature", "value": 21.5} - oder None, wenn unklar.
    """
    t = " " + text.lower().strip() + " "

    m = re.search(r"(\d{1,3})\s*(%|prozent)", t)
    if m and _has_word(t, ["dimm", "helligkeit", "auf "]):
        return {"action": "set_brightness", "value": max(0, min(100, int(m.group(1))))}

    m = re.search(r"(\d{1,2}(?:[.,]\d)?)\s*(grad|°)", t)
    if m and _has_word(t, ["temperatur", "heiz", "stell", "auf "]):
        return {"action": "set_temperature", "value": float(m.group(1).replace(",", "."))}

    # Rollladen/Cover-Richtung vor dem generischen an/aus pruefen
    if _has_word(t, _OPEN_WORDS) and _has_word(t, ["rollo", "rolllad", "rolllad", "jalousie", "vorhang", "cover"]):
        return {"action": "open_cover"}
    if _has_word(t, _CLOSE_WORDS) and _has_word(t, ["rollo", "rolllad", "rolllad", "jalousie", "vorhang", "cover"]):
        return {"action": "close_cover"}

    if _has_word(t, _OFF_WORDS):
        return {"action": "turn_off"}
    if _has_word(t, _ON_WORDS):
        return {"action": "turn_on"}
    return None


# Schnellpfad-Aktion -> (service, data-Builder) je nach Entity-Domain
def _fast_service_for(domain: str, intent: dict):
    action = intent["action"]
    if action == "set_brightness" and domain == "light":
        return "turn_on", {"brightness_pct": intent["value"]}
    if action == "set_temperature" and domain == "climate":
        return "set_temperature", {"temperature": intent["value"]}
    if action == "open_cover" and domain == "cover":
        return "open_cover", {}
    if action == "close_cover" and domain == "cover":
        return "close_cover", {}
    if action in ("turn_on", "turn_off"):
        if domain == "cover":
            return ("open_cover" if action == "turn_on" else "close_cover"), {}
        if domain in ("light", "switch", "fan", "input_boolean", "climate", "media_player", "scene", "script"):
            # scene/script kennen nur turn_on
            if domain in ("scene", "script") and action == "turn_off":
                return None
            return action, {}
    return None


# --------------------------------------------------------------------------
# Geraete-Auswahl (Alias + Anzeigename)
# --------------------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9äöüß ]", " ", (s or "").lower()).strip()


def match_aliases(text: str, aliases) -> list:
    """aliases: Iterable von {"phrase": ..., "entity_id": ...} (genau das, was
    crud.get_smarthome_aliases liefert - bewusst KEIN dict, damit derselbe
    Sprich-Name auf mehrere Geraete zeigen darf und das dann eine Rueckfrage
    ausloest statt still eines zu verschlucken).

    Trefferliste an entity_ids, laengster Alias zuerst gematcht (spezifischer
    gewinnt), Duplikate raus."""
    nt = _norm(text)
    hits = []
    for a in sorted(aliases, key=lambda a: -len(a.get("phrase", ""))):
        p = _norm(a.get("phrase", ""))
        if p and p in nt:
            hits.append(a["entity_id"])
    seen = set()
    return [e for e in hits if not (e in seen or seen.add(e))]


def match_by_friendly_name(text: str, states: list, allowed_domains) -> list:
    nt = _norm(text)
    hits = []
    for st in states:
        ent = st.get("entity_id", "")
        domain = ent.split(".")[0]
        if allowed_domains and domain not in allowed_domains:
            continue
        fn = _norm(st.get("attributes", {}).get("friendly_name", ""))
        if fn and len(fn) >= 3 and fn in nt:
            hits.append(ent)
    return hits


# --------------------------------------------------------------------------
# LLM-Pfad
# --------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "Du bist ein deutschsprachiger Haus-Assistent fuer Home Assistant. "
    "Du erfindest KEINE entity_ids - du nutzt ausschliesslich Geraete aus der "
    "bereitgestellten Liste. Bei Unsicherheit (mehrere moegliche Geraete, "
    "unklarer Wunsch) fragst du nach, statt zu raten.\n\n"
    "Antworte AUSSCHLIESSLICH mit einem JSON-Objekt in genau dieser Form:\n"
    "{\n"
    '  "intent": "control" | "query" | "chat" | "clarify",\n'
    '  "domain": "light|switch|climate|cover|fan|media_player|scene|script|input_boolean|null",\n'
    '  "service": "z.B. turn_on, turn_off, set_temperature oder null",\n'
    '  "entity_id": "exakte entity_id aus der Liste oder null",\n'
    '  "data": {},\n'
    '  "reply": "kurze natuerliche Antwort auf Deutsch"\n'
    "}\n\n"
    "intent=control: Geraet schalten. intent=query: Frage zum Zustand "
    "(beantworte sie in 'reply' aus der Geraeteliste). intent=chat: allgemeine "
    "Antwort. intent=clarify: Rueckfrage in 'reply'."
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_lenient(text: str) -> dict:
    if not text or not text.strip():
        raise ValueError("leere Antwort")
    cands = [text.strip()]
    m = _FENCE_RE.search(text)
    if m:
        cands.append(m.group(1).strip())
    s = text.strip()
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j > i:
        cands.append(s[i:j + 1])
    for c in cands:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except (ValueError, TypeError):
            continue
    raise ValueError("kein verwertbares JSON: " + s[:150])


def build_catalog(states: list, areas: dict, allowed_domains, allowed_areas, limit: int = 80):
    """Kompakter Geraete-Katalog fuer den Prompt. Nur relevante Domains,
    optional nur bestimmte Bereiche, hart begrenzt - nicht 2000 States ins
    Prompt. Rueckgabe: (text, set_of_entity_ids)."""
    lines, ids = [], set()
    for st in states:
        ent = st.get("entity_id", "")
        domain = ent.split(".")[0]
        if allowed_domains and domain not in allowed_domains:
            continue
        area = areas.get(ent, "")
        if allowed_areas and area not in allowed_areas:
            continue
        fn = st.get("attributes", {}).get("friendly_name", ent)
        state = st.get("state", "")
        area_part = f" | Bereich: {area}" if area else ""
        lines.append(f'- {ent} | "{fn}"{area_part} | Status: {state}')
        ids.add(ent)
        if len(lines) >= limit:
            break
    return "\n".join(lines), ids


# --------------------------------------------------------------------------
# Orchestrierung
# --------------------------------------------------------------------------

# Single-User-System (siehe CLAUDE.md) - eine offene Rueckfrage genuegt,
# kein Sitzungs-/Nutzer-Schluessel noetig.
_LAST_PENDING: dict = {"action": None}

_CONFIRM_WORDS = {"ja", "ja bitte", "jap", "jo", "ok", "okay", "mach", "machs",
                  "mach es", "bestaetige", "bestaetigen", "bestätige", "bestätigen"}
_CANCEL_WORDS = {"nein", "nee", "abbrechen", "stopp", "lass", "doch nicht"}


def _entity_domain(entity_id: str) -> str:
    return (entity_id or "").split(".")[0]


def _friendly(states: list, entity_id: str) -> str:
    for st in states:
        if st.get("entity_id") == entity_id:
            return st.get("attributes", {}).get("friendly_name", entity_id)
    return entity_id


def _result(ok, reply, intent="chat", actions=None, needs_confirmation=False, candidates=None):
    return {
        "ok": ok,
        "reply": reply,
        "intent": intent,
        "actions": actions or [],
        "needs_confirmation": needs_confirmation,
        "candidates": candidates or [],
    }


def _execute(db, settings, domain, service, entity_id, data, source, spoken_text):
    """Fuehrt einen HA-Service aus (oder simuliert bei dry_run), protokolliert
    und liefert das actions[]-Element zurueck."""
    dry = bool(getattr(settings, "homeassistant_dry_run", False))
    payload = dict(data or {})
    if entity_id:
        payload["entity_id"] = entity_id
    action = {"domain": domain, "service": service, "entity_id": entity_id,
              "data": data or {}, "ok": True, "error": None, "dry_run": dry}
    try:
        if not dry:
            ha_client.call_service(
                settings.homeassistant_url,
                _token(settings),
                domain, service, payload,
            )
    except ha_client.HAError as exc:
        action["ok"] = False
        action["error"] = str(exc)

    from . import crud
    crud.log_smarthome_action(
        db,
        text=spoken_text,
        intent="control",
        domain=domain,
        service=service,
        entity_id=entity_id,
        data=data or {},
        ok=action["ok"],
        error=action["error"],
        source=source,
    )
    return action


def _token(settings) -> str:
    """HA-Token entschluesseln (verschluesselt gespeichert wie alle Secrets)."""
    enc = getattr(settings, "homeassistant_token_encrypted", None)
    if not enc:
        return ""
    from . import bank_sync
    try:
        return bank_sync.decrypt_secret(settings.secret_key, enc)
    except Exception:  # noqa: BLE001 - defekter/alter Token -> wie "kein Token"
        return ""


def _allowed_domains(settings):
    raw = getattr(settings, "homeassistant_allowed_domains", None)
    if raw:
        return [d.strip() for d in raw.split(",") if d.strip()]
    return DEFAULT_ALLOWED_DOMAINS


def _allowed_areas(settings):
    raw = getattr(settings, "homeassistant_allowed_areas", None)
    if raw:
        return [a.strip() for a in raw.split(",") if a.strip()]
    return []


def _extra_services(settings):
    raw = getattr(settings, "homeassistant_extra_services", None)
    return [s.strip() for s in (raw or "").split(",") if s.strip()]


def health(settings) -> dict:
    url, token = settings.homeassistant_url, _token(settings)
    ha_ok = ha_client.check(url, token) if url and token else False
    ollama_ok = False
    if settings.ollama_url:
        try:
            ollama_client.list_models(settings.ollama_url)
            ollama_ok = True
        except Exception:  # noqa: BLE001
            ollama_ok = False
    return {
        "ha_configured": bool(url and token),
        "ha_connected": ha_ok,
        "ollama_configured": bool(settings.ollama_url and settings.ollama_model),
        "ollama_connected": ollama_ok,
        "ollama_model": settings.ollama_model,
        "dry_run": bool(getattr(settings, "homeassistant_dry_run", False)),
    }


def list_devices(settings, include_all: bool = False) -> list:
    """Geraeteliste fuer die UI.

    Standard: nur steuerbare Domains (``_allowed_domains``) und ggf. der
    Bereichs-Filter. Mit ``include_all`` kommt JEDE Entity aus Home Assistant
    zurueck (auch Sensoren, ``binary_sensor``, ``device_tracker`` usw.) -
    ``controllable`` markiert dann, welche Kies tatsaechlich schalten darf.
    Das Schalten selbst bleibt unabhaengig davon durch ``service_allowed``
    abgesichert.
    """
    states = _get_states(settings)
    areas = ha_client.area_map(settings.homeassistant_url, _token(settings))
    allowed = _allowed_domains(settings)
    areas_filter = _allowed_areas(settings)
    out = []
    for st in states:
        ent = st.get("entity_id", "")
        domain = _entity_domain(ent)
        controllable = domain in allowed
        area = areas.get(ent, "")
        if not include_all:
            if not controllable:
                continue
            if areas_filter and area not in areas_filter:
                continue
        attrs = st.get("attributes", {})
        out.append({
            "entity_id": ent,
            "domain": domain,
            "name": attrs.get("friendly_name", ent),
            "area": area or None,
            "state": st.get("state", ""),
            "controllable": controllable,
            "toggleable": domain in ("light", "switch", "fan", "input_boolean"),
        })
    out.sort(key=lambda d: (d["area"] or "zzz", d["name"].lower()))
    return out


def autolayout(settings) -> dict:
    """Erzeugt aus den HA-Bereichen (Areas) automatisch einen Grundriss:
    ein Raum je Bereich in einem Raster, die Geraete des Bereichs darin
    verteilt. Grobe Startaufteilung, die der Nutzer dann verschiebt."""
    token = _token(settings)
    states = _get_states(settings)
    try:
        areas = ha_client.area_map(settings.homeassistant_url, token)
    except ha_client.HAError:
        areas = {}
    allowed = _allowed_domains(settings)
    areas_filter = _allowed_areas(settings)

    by_area = {}
    for st in states:
        ent = st.get("entity_id", "")
        if _entity_domain(ent) not in allowed:
            continue
        area = areas.get(ent) or "Ohne Bereich"
        if areas_filter and area not in areas_filter and area != "Ohne Bereich":
            continue
        by_area.setdefault(area, []).append(ent)

    names = sorted(by_area)
    cols = max(1, int(len(names) ** 0.5 + 0.999)) if names else 1
    rw, rh, gap = 4.0, 3.2, 0.6
    rooms, devices = [], []
    for i, name in enumerate(names):
        ox, oy = (i % cols) * (rw + gap), (i // cols) * (rh + gap)
        rid = f"r{i}"
        rooms.append({"id": rid, "name": name, "x": round(ox, 1), "y": round(oy, 1),
                      "w": rw, "h": rh, "area": name})
        ents = by_area[name]
        dcols = max(1, int(len(ents) ** 0.5 + 0.999))
        drows = (len(ents) + dcols - 1) // dcols
        for j, ent in enumerate(ents):
            gx = (j % dcols) / (dcols - 1) if dcols > 1 else 0.5
            gy = (j // dcols) / (drows - 1) if drows > 1 else 0.5
            devices.append({
                "entity_id": ent, "room_id": rid,
                "x": round(ox + 0.6 + gx * (rw - 1.2), 1),
                "y": round(oy + 0.6 + gy * (rh - 1.2), 1),
            })
    return {"rooms": rooms, "devices": devices}


_SCENE_ATTRS = {
    "light": ("brightness", "color_temp", "rgb_color", "hs_color", "effect"),
    "climate": ("temperature", "hvac_mode"),
    "cover": ("current_position",),
    "media_player": ("volume_level",),
    "fan": ("percentage",),
}


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower().strip()).strip("_")
    return s or "szene"


def list_scenes(settings) -> list:
    out = []
    for st in _get_states(settings):
        if st.get("entity_id", "").startswith("scene."):
            attrs = st.get("attributes", {})
            out.append({
                "entity_id": st["entity_id"],
                "name": attrs.get("friendly_name", st["entity_id"]),
                "entities": attrs.get("entity_id", []),
            })
    out.sort(key=lambda s: s["name"].lower())
    return out


def _to_watt(value, unit) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v * 1000 if (unit or "").lower().startswith("kw") else v


def _ha_dt(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def morning_notes(settings, long_on_hours: int = 6) -> list:
    """Kurze Auffaelligkeiten fuers Morgen-Briefing (Rollladen offen, Heizung
    an, Licht seit Stunden an, Fenster/Tuer offen). Leer, wenn HA nicht
    eingerichtet oder nichts Auffaelliges."""
    if not (settings.homeassistant_url and _token(settings)):
        return []
    try:
        states = _get_states(settings)
    except ha_client.HAError:
        return []
    now = datetime.utcnow()
    covers, climate, lights, contacts = [], [], [], []
    for st in states:
        ent = st.get("entity_id", "")
        dom = _entity_domain(ent)
        state = st.get("state")
        attrs = st.get("attributes", {})
        fn = attrs.get("friendly_name", ent)
        if dom == "cover" and state == "open":
            covers.append(fn)
        elif dom == "climate" and state not in (None, "off", "unavailable", "unknown"):
            t = attrs.get("temperature")
            climate.append(f"{fn} ({t}°)" if t is not None else fn)
        elif dom == "light" and state == "on":
            lc = _ha_dt(st.get("last_changed"))
            if lc and (now - lc).total_seconds() > long_on_hours * 3600:
                lights.append(fn)
        elif dom == "binary_sensor" and state == "on" and attrs.get("device_class") in ("door", "window", "opening"):
            contacts.append(fn)
    notes = []
    if covers:
        notes.append("🪟 Rollläden offen: " + ", ".join(covers[:6]))
    if climate:
        notes.append("🌡️ Heizung/Klima an: " + ", ".join(climate[:6]))
    if lights:
        notes.append(f"💡 Licht seit >{long_on_hours} h an: " + ", ".join(lights[:6]))
    if contacts:
        notes.append("🚪 Offen: " + ", ".join(contacts[:6]))
    return notes


def energy_summary(settings) -> dict:
    """Strom-Sensoren aus HA + grobe Kostenschaetzung.

    power-Sensoren = aktuelle Leistung (W); die Summe hochgerechnet auf 24 h
    mal Strompreis ergibt die (sehr grobe) Tageskosten-Schaetzung beim
    aktuellen Verbrauch. energy-Sensoren (kWh) werden nur aufgelistet.
    """
    price = float(getattr(settings, "homeassistant_electricity_price", 0.35) or 0.35)
    power, energy, total_w = [], [], 0.0
    for st in _get_states(settings):
        ent = st.get("entity_id", "")
        if not ent.startswith("sensor."):
            continue
        attrs = st.get("attributes", {})
        dc = (attrs.get("device_class") or "").lower()
        unit = (attrs.get("unit_of_measurement") or "")
        name = attrs.get("friendly_name", ent)
        if dc == "power" or unit.lower() in ("w", "kw"):
            w = _to_watt(st.get("state"), unit)
            total_w += w
            power.append({"entity_id": ent, "name": name, "watt": round(w, 1)})
        elif dc == "energy" or unit.lower() in ("wh", "kwh"):
            try:
                kwh = float(st.get("state"))
                if unit.lower() == "wh":
                    kwh /= 1000
            except (TypeError, ValueError):
                kwh = None
            energy.append({"entity_id": ent, "name": name, "kwh": round(kwh, 2) if kwh is not None else None})
    power.sort(key=lambda p: -p["watt"])
    energy.sort(key=lambda e: e["name"].lower())
    daily = total_w / 1000 * 24 * price
    return {
        "price_per_kwh": price,
        "total_power_w": round(total_w, 1),
        "est_daily_cost": round(daily, 2),
        "est_monthly_cost": round(daily * 30, 2),
        "power_sensors": power[:40],
        "energy_sensors": energy[:40],
    }


def list_automations_status(settings) -> list:
    """Alle HA-Automationen mit an/aus, letzter Ausloesung und Laufzustand -
    fuer das Automations-Dashboard."""
    out = []
    for st in _get_states(settings):
        if not st.get("entity_id", "").startswith("automation."):
            continue
        attrs = st.get("attributes", {})
        out.append({
            "entity_id": st["entity_id"],
            "name": attrs.get("friendly_name", st["entity_id"]),
            "enabled": st.get("state") == "on",
            "last_triggered": attrs.get("last_triggered"),
            "running": int(attrs.get("current", 0) or 0),
        })
    out.sort(key=lambda a: a["name"].lower())
    return out


def automation_logbook(settings, hours: int = 24) -> list:
    entries = ha_client.get_logbook(settings.homeassistant_url, _token(settings), hours=hours)
    rows = []
    for e in entries:
        ent = e.get("entity_id") or ""
        if ent.startswith("automation.") or e.get("domain") == "automation":
            rows.append({
                "when": e.get("when"),
                "name": e.get("name") or ent,
                "message": e.get("message") or "",
                "entity_id": ent,
            })
    return rows[:100]


def create_scene_from_current(settings, name: str, entity_ids: list) -> dict:
    """Nimmt die AKTUELLEN Zustaende der gewaehlten Geraete als Szene auf
    (Idee: Raum wie gewuenscht einstellen, dann speichern) und legt sie
    persistent in HA an."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Bitte einen Namen fuer die Szene angeben.")
    if not entity_ids:
        raise ValueError("Keine Geraete ausgewaehlt.")
    states = {s["entity_id"]: s for s in _get_states(settings)}
    entities = {}
    for eid in entity_ids:
        st = states.get(eid)
        if not st:
            continue
        dom = _entity_domain(eid)
        entry = {"state": st.get("state")}
        for a in _SCENE_ATTRS.get(dom, ()):
            v = st.get("attributes", {}).get(a)
            if v is not None:
                entry[a] = v
        entities[eid] = entry
    if not entities:
        raise ValueError("Die ausgewaehlten Geraete sind gerade nicht bekannt.")
    scene_id = f"kies_{_slugify(name)}"
    token = _token(settings)
    ha_client.create_scene(settings.homeassistant_url, token, scene_id,
                           {"name": name, "entities": entities})
    ha_client.reload_scenes(settings.homeassistant_url, token)
    return {"entity_id": f"scene.{scene_id}", "name": name, "entities": list(entities)}


def process_command(db, settings, text: str, confirm: bool = False, source: str = "text") -> dict:
    """Kernpipeline. Wirft nie - Fehler kommen als {"ok": False, "reply": ...}."""
    text = (text or "").strip()
    if not text:
        return _result(False, "Ich habe keinen Befehl verstanden.")

    low = text.lower().strip(" .!?")

    # Bestaetigung/Abbruch einer offenen Rueckfrage
    if _LAST_PENDING["action"] and (confirm or low in _CONFIRM_WORDS):
        pend = _LAST_PENDING["action"]
        _LAST_PENDING["action"] = None
        act = _execute(db, settings, pend["domain"], pend["service"],
                       pend["entity_id"], pend["data"], source, pend["text"])
        ok = act["ok"]
        return _result(ok, pend["reply_ok"] if ok else f"Hat nicht geklappt: {act['error']}",
                       intent="control", actions=[act])
    if _LAST_PENDING["action"] and low in _CANCEL_WORDS:
        _LAST_PENDING["action"] = None
        return _result(True, "Ok, ich lasse es.", intent="clarify")

    if not settings.homeassistant_url or not _token(settings):
        return _result(False, "Smart Home ist nicht eingerichtet (URL/Token in den Einstellungen fehlen).")

    # --- States / Bereiche einmal laden (fuer beide Pfade) ---
    try:
        states = _get_states(settings)
    except ha_client.HAError as exc:
        return _result(False, str(exc))
    try:
        areas = ha_client.area_map(settings.homeassistant_url, _token(settings))
    except ha_client.HAError:
        areas = {}

    allowed_domains = _allowed_domains(settings)
    extra = _extra_services(settings)

    # --- Schnellpfad ---
    matched = (match_aliases(text, _load_aliases(db))
               or match_by_friendly_name(text, states, allowed_domains))
    fast = parse_fast_intent(text)

    if matched and fast:
        if len(matched) > 1:
            names = [f"{_friendly(states, e)} ({e})" for e in matched[:6]]
            return _result(True, "Welches Geraet meinst du? " + ", ".join(names),
                           intent="clarify", needs_confirmation=True, candidates=matched)
        entity_id = matched[0]
        domain = _entity_domain(entity_id)
        sd = _fast_service_for(domain, fast)
        if sd:
            service, data = sd
            if not service_allowed(domain, service, extra):
                return _result(False, f"Die Aktion {domain}.{service} ist nicht freigegeben.")
            act = _execute(db, settings, domain, service, entity_id, data, source, text)
            if act["ok"]:
                return _result(True, f"Erledigt: {_friendly(states, entity_id)} {_verb(service)}.",
                               intent="control", actions=[act])
            return _result(False, f"Hat nicht geklappt: {act['error']}", intent="control", actions=[act])

    # --- LLM-Pfad ---
    if not settings.ollama_url or not settings.ollama_model:
        return _result(False, "Fuer freie Befehle fehlt ein Ollama-Modell (Einstellungen -> KI-Assistent).")

    catalog, valid_ids = build_catalog(states, areas, allowed_domains, _allowed_areas(settings))
    user_msg = f"Verfuegbare Geraete:\n{catalog}\n\nBefehl des Nutzers: {text}"
    try:
        raw = ollama_client.chat(
            settings.ollama_url, settings.ollama_model,
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user", "content": user_msg}],
            timeout=120,
        )
    except Exception as exc:  # noqa: BLE001 - requests.HTTPError/ValueError/Timeout
        return _result(False, f"Die lokale KI (Ollama) ist gerade nicht ansprechbar: {exc}")

    try:
        parsed = parse_json_lenient(raw)
    except ValueError:
        # Modell hat nicht sauber geantwortet - roher Text als Chat-Antwort
        return _result(True, raw.strip()[:500] or "Ich bin mir nicht sicher.", intent="chat")

    intent = (parsed.get("intent") or "chat").lower()
    reply = (parsed.get("reply") or "").strip()

    if intent == "control":
        entity_id = parsed.get("entity_id")
        domain = parsed.get("domain") or _entity_domain(entity_id or "")
        service = parsed.get("service") or ""
        data = parsed.get("data") or {}
        if not entity_id or entity_id not in valid_ids:
            return _result(True, reply or "Ich bin mir nicht sicher, welches Geraet gemeint ist. Kannst du es genauer sagen?",
                           intent="clarify")
        if not service_allowed(domain, service, extra):
            return _result(False, f"Die Aktion {domain}.{service} ist nicht freigegeben.")
        nice = _friendly(states, entity_id)
        require_confirm = bool(getattr(settings, "homeassistant_require_confirmation", True))
        if require_confirm and not confirm:
            _LAST_PENDING["action"] = {
                "domain": domain, "service": service, "entity_id": entity_id,
                "data": data, "text": text,
                "reply_ok": f"Erledigt: {nice} {_verb(service)}.",
            }
            return _result(True, f"Soll ich {nice} {_verb(service)}? Sag 'ja' zum Bestaetigen.",
                           intent="control", needs_confirmation=True,
                           candidates=[entity_id])
        act = _execute(db, settings, domain, service, entity_id, data, source, text)
        if act["ok"]:
            return _result(True, reply or f"Erledigt: {nice} {_verb(service)}.",
                           intent="control", actions=[act])
        return _result(False, f"Hat nicht geklappt: {act['error']}", intent="control", actions=[act])

    if intent in ("query", "chat", "clarify"):
        from . import crud
        crud.log_smarthome_action(db, text=text, intent=intent, domain=None, service=None,
                                  entity_id=None, data={}, ok=True, error=None, source=source)
        return _result(True, reply or "Ok.", intent=intent)

    return _result(True, reply or "Ok.", intent="chat")


_VERBS = {
    "turn_on": "eingeschaltet", "turn_off": "ausgeschaltet", "toggle": "umgeschaltet",
    "open_cover": "hochgefahren", "close_cover": "heruntergefahren", "stop_cover": "gestoppt",
    "set_temperature": "auf die gewuenschte Temperatur gestellt",
    "media_play": "gestartet", "media_pause": "pausiert", "media_stop": "gestoppt",
    "volume_set": "in der Lautstaerke angepasst",
}


def _verb(service: str) -> str:
    return _VERBS.get(service, f"({service})")


def _load_aliases(db):
    from . import crud
    return crud.get_smarthome_aliases(db)
