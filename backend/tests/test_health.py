"""Gesundheits-Grunddaten: die neuen Metrik-Typen schritte/puls (Phase 9)."""


def test_new_metric_types_roundtrip(auth_client):
    for mt, val in (("schritte", 8421), ("puls", 58), ("gewicht", 74.3)):
        r = auth_client.post("/api/health-metrics",
                             json={"metric_type": mt, "date": "2026-09-01", "value": val})
        assert r.status_code == 200, r.text
        got = auth_client.get(f"/api/health-metrics?metric_type={mt}&days=90").json()
        assert got and got[-1]["value"] == val


def test_second_entry_same_day_overwrites(auth_client):
    auth_client.post("/api/health-metrics", json={"metric_type": "schritte", "date": "2026-09-02", "value": 100})
    auth_client.post("/api/health-metrics", json={"metric_type": "schritte", "date": "2026-09-02", "value": 9000})
    got = auth_client.get("/api/health-metrics?metric_type=schritte&days=90").json()
    same_day = [p for p in got if p["date"] == "2026-09-02"]
    assert len(same_day) == 1 and same_day[0]["value"] == 9000
