"""Regen-Wahrscheinlichkeit für die Losfahren-Erinnerung - Open-Meteo, kostenlos
und ohne API-Key nötig. Mehr als die stündliche Niederschlagswahrscheinlichkeit
zur Heimat-Koordinate wird aktuell nirgends in der App gebraucht."""

from datetime import datetime

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 15


def precipitation_probability_percent(lat: float, lon: float, at: datetime) -> int | None:
    """Niederschlagswahrscheinlichkeit (%) zur nächstgelegenen vollen Stunde,
    None wenn außerhalb des Vorhersagezeitraums oder bei einem Fehler."""
    resp = requests.get(
        FORECAST_URL,
        params={
            "latitude": lat, "longitude": lon,
            "hourly": "precipitation_probability",
            "timezone": "UTC",
            "forecast_days": 2,
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    hourly = resp.json().get("hourly", {})
    times = hourly.get("time", [])
    probs = hourly.get("precipitation_probability", [])
    target = at.strftime("%Y-%m-%dT%H:00")
    if target in times:
        return probs[times.index(target)]
    return None
