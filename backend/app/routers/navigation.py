"""Navigation helpers for native Kies Drive clients.

Live fuel credentials remain on the server. Native clients authenticate with
their existing device token and only receive public station data.
"""
from __future__ import annotations

import math
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Literal

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import auth, bank_sync, models, websearch
from ..database import get_db

navigation_router = APIRouter(prefix="/api/navigation", tags=["navigation"])
TANKERKOENIG_URL = "https://creativecommons.tankerkoenig.de/json/list.php"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Suchradius um jeden Routenpunkt, innerhalb dessen eine Straße mit
# Tempolimit-Tag als "die Straße an dieser Stelle" gilt.
SPEED_LIMIT_SEARCH_RADIUS_M = 40


class TollSearchRequest(BaseModel):
    origin: str = Field(min_length=2, max_length=180)
    destination: str = Field(min_length=2, max_length=180)


def _explicit_toll_amount(text: str) -> float | None:
    """Only accept an amount directly labelled as total toll costs."""
    patterns = (
        r"(?:gesamtmaut|mautkosten|toll costs?)\s*(?:von|:|-)?\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:€|eur)",
        r"(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:€|eur)\s*(?:gesamtmaut|mautkosten|toll costs?)",
    )
    lowered = text.lower()
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            return float(match.group(1).replace(",", "."))
    return None


@navigation_router.post("/toll-search")
def toll_search(
    body: TollSearchRequest,
    db: Session = Depends(get_db),
    principal: models.AuthenticatedPrincipal = Depends(auth.require_session_or_device),
):
    """Research current car tolls through the user's own TrueNAS SearXNG.

    Search snippets are evidence, not a calculator: an amount is returned only
    when a result explicitly labels it as the total toll for the requested route.
    """
    del principal
    settings = auth.get_or_create_settings(db)
    if settings.websearch_provider != "searxng" or not settings.searxng_url:
        raise HTTPException(503, "SearXNG ist auf dem TrueNAS noch nicht eingerichtet")
    query = (
        f"PKW Mautkosten Gesamtmaut {body.origin} nach {body.destination} "
        f"{date.today().year}"
    )
    try:
        results = websearch.search_searxng(settings.searxng_url, query)
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(502, "SearXNG ist gerade nicht erreichbar") from exc

    sources = [
        {"title": item.get("title") or "Suchtreffer", "url": item.get("url") or "",
         "snippet": item.get("snippet") or ""}
        for item in results[:3]
    ]
    for source in sources:
        amount = _explicit_toll_amount(f"{source['title']} {source['snippet']}")
        if amount is not None:
            return {"status": "known", "amount": amount, "currency": "EUR",
                    "source": source["title"], "source_url": source["url"], "sources": sources}
    return {"status": "unknown", "amount": None, "currency": "EUR",
            "source": "SearXNG", "source_url": None, "sources": sources}


def _distance_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = math.radians(b_lat - a_lat), math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


@navigation_router.get("/fuel-stations")
def fuel_stations(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    radius_km: float = Query(default=10, gt=0, le=25),
    fuel: Literal["e5", "e10", "diesel"] = "diesel",
    db: Session = Depends(get_db),
    principal: models.AuthenticatedPrincipal = Depends(auth.require_session_or_device),
):
    del principal
    api_key = os.environ.get("TANKERKOENIG_API_KEY", "").strip()
    if not api_key:
        settings = auth.get_or_create_settings(db)
        if settings.tankerkoenig_api_key_encrypted:
            api_key = bank_sync.decrypt_secret(
                settings.secret_key, settings.tankerkoenig_api_key_encrypted
            )
    if not api_key:
        raise HTTPException(503, "Tankpreis-API ist noch nicht verbunden")
    try:
        response = requests.get(TANKERKOENIG_URL, params={
            "lat": lat, "lng": lon, "rad": radius_km,
            "sort": "dist", "type": fuel, "apikey": api_key,
        }, timeout=12)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(502, "Tankpreis-Dienst ist gerade nicht erreichbar") from exc
    if not payload.get("ok"):
        raise HTTPException(502, payload.get("message") or "Tankpreis-Abfrage fehlgeschlagen")
    stations = []
    for station in payload.get("stations", []):
        price = station.get("price")
        if price is None:
            continue
        stations.append({
            "id": station.get("id"), "name": station.get("name") or "Tankstelle",
            "brand": station.get("brand") or "", "street": station.get("street") or "",
            "place": station.get("place") or "", "lat": station.get("lat"),
            "lon": station.get("lng"), "price": price,
            "open": station.get("isOpen"),
            "distance_km": _distance_km(lat, lon, station["lat"], station["lng"]),
        })
    return {"ok": True, "fuel": fuel, "stations": stations}


class SpeedLimitPoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class SpeedLimitRequest(BaseModel):
    # Begrenzt auf sample-taugliche Größe - das sind bereits grob abgetastete
    # Routenpunkte (siehe RoutePlanner.sample in Kies Drive), keine ganze Polyline.
    points: list[SpeedLimitPoint] = Field(min_length=1, max_length=80)


# --- Kies Drive Remote/MCP bridge -----------------------------------------

class DriveLiveState(BaseModel):
    location: dict[str, Any] | None = None
    heading_degrees: float | None = None
    speed_kmh: float | None = None
    active_route: dict[str, Any] | None = None
    next_maneuver: dict[str, Any] | None = None
    route_lock: dict[str, Any] | None = None
    navigation_active: bool = False
    recorded_at: datetime


class DriveCommandResult(BaseModel):
    ok: bool
    message: str | None = None


@navigation_router.put("/remote/state")
def put_drive_state(
    state: DriveLiveState,
    db: Session = Depends(get_db),
    principal: models.AuthenticatedPrincipal = Depends(auth.require_session_or_device),
):
    if not principal.device:
        raise HTTPException(403, "Live-Status darf nur ein registriertes Drive-Gerät melden")
    row = db.get(models.DriveRemoteState, principal.device.id)
    payload = state.model_dump(mode="json")
    if row:
        row.payload = payload
        row.updated_at = datetime.utcnow()
    else:
        row = models.DriveRemoteState(device_id=principal.device.id, payload=payload,
                                      updated_at=datetime.utcnow())
        db.add(row)
    db.commit()
    return {"ok": True}


@navigation_router.get("/remote/commands")
def get_drive_commands(
    db: Session = Depends(get_db),
    principal: models.AuthenticatedPrincipal = Depends(auth.require_session_or_device),
):
    if not principal.device:
        raise HTTPException(403, "Befehle sind nur für registrierte Drive-Geräte verfügbar")
    rows = (db.query(models.DriveRemoteCommand)
            .filter(models.DriveRemoteCommand.status == "pending",
                    ((models.DriveRemoteCommand.device_id == principal.device.id) |
                     (models.DriveRemoteCommand.device_id.is_(None))))
            .order_by(models.DriveRemoteCommand.id).limit(10).all())
    return {"commands": [{"id": r.id, "command": r.command, "arguments": r.arguments}
                         for r in rows]}


@navigation_router.post("/remote/commands/{command_id}/complete")
def complete_drive_command(
    command_id: int,
    result: DriveCommandResult,
    db: Session = Depends(get_db),
    principal: models.AuthenticatedPrincipal = Depends(auth.require_session_or_device),
):
    if not principal.device:
        raise HTTPException(403, "Befehle sind nur für registrierte Drive-Geräte verfügbar")
    row = db.query(models.DriveRemoteCommand).filter_by(id=command_id).first()
    if not row or (row.device_id is not None and row.device_id != principal.device.id):
        raise HTTPException(404, "Befehl nicht gefunden")
    row.device_id = principal.device.id
    row.status = "completed" if result.ok else "failed"
    row.completed_at = datetime.utcnow()
    row.result = result.model_dump()
    db.commit()
    return {"ok": True}


_MCP_TOOLS = [
    {"name": "get_location", "description": "Aktuellen Standort von Kies Drive lesen.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_heading", "description": "Aktuelle Fahrtrichtung in Grad und Himmelsrichtung lesen.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_speed", "description": "Aktuelle GPS-Geschwindigkeit lesen.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_active_route", "description": "Aktive Route und persistenten Trip-Lock lesen.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_next_maneuver", "description": "Nächsten Navigationsschritt lesen.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "set_destination", "description": "Ziel in Kies Drive setzen; die App berechnet die Route lokal.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "latitude": {"type": "number"}, "longitude": {"type": "number"}, "required_waypoints": {"type": "array", "items": {"type": "object"}}}, "anyOf": [{"required": ["query"]}, {"required": ["latitude", "longitude"]}]}},
    {"name": "set_route_options", "description": "Globale oder abschnittsbezogene Routenvorgaben ändern.", "inputSchema": {"type": "object", "properties": {"avoid_tolls": {"type": "boolean"}, "avoid_highways": {"type": "boolean"}, "waypoint_id": {"type": "string"}}}},
    {"name": "restore_route", "description": "Persistenten Trip ab aktueller Position in Kies Drive fortsetzen.", "inputSchema": {"type": "object", "properties": {}}},
]


def _mcp_authorize(authorization: str | None) -> None:
    expected = os.environ.get("KIES_DRIVE_MCP_TOKEN", "").strip()
    if not expected:
        raise HTTPException(503, "KIES_DRIVE_MCP_TOKEN ist noch nicht gesetzt")
    if not authorization or authorization != f"Bearer {expected}":
        raise HTTPException(401, "Ungültiger MCP-Token")


