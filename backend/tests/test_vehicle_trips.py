"""Fahrtenbuch: Import aus einem Speedometer°-Backup (speedometer.py) +
/api/vehicle/trips (Liste, Zusammenfassung, geschäftlich/privat setzen).
"""
import io
import json

from app import speedometer

# startDate/endDate = Sekunden seit 2001-01-01. 2026-08-30 11:34:37 UTC:
_START = 809782477.5
_END = 809783055.2

_BACKUP = {
    "version": 4,
    "exportDate": 809812649.79,
    "vehicles": [{"id": "V1", "name": "Peugeot 5008", "isDefault": True}],
    "trips": [
        {
            "id": "T1", "vehicleId": "V1", "statusRaw": "completed",
            "startDate": _START, "endDate": _END,
            "totalDistance": 3838.5, "duration": 577.65,
            "averageSpeed": 6.645, "maxSpeed": 21.81, "elevationGain": 29.3,
            "startLatitude": 49.8486, "startLongitude": 8.3200,
            "endLatitude": 49.8613, "endLongitude": 8.3166,
            "startLocationName": "32 Schloßstraße, Dexheim", "startCity": "Dexheim",
            "endLocationName": "", "endCity": "Dexheim",
            "routeDataBase64": "AAECAwQF",
        },
        {
            "id": "T2", "vehicleId": "V1", "statusRaw": "completed",
            "startDate": _START + 90000, "endDate": _START + 91800,
            "totalDistance": 12490.0, "duration": 1800.0,
            "averageSpeed": 12.0, "maxSpeed": 30.0,
            "startLocationName": "A", "endLocationName": "B",
        },
    ],
}


def test_parser_maps_units_correctly():
    trips = speedometer.parse_speedometer_backup(_BACKUP)
    assert len(trips) == 2
    t = trips[0]
    assert t["external_id"] == "T1"
    assert t["source_vehicle"] == "Peugeot 5008"
    assert abs(t["distance_km"] - 3.838) < 0.001          # Meter -> km
    assert abs(t["avg_speed_kmh"] - 23.9) < 0.1           # m/s * 3.6
    assert abs(t["max_speed_kmh"] - 78.5) < 0.1
    assert t["start_location"] == "32 Schloßstraße, Dexheim"
    assert t["end_location"] == "Dexheim"                  # Fallback auf endCity
    assert t["started_at"].year == 2026 and t["started_at"].month == 8
    assert t["track_bytes"] == b"\x00\x01\x02\x03\x04\x05"
    assert t["purpose"] == "unbekannt"


def test_upload_import_dedups_and_summary_and_purpose(auth_client):
    fd = {"file": ("backup.speedometer", io.BytesIO(json.dumps(_BACKUP).encode()), "application/json")}
    r = auth_client.post("/api/vehicle/trips/import", files=fd)
    assert r.status_code == 200
    assert r.json()["imported"] == 2

    # zweiter Import derselben Datei -> alles übersprungen
    fd = {"file": ("backup.speedometer", io.BytesIO(json.dumps(_BACKUP).encode()), "application/json")}
    assert auth_client.post("/api/vehicle/trips/import", files=fd).json() == {"ok": True, "imported": 0, "skipped": 2}

    trips = auth_client.get("/api/vehicle/trips").json()
    assert len(trips) == 2
    assert trips[0]["started_at"] >= trips[1]["started_at"]     # neueste zuerst

    summ = auth_client.get("/api/vehicle/trips/summary").json()
    assert summ["trip_count"] == 2
    assert abs(summ["total_km"] - (3.838 + 12.49)) < 0.05
    assert summ["vehicles"] == ["Peugeot 5008"]
    assert summ["unknown_km"] > 0 and summ["business_km"] == 0.0

    t1 = next(t for t in trips if t["distance_km"] < 5)
    r = auth_client.patch(f"/api/vehicle/trips/{t1['id']}", json={"purpose": "geschaeftlich", "note": "Kunde"})
    assert r.status_code == 200 and r.json()["purpose"] == "geschaeftlich"
    summ = auth_client.get("/api/vehicle/trips/summary").json()
    assert abs(summ["business_km"] - 3.8) < 0.1

    # Track wurde abgelegt und ist abrufbar
    assert auth_client.get(f"/api/vehicle/trips/{t1['id']}/track").status_code == 200


def test_webhook_needs_secret(auth_client):
    r = auth_client.post("/api/webhook/vehicle-trips", json=_BACKUP)
    assert r.status_code == 403


def test_path_traversal_external_id_is_neutralised(auth_client):
    """Eine Fahrt mit bösartiger ID darf keine Datei außerhalb des Track-
    Ordners schreiben (Path Traversal über den Manifest-Dateinamen)."""
    evil = {
        "version": 4, "vehicles": [{"id": "V1", "name": "X"}],
        "trips": [{
            "id": "../../../../tmp/kies-pwned", "vehicleId": "V1", "statusRaw": "completed",
            "startDate": _START, "totalDistance": 1000.0, "duration": 60.0,
            "routeDataBase64": "cHduZWQ=",
        }],
    }
    import io, json, os
    fd = {"file": ("b.speedometer", io.BytesIO(json.dumps(evil).encode()), "application/json")}
    r = auth_client.post("/api/vehicle/trips/import", files=fd)
    assert r.status_code == 200 and r.json()["imported"] == 1
    assert not os.path.exists("/tmp/kies-pwned")
    assert not os.path.exists("/tmp/kies-pwned.spdtrack")
    # Track ist trotzdem korrekt (unter sicherem Namen) abgelegt und abrufbar
    tid = auth_client.get("/api/vehicle/trips").json()[0]["id"]
    assert auth_client.get(f"/api/vehicle/trips/{tid}/track").status_code == 200
