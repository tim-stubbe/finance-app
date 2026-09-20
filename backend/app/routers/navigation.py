"""Navigation helpers for native Kies Drive clients.

Live fuel credentials remain on the server. Native clients authenticate with
their existing device token and only receive public station data.
"""
from __future__ import annotations

import math
import os
import re
from datetime import date
from typing import Literal

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
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
