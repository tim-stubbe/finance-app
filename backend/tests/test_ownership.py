"""Multi-User Phase 2 - "ein Besitzer pro Bereich" (ownership.py).

Deckt die im Sicherheits-Audit als IDOR markierten Bereichs-Endpunkte ab:
`/api/spaces` (Liste), `/api/spaces/{id}/select`.
"""
from app import auth, models, ownership
from app.database import SessionLocal


def _second_user_with_space(db):
    u = models.User(name="Zweitnutzer", password_hash=auth.hash_password("x" * 12))
    db.add(u)
    db.commit()
    db.refresh(u)
    s = models.Space(name="Fremd", icon="🔒", owner_id=u.id)
    db.add(s)
    db.commit()
    db.refresh(s)
    return u, s


def test_owns_space_rules():
    class _S:
        def __init__(self, owner_id):
            self.owner_id = owner_id

    class _U:
        id = 1

    assert ownership.owns_space(_U(), _S(None)) is True      # noch nicht migriert
    assert ownership.owns_space(_U(), _S(1)) is True          # eigener Bereich
    assert ownership.owns_space(_U(), _S(2)) is False         # fremder Bereich
    assert ownership.owns_space(None, _S(1)) is False
    assert ownership.owns_space(_U(), None) is False


def test_list_spaces_hides_foreign(auth_client):
    db = SessionLocal()
    try:
        _, foreign = _second_user_with_space(db)
        foreign_id = foreign.id
    finally:
        db.close()

    r = auth_client.get("/api/spaces")
    assert r.status_code == 200
    ids = {s["id"] for s in r.json()}
    assert foreign_id not in ids
    # Der eigene (migrations-offene, owner_id NULL) Bereich bleibt sichtbar.
    assert len(ids) >= 1


def test_select_foreign_space_404(auth_client):
    db = SessionLocal()
    try:
        _, foreign = _second_user_with_space(db)
        foreign_id = foreign.id
    finally:
        db.close()

    r = auth_client.post(f"/api/spaces/{foreign_id}/select")
    assert r.status_code == 404


def test_created_space_gets_owner(auth_client):
    r = auth_client.post("/api/spaces", json={"name": "Neu", "icon": "✨"})
    assert r.status_code == 200
    new_id = r.json()["id"]

    db = SessionLocal()
    try:
        me = db.query(models.User).order_by(models.User.id).first()
        space = db.query(models.Space).filter(models.Space.id == new_id).first()
        assert space.owner_id == me.id
    finally:
        db.close()

    # ...und ist damit auch auswählbar.
    assert auth_client.post(f"/api/spaces/{new_id}/select").status_code == 200
