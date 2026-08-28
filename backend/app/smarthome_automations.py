"""KI-Automationen: die lokale KI schlaegt Ablaeufe/Workflows vor UND schreibt
die Home-Assistant-Automation dazu (YAML).

Sicherheitsgrundsatz: nichts wird automatisch scharf geschaltet. Die KI
erzeugt nur einen Entwurf, der Nutzer sieht das YAML, kann es bearbeiten und
legt es explizit an. Vor dem echten Anlegen laeuft dieselbe Service-Allowlist
wie bei der direkten Steuerung (smarthome.service_allowed).

Teil des Smart-Home-Moduls (siehe smarthome.py). Einzige KI: Ollama.
"""

import json
import re
import time

import yaml

from . import ha_client, ollama_client, smarthome, models

SUGGEST_SYSTEM = (
    "Du bist Experte fuer Home-Assistant-Automationen und schlaegst konkrete, "
    "nuetzliche Ablaeufe fuer den gegebenen Haushalt vor. Nutze AUSSCHLIESSLICH "
    "die bereitgestellten entity_ids, erfinde keine. Antworte NUR mit JSON:\n"
    '{"ideas": [{"title": "kurz", "description": "1-2 Saetze", '
    '"trigger": "Ausloeser in Worten", "entities": ["entity_id", ...]}]}'
)

YAML_SYSTEM = (
    "Du schreibst GENAU EINE Home-Assistant-Automation als YAML. Nutze nur die "
    "bereitgestellten entity_ids und uebliche HA-Services (z.B. light.turn_on, "
    "cover.close_cover). Struktur: 'alias', 'trigger', optional 'condition', "
    "'action', 'mode'. Antworte NUR mit dem YAML - keine Erklaerung, keine "
    "Markdown-Codebloecke."
)

_FENCE_RE = re.compile(r"```(?:ya?ml|json)?\s*(.*?)```", re.DOTALL)


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.search(text or "")
    return (m.group(1) if m else (text or "")).strip()


def _catalog(settings):
    token = smarthome._token(settings)
    states = ha_client.get_states(settings.homeassistant_url, token)
    areas = ha_client.area_map(settings.homeassistant_url, token)
    text, ids = smarthome.build_catalog(
        states, areas, smarthome._allowed_domains(settings),
        smarthome._allowed_areas(settings), limit=120,
    )
    return text, ids


def _out(row: models.SmartHomeAutomationDraft) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "description": row.description,
        "spec": json.loads(row.spec_json) if row.spec_json else None,
        "yaml": row.yaml_text,
        "warnings": json.loads(row.warnings_json) if row.warnings_json else [],
        "status": row.status,
        "ha_entity_id": row.ha_entity_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _require_ollama(settings):
    if not settings.ollama_url or not settings.ollama_model:
        raise ValueError("Kein Ollama-Modell eingerichtet (Einstellungen -> KI-Assistent).")