def _latest_drive_state(db: Session) -> models.DriveRemoteState:
    row = db.query(models.DriveRemoteState).order_by(models.DriveRemoteState.updated_at.desc()).first()
    if not row:
        raise HTTPException(409, "Kies Drive hat noch keine Live-Daten gemeldet")
    return row


def _mcp_text(value: Any) -> dict[str, Any]:
    import json
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}


def _state_meta(state: models.DriveRemoteState) -> dict[str, Any]:
    age = max(0, int((datetime.utcnow() - state.updated_at).total_seconds()))
    return {"recorded_at": state.payload.get("recorded_at"), "age_seconds": age,
            "live": age <= 30, "warning": None if age <= 30 else "Live-Daten sind veraltet"}


def _call_drive_tool(db: Session, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    reads = {
        "get_location": "location", "get_heading": "heading_degrees",
        "get_speed": "speed_kmh", "get_next_maneuver": "next_maneuver",
    }
    if name in reads:
        state = _latest_drive_state(db)
        return _mcp_text({"value": state.payload.get(reads[name]), **_state_meta(state)})
    if name == "get_active_route":
        state = _latest_drive_state(db)
        return _mcp_text({"active_route": state.payload.get("active_route"),
                          "route_lock": state.payload.get("route_lock"),
                          "navigation_active": state.payload.get("navigation_active"),
                          **_state_meta(state)})
    if name not in {"set_destination", "set_route_options", "restore_route"}:
        raise HTTPException(400, f"Unbekanntes Tool: {name}")
    state = db.query(models.DriveRemoteState).order_by(models.DriveRemoteState.updated_at.desc()).first()
    command = models.DriveRemoteCommand(
        device_id=state.device_id if state else None, command=name,
        arguments=arguments, status="pending", created_at=datetime.utcnow(),
    )
    db.add(command)
    db.commit()
    return _mcp_text({"accepted": True, "command_id": command.id,
                      "message": "An Kies Drive gesendet; Navigation wird lokal in der App berechnet."})


@navigation_router.post("/mcp")
def drive_mcp(request_body: dict[str, Any], db: Session = Depends(get_db),
              authorization: str | None = Header(default=None)):
    """Kleiner MCP-Streamable-HTTP JSON-RPC-Endpunkt für Kies Drive."""
    _mcp_authorize(authorization)
    method = request_body.get("method")
    request_id = request_body.get("id")
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "kies-drive", "version": "1.0.0"}}
    elif method == "tools/list":
        result = {"tools": _MCP_TOOLS}
    elif method == "tools/call":
        params = request_body.get("params") or {}
        result = _call_drive_tool(db, params.get("name", ""), params.get("arguments") or {})
    elif method and method.startswith("notifications/"):
        return {"jsonrpc": "2.0", "result": {}}
    else:
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _parse_maxspeed(raw: str | None) -> tuple[int | None, bool]:
    """Gibt (Tempolimit in km/h, unbegrenzt) zurück, z.B. für Autobahn ohne Limit."""
    if not raw:
        return None, False
    value = raw.strip().lower()
    if value in ("none", "signals", "no", "unlimited"):
        return None, value == "none"
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None, False
    speed = int(digits)
    if "mph" in value:
        speed = round(speed * 1.60934)
    return speed, False


@navigation_router.post("/speed-limits")
def speed_limits(
    body: SpeedLimitRequest,
    principal: models.AuthenticatedPrincipal = Depends(auth.require_session_or_device),
):
    del principal
    points = body.points
    # Eine Overpass-Anfrage mit einer around()-Klausel pro Punkt statt einer
    # Anfrage pro Punkt - schont die öffentliche Overpass-API und bleibt
    # innerhalb ihres Zeitlimits.
    clauses = "\n".join(
        f'way["highway"]["maxspeed"](around:{SPEED_LIMIT_SEARCH_RADIUS_M},{p.lat:.6f},{p.lon:.6f});'
        for p in points
    )
    query = f"[out:json][timeout:20];\n({clauses}\n);\nout geom;"
    try:
        response = requests.post(OVERPASS_URL, data={"data": query}, timeout=25)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(502, "Tempolimit-Dienst (OpenStreetMap) ist gerade nicht erreichbar") from exc

    best: list[tuple[float, int | None, bool]] = [(float("inf"), None, False) for _ in points]
    for way in payload.get("elements", []):
        maxspeed, unlimited = _parse_maxspeed(way.get("tags", {}).get("maxspeed"))
        if maxspeed is None and not unlimited:
            continue
        for node in way.get("geometry") or []:
            if node is None:
                continue
            for i, p in enumerate(points):
                dist = _distance_km(p.lat, p.lon, node["lat"], node["lon"]) * 1000
                if dist < best[i][0] and dist <= SPEED_LIMIT_SEARCH_RADIUS_M:
                    best[i] = (dist, maxspeed, unlimited)

    limits = [{"maxspeed": m, "unlimited": u} for _, m, u in best]
    return {"ok": True, "limits": limits}
