"""Fahrzeit zu Terminen - Adressen per OpenStreetMap/Nominatim geokodieren
(kostenlos, kein API-Key), Fahrzeit per OpenRouteService berechnen (kostenloser
Account nötig, 2000 Anfragen/Tag im Gratis-Tarif). Reine Schätzung ab einer
festen Startadresse (kein Live-Standort verfügbar), Auto als Verkehrsmittel."""

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
ORS_DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/driving-car"
# Nominatims Nutzungsbedingungen verlangen einen aussagekräftigen User-Agent
# (keine Standard-requests-Kennung) - sonst werden Anfragen abgelehnt.
_HEADERS = {"User-Agent": "Kies-Finanztool/1.0 (privates Selbsthosting, kein Massenabruf)"}


def geocode(address: str) -> tuple[float, float] | None:
    """Adresse -> (lat, lon), oder None wenn nichts gefunden wurde."""
    resp = requests.get(
        NOMINATIM_URL, params={"q": address, "format": "json", "limit": 1},
        headers=_HEADERS, timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"])


def travel_time_minutes(api_key: str, start: tuple[float, float], end: tuple[float, float]) -> int | None:
    """Fahrzeit in Minuten (Auto) zwischen zwei Koordinaten. `start`/`end` sind
    (lat, lon) - ORS selbst will lon,lat, wird hier intern umgedreht."""
    resp = requests.get(
        ORS_DIRECTIONS_URL,
        params={
            "api_key": api_key,
            "start": f"{start[1]},{start[0]}",
            "end": f"{end[1]},{end[0]}",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        seconds = data["features"][0]["properties"]["segments"][0]["duration"]
    except (KeyError, IndexError):
        return None
    return round(seconds / 60)
