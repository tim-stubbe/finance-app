"""_note_entity_label darf bei der Notiz-Suche keinen Titel aus einem fremden
Bereich durchsickern lassen (Multi-User Phase 2 / Sicherheits-Audit)."""
from app import models
from app.routers.personal import _note_entity_label
from app.database import SessionLocal


def test_goal_label_scoped_to_space():
    db = SessionLocal()
    try:
        s_a = db.query(models.Space).first()
        s_b = models.Space(name="B", icon="🅱️")
        db.add(s_b)
        db.commit()

        g_a = models.Goal(title="Ziel A", space_id=s_a.id)
        g_b = models.Goal(title="Ziel B", space_id=s_b.id)
        g_null = models.Goal(title="Ziel global", space_id=None)
        db.add_all([g_a, g_b, g_null])
        db.commit()

        # Aus Bereich A gesucht: eigenes Ziel + bereichsloses Ziel sichtbar,
        # fremdes NICHT.
        assert _note_entity_label(db, "goal", g_a.id, s_a.id) == "Ziel A"
        assert _note_entity_label(db, "goal", g_null.id, s_a.id) == "Ziel global"
        assert _note_entity_label(db, "goal", g_b.id, s_a.id) is None

        # Ohne space_id (Alt-Aufruf) weiterhin best-effort ohne Einschraenkung.
        assert _note_entity_label(db, "goal", g_b.id) == "Ziel B"
    finally:
        db.close()