# --------------------------------------------------------------------------
# 1) Vorschlaege
# --------------------------------------------------------------------------
def suggest(db, settings, n: int = 5) -> list:
    _require_ollama(settings)
    cat, _ids = _catalog(settings)

    from . import crud
    hist = crud.get_smarthome_actions(db, limit=20)
    hist_txt = "\n".join(f"- {h['text']} ({h['intent']})" for h in hist if h.get("text")) or "(keine)"
    try:
        existing = ha_client.list_automations(settings.homeassistant_url, smarthome._token(settings))
        exist_txt = "\n".join(f"- {a['name']}" for a in existing) or "(keine)"
    except ha_client.HAError:
        exist_txt = "(unbekannt)"

    user = (
        f"Geraete:\n{cat}\n\nVorhandene Automationen:\n{exist_txt}\n\n"
        f"Zuletzt genutzte Sprachbefehle:\n{hist_txt}\n\n"
        f"Schlage bis zu {n} sinnvolle, noch fehlende Ablaeufe vor."
    )
    raw = ollama_client.chat(
        settings.ollama_url, settings.ollama_model,
        [{"role": "system", "content": SUGGEST_SYSTEM},
         {"role": "user", "content": user}],
        timeout=180,
    )
    try:
        parsed = json.loads(_strip_fences(raw))
        ideas = parsed.get("ideas") if isinstance(parsed, dict) else parsed
    except (ValueError, TypeError):
        ideas = []

    known = {d.title.strip().lower()
             for d in db.query(models.SmartHomeAutomationDraft).all()}
    created = []
    for idea in (ideas or [])[:n]:
        if not isinstance(idea, dict):
            continue
        title = (idea.get("title") or "").strip()
        if not title or title.lower() in known:
            continue
        row = models.SmartHomeAutomationDraft(
            title=title[:200],
            description=(idea.get("description") or "").strip(),
            spec_json=json.dumps(
                {"trigger": idea.get("trigger", ""), "entities": idea.get("entities", [])},
                ensure_ascii=False,
            ),
            status="vorschlag",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        known.add(title.lower())
        created.append(_out(row))
    return created


# --------------------------------------------------------------------------
# 2) YAML entwerfen
# --------------------------------------------------------------------------
def _walk(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(obj, list):
        for it in obj:
            yield from _walk(it)


def validate_yaml(yaml_text: str, known_ids, settings) -> list:
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return [f"YAML ist nicht parsebar: {exc}"]
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return ["YAML ergibt keine Automation (kein Objekt)."]

    warnings = []
    if "trigger" not in data and "triggers" not in data:
        warnings.append("Kein 'trigger' definiert.")
    if "action" not in data and "actions" not in data:
        warnings.append("Kein 'action' definiert.")

    refs, services = set(), set()
    for k, v in _walk(data):
        if k in ("entity_id", "entity_ids"):
            if isinstance(v, str):
                refs.add(v)
            elif isinstance(v, list):
                refs.update(x for x in v if isinstance(x, str))
        if k in ("service", "action") and isinstance(v, str) and "." in v and " " not in v:
            services.add(v)

    unknown = sorted(r for r in refs if known_ids and r not in known_ids)
    if unknown:
        warnings.append("Unbekannte entity_ids: " + ", ".join(unknown))

    extra = smarthome._extra_services(settings)
    bad = sorted(s for s in services
                 if not smarthome.service_allowed(s.split(".")[0], s.split(".", 1)[1], extra))
    if bad:
        warnings.append("Nicht freigegebene Services: " + ", ".join(bad))
    return warnings


def draft_yaml(db, settings, draft_id=None, freeform=None) -> dict:
    _require_ollama(settings)
    cat, ids = _catalog(settings)

    if draft_id:
        row = db.query(models.SmartHomeAutomationDraft).filter_by(id=draft_id).first()
        if not row:
            raise ValueError("Vorschlag nicht gefunden.")
        spec = json.loads(row.spec_json or "{}")
        idea = (f"Titel: {row.title}\nBeschreibung: {row.description}\n"
                f"Ausloeser: {spec.get('trigger', '')}\n"
                f"Geraete: {', '.join(spec.get('entities', []))}")
    else:
        text = (freeform or "").strip()
        if not text:
            raise ValueError("Bitte einen Wunsch beschreiben.")
        row = models.SmartHomeAutomationDraft(
            title=text[:80], description=text, status="vorschlag",
            spec_json=json.dumps({"trigger": text, "entities": []}, ensure_ascii=False),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        idea = f"Wunsch des Nutzers: {text}"

    raw = ollama_client.chat(
        settings.ollama_url, settings.ollama_model,
        [{"role": "system", "content": YAML_SYSTEM},
         {"role": "user", "content": f"Verfuegbare Geraete:\n{cat}\n\n{idea}\n\nSchreibe die Automation als YAML."}],
        timeout=240,
    )
    yaml_text = _strip_fences(raw)
    row.yaml_text = yaml_text
    row.warnings_json = json.dumps(validate_yaml(yaml_text, ids, settings), ensure_ascii=False)
    row.status = "entwurf"
    db.commit()
    db.refresh(row)
    return _out(row)


def save_yaml(db, settings, draft_id, yaml_text) -> dict:
    row = db.query(models.SmartHomeAutomationDraft).filter_by(id=draft_id).first()
    if not row:
        raise ValueError("Entwurf nicht gefunden.")
    _cat, ids = _catalog(settings)
    row.yaml_text = yaml_text
    row.warnings_json = json.dumps(validate_yaml(yaml_text, ids, settings), ensure_ascii=False)
    if row.status == "vorschlag":
        row.status = "entwurf"
    db.commit()
    db.refresh(row)
    return _out(row)


# --------------------------------------------------------------------------
# 3) In Home Assistant anlegen
# --------------------------------------------------------------------------
def apply(db, settings, draft_id) -> dict:
    row = db.query(models.SmartHomeAutomationDraft).filter_by(id=draft_id).first()
    if not row or not row.yaml_text:
        raise ValueError("Kein Entwurf mit YAML vorhanden.")
    try:
        data = yaml.safe_load(row.yaml_text)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML nicht parsebar: {exc}")
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        raise ValueError("YAML ergibt keine Automation.")

    _cat, ids = _catalog(settings)
    blockers = [w for w in validate_yaml(row.yaml_text, ids, settings)
                if w.startswith("Nicht freigegebene Services")]
    if blockers:
        raise ValueError(blockers[0] + " - anpassen oder Service in den Smart-Home-Einstellungen freigeben.")

    aid = (row.ha_entity_id.split(".", 1)[1] if row.ha_entity_id
           else f"kies_{row.id}_{int(time.time())}")
    data.setdefault("alias", row.title)
    token = smarthome._token(settings)
    ha_client.create_automation(settings.homeassistant_url, token, aid, data)
    ha_client.reload_automations(settings.homeassistant_url, token)

    row.ha_entity_id = f"automation.{aid}"
    row.status = "angelegt"
    db.commit()
    db.refresh(row)

    from . import crud
    crud.log_smarthome_action(db, text=f"Automation angelegt: {row.title}",
                              intent="automation", domain="automation", service="config",
                              entity_id=row.ha_entity_id, data={}, ok=True, error=None,
                              source="automation")
    return _out(row)
