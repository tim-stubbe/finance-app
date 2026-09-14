"""Navigation helpers for native Kies Drive clients.

Live fuel credentials remain on the server. Native clients authenticate with
their existing device token and only receive public station data.
"""
from __future__ import annotations

import math
import os
from typing import Literal

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import auth, bank_sync, models
from ..database import get_db

navigation_router = APIRouter(prefix="/api/navigation", tags=["navigation"])
TANKERKOENIG_URL = "https://creativecommons.tankerkoenig.de/json/list.php"


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
