"""Tests für Ziele: die beiden Validierungs-Wächter in routers/goals.py, die
sonst nur beim manuellen Ausprobieren auffallen würden - ein automatisch
messbares Ziel ohne Auswertungsregel, ein Ziel als sein eigener Vorgänger,
ein von Hand abgehaktes auto_financial-Ziel."""


def test_manual_goal_create_and_complete(auth_client):
    r = auth_client.post("/api/goals", json={"title": "Neues Sofa kaufen", "goal_type": "manual"})
    assert r.status_code == 200
    goal_id = r.json()["id"]
    assert r.json()["status"] == "open"

    r = auth_client.post(f"/api/goals/{goal_id}/complete")
    assert r.status_code == 200
    assert r.json()["goal"]["status"] == "completed"


def test_auto_financial_goal_requires_trigger(auth_client):
    r = auth_client.post("/api/goals", json={"title": "10000€ sparen", "goal_type": "auto_financial"})
    assert r.status_code == 400


def test_auto_financial_goal_cannot_be_manually_completed(auth_client):
    r = auth_client.post("/api/goals", json={
        "title": "10000€ sparen", "goal_type": "auto_financial",
        "trigger": {"metric_type": "net_worth", "comparison": "gte", "threshold_value": 10000.0},
    })
    assert r.status_code == 200
    goal_id = r.json()["id"]

    r = auth_client.post(f"/api/goals/{goal_id}/complete")
    assert r.status_code == 400


def test_goal_cannot_be_its_own_predecessor(auth_client):
    r = auth_client.post("/api/goals", json={"title": "Ziel A", "goal_type": "manual"})
    goal_id = r.json()["id"]

    r = auth_client.put(f"/api/goals/{goal_id}", json={"predecessor_goal_id": goal_id})
    assert r.status_code == 400


def test_predecessor_must_exist(auth_client):
    r = auth_client.post("/api/goals", json={
        "title": "Ziel B", "goal_type": "manual", "predecessor_goal_id": 999999,
    })
    assert r.status_code == 400


def test_delete_goal(auth_client):
    r = auth_client.post("/api/goals", json={"title": "Löschbares Ziel", "goal_type": "manual"})
    goal_id = r.json()["id"]
    r = auth_client.delete(f"/api/goals/{goal_id}")
    assert r.status_code == 200
    r = auth_client.delete(f"/api/goals/{goal_id}")
    assert r.status_code == 404
