"""Parser für Backups der iOS-App "Speedometer°" (Format-Version 4).

Wandelt einen Backup-Export (JSON, Dateiendung `.speedometer`) bzw. dessen
`trips`-Array in Kies' neutrales Fahrten-Schema um (siehe
crud.import_vehicle_trips). Reine Umwandlung, keine DB.

Beobachtetes Format (ein Trip):
  id                  UUID                      -> external_id
  startDate/endDate   Sekunden seit 2001-01-01  -> started_at / ended_at
  totalDistance       Meter                     -> distance_km
  duration            Sekunden
  averageSpeed        m/s                       -> avg_speed_kmh (*3.6)
  maxSpeed            m/s                       -> max_speed_kmh
  elevationGain       Meter
  start/endLatitude, start/endLongitude
  startLocationName / startCity, endLocationName / endCity
  vehicleId          -> Name über vehicles[]    -> source_vehicle
  routeDataBase64     gepackter GPS-Track        -> als Rohdatei ablegen
  statusRaw          "completed" | ...
Kein Kilometerstand und (in diesem Export) keine geschäftlich/privat-Tags.
"""

import base64
from datetime import datetime, timedelta

_COCOA_EPOCH = datetime(2001, 1, 1)


def _cocoa(ts):
    try:
        return _COCOA_EPOCH + timedelta(seconds=float(ts))
    except (TypeError, ValueError):
        return None


def _f(v):
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def looks_like_speedometer_backup(data) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("trips"), list)
        and ("vehicles" in data or "exportDate" in data or data.get("version") in (3, 4, 5))
    )


def parse_speedometer_backup(data: dict) -> list[dict]:
    """Backup-Objekt -> Liste normalisierter Fahrten-Dicts (siehe
    crud.import_vehicle_trips für die erwarteten Schlüssel)."""
    veh_names = {}
    for v in data.get("vehicles", []) or []:
        if isinstance(v, dict) and v.get("id"):
            veh_names[v["id"]] = v.get("name")

    out = []
    for t in data.get("trips", []) or []:
        if not isinstance(t, dict):
            continue
        started = _cocoa(t.get("startDate"))
        if started is None:
            continue
        if str(t.get("statusRaw", "completed")).lower() not in ("completed", "finished", ""):
            continue
        dist_m = t.get("totalDistance") or 0
        avg = t.get("averageSpeed")
        mx = t.get("maxSpeed")
        track_b64 = t.get("routeDataBase64") or None
        track_bytes = None
        if track_b64:
            try:
                track_bytes = base64.b64decode(track_b64)
            except Exception:  # noqa: BLE001
                track_bytes = None
        out.append({
            "external_id": t.get("id"),
            "source": "speedometer",
            "source_vehicle": veh_names.get(t.get("vehicleId")),
            "started_at": started,
            "ended_at": _cocoa(t.get("endDate")),
            "distance_km": round(float(dist_m) / 1000.0, 3),
            "duration_s": int(round(float(t["duration"]))) if t.get("duration") is not None else None,
            "avg_speed_kmh": round(float(avg) * 3.6, 1) if avg is not None else None,
            "max_speed_kmh": round(float(mx) * 3.6, 1) if mx is not None else None,
            "elevation_gain_m": _f(t.get("elevationGain")),
            "start_location": t.get("startLocationName") or t.get("startCity"),
            "end_location": t.get("endLocationName") or t.get("endCity"),
            "start_lat": _f(t.get("startLatitude")),
            "start_lon": _f(t.get("startLongitude")),
            "end_lat": _f(t.get("endLatitude")),
            "end_lon": _f(t.get("endLongitude")),
            "purpose": "unbekannt",
            "track_bytes": track_bytes,
            "track_ext": "spdtrack",   # Speedometers eigenes gepacktes Format
        })
    return out
