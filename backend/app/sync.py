"""Pull/Push-Endpunkte für den Offline-Sync des nativen macOS-Clients.

Kein Session-Cookie/Login (die App ist bewusst Single-User ohne Auth-System) -
stattdessen ein geteiltes Secret im Header, exakt das gleiche Muster wie beim
n8n-Webhook (siehe main.py: get_webhook_settings/regenerate_webhook_secret,
POST /api/webhook/business-issue). space_id kommt hier aus Query/Body statt
aus der Session, weil ein nativer Client keinen Browser-Cookie hat.

Konfliktauflösung: Last-Write-Wins über updated_at. Vertretbar, weil die App
Single-User/faktisch Single-Space ist - echte Zeitgleich-Konflikte sind
selten. Der Client bekommt verlorene Konflikte trotzdem sichtbar zurück
(conflicts[]) statt sie stillschweigend zu verwerfen."""

import enum
import secrets as secrets_module
from datetime import date, datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import auth, bank_sync, models
from .database import get_db
from .sync_registry import SYNC_REGISTRY

sync_router = APIRouter(prefix="/api/sync")


def _json_safe(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def _serialize_row(obj) -> dict:
    """Serialisiert eine ORM-Zeile über ihre reinen Tabellenspalten - bewusst
    NICHT über die schemas.*Out-Klassen, siehe sync_registry.py-Docstring."""
    return {
        col.name: _json_safe(getattr(obj, col.name))
        for col in obj.__table__.columns
    }


def _verify_secret(db: Session, x_sync_secret: Optional[str]):
    s = auth.get_or_create_settings(db)
    if not s.native_sync_secret_encrypted:
        raise HTTPException(403, "Nativer Sync ist noch nicht eingerichtet (Einstellungen → Weitere Verbindungen).")
    expected = bank_sync.decrypt_secret(s.secret_key, s.native_sync_secret_encrypted)
    if not x_sync_secret or not secrets_module.compare_digest(x_sync_secret, expected):
        raise HTTPException(403, "Ungültiges Secret.")


class SyncOp(BaseModel):
    op: Literal["create", "update", "delete"]
    entity_type: str
    client_id: Optional[str] = None
    server_id: Optional[int] = None
    base_updated_at: Optional[str] = None
    data: dict[str, Any] = {}


class SyncPushRequest(BaseModel):
    space_id: Optional[int] = None
    ops: list[SyncOp]


@sync_router.get("/pull")
def pull(
    since: Optional[str] = None, db: Session = Depends(get_db),
    x_sync_secret: Optional[str] = Header(None),
):
    _verify_secret(db, x_sync_secret)
    since_dt = datetime.fromisoformat(since) if since else datetime(1970, 1, 1)
    # VOR den Queries erfasst, nicht danach - sonst koennte eine zwischen
    # Cursor-Erfassung und Query-Ausfuehrung committete Aenderung beim
    # naechsten Pull mit diesem Cursor verschluckt werden.
    server_time = datetime.utcnow()

    entities: dict[str, list[dict]] = {}
    for name, entity in SYNC_REGISTRY.items():
        rows = (
            db.query(entity.model)
            .filter(entity.model.updated_at > since_dt)
            .all()
        )
        entities[name] = [_serialize_row(r) for r in rows]

    tombstones = (
        db.query(models.SyncTombstone)
        .filter(models.SyncTombstone.deleted_at > since_dt)
        .all()
    )

    return {
        "server_time": server_time.isoformat(),
        "entities": entities,
        "tombstones": [
            {
                "entity_type": t.entity_type, "entity_id": t.entity_id,
                "space_id": t.space_id, "deleted_at": t.deleted_at.isoformat(),
            }
            for t in tombstones
        ],
    }


def _sort_ops(ops: list[SyncOp]) -> list[SyncOp]:
    """Parents vor Kindern anwenden (aus SyncEntity.depends_on) - stabile
    Sortierung sonst, damit die vom Client gesendete Reihenfolge innerhalb
    derselben Abhängigkeitsstufe erhalten bleibt."""

    def rank(entity_type: str, seen: Optional[set] = None) -> int:
        seen = seen or set()
        if entity_type in seen:
            return 0  # Zirkelbezug, sollte nicht vorkommen - nicht weiter verfolgen
        entity = SYNC_REGISTRY.get(entity_type)
        if not entity or not entity.depends_on:
            return 0
        return 1 + rank(entity.depends_on, seen | {entity_type})

    return sorted(ops, key=lambda op: rank(op.entity_type))


@sync_router.post("/push")
def push(
    body: SyncPushRequest, db: Session = Depends(get_db),
    x_sync_secret: Optional[str] = Header(None),
):
    _verify_secret(db, x_sync_secret)

    id_map: dict[str, int] = {}
    applied: list[str] = []
    conflicts: list[dict] = []

    for op in _sort_ops(body.ops):
        entity = SYNC_REGISTRY.get(op.entity_type)
        if not entity:
            conflicts.append({"entity_type": op.entity_type, "reason": f"Unbekannte Entität {op.entity_type}"})
            continue

        # Client-Temp-IDs in referenzierten Feldern (z.B. "account_id":
        # "tmp-1") auf die inzwischen bekannte echte Server-ID aufloesen.
        data = dict(op.data)
        for key, value in list(data.items()):
            if isinstance(value, str) and value in id_map:
                data[key] = id_map[value]

        try:
            if op.op == "create":
                if not entity.create_fn:
                    raise ValueError(f"{op.entity_type} unterstützt keine Erstellung per Sync")
                obj = entity.create_fn(db, body.space_id, data)
                if op.client_id:
                    id_map[op.client_id] = obj.id
                applied.append(op.client_id or f"create-{obj.id}")

            elif op.op == "update":
                if not entity.update_fn or op.server_id is None:
                    raise ValueError(f"{op.entity_type} unterstützt kein Update per Sync")
                current = db.query(entity.model).filter(entity.model.id == op.server_id).first()
                if not current:
                    raise ValueError(f"{op.entity_type} {op.server_id} nicht gefunden")
                if op.base_updated_at:
                    base = datetime.fromisoformat(op.base_updated_at)
                    current_updated_at = getattr(current, "updated_at", None)
                    if current_updated_at and current_updated_at > base:
                        conflicts.append({
                            "entity_type": op.entity_type, "server_id": op.server_id,
                            "server_data": _serialize_row(current),
                            "reason": "server_newer",
                        })
                        continue
                entity.update_fn(db, body.space_id, op.server_id, data)
                applied.append(f"update-{op.server_id}")

            elif op.op == "delete":
                if not entity.delete_fn or op.server_id is None:
                    raise ValueError(f"{op.entity_type} unterstützt keine Löschung per Sync (siehe sync_registry.py)")
                entity.delete_fn(db, body.space_id, op.server_id)
                applied.append(f"delete-{op.server_id}")

        except ValueError as e:
            db.rollback()
            conflicts.append({"entity_type": op.entity_type, "server_id": op.server_id, "reason": str(e)})

    return {"id_map": id_map, "applied": applied, "conflicts": conflicts}


# --- Universelle Kommandozeile fuer native Clients (Siri-Shortcut, siehe
# macos/Kies/Sources/KiesiOS/KiesAskIntent.swift). Auth ueber dasselbe
# X-Sync-Secret wie pull/push - ein nativer Client hat keinen Browser-
# Cookie. Routet durch hub_command (Smart Home, To-do, Wunschliste, ...).
class NativeCommandRequest(BaseModel):
    text: str
    confirm: bool = False


@sync_router.post("/command")
def native_command(
    body: NativeCommandRequest,
    db: Session = Depends(get_db),
    x_sync_secret: Optional[str] = Header(None),
):
    _verify_secret(db, x_sync_secret)
    from . import crud, hub_command
    settings = auth.get_or_create_settings(db)
    spaces = crud.get_spaces(db)
    space_id = spaces[0].id if spaces else 1
    return hub_command.route(db, settings, body.text, space_id, confirm=body.confirm)


# --- Apple-Health-Import vom iPhone (HealthKit -> health_metrics). Eigener
# schlanker Endpunkt statt HealthMetric ins generische Sync-Registry zu heben
# (die Tabelle hat kein updated_at/space_id). Upsert je (Typ, Tag) wie im
# Web-Formular (crud.create_health_metric), damit die Verlaufskurve nicht
# durch mehrere Tageswerte verzerrt wird. Auth: dasselbe X-Sync-Secret.
class HealthMetricIn(BaseModel):
    metric_type: Literal["gewicht", "schlaf", "schritte", "puls"]
    date: date
    value: float


class HealthSyncRequest(BaseModel):
    metrics: list[HealthMetricIn]


@sync_router.post("/health")
def sync_health(
    body: HealthSyncRequest,
    db: Session = Depends(get_db),
    x_sync_secret: Optional[str] = Header(None),
):
    _verify_secret(db, x_sync_secret)
    from . import crud, schemas as _schemas, models as _models

    saved = 0
    for m in body.metrics:
        if m.value < 0 or m.value != m.value:  # negativ / NaN aussortieren
            continue
        crud.create_health_metric(db, _schemas.HealthMetricCreate(
            metric_type=_models.HealthMetricType(m.metric_type),
            date=m.date,
            value=round(m.value, 3),
        ))
        saved += 1
    return {"ok": True, "saved": saved}
