from datetime import datetime, timedelta

from app import crud, models
from app.database import SessionLocal


def _event(uid: str, title: str, start: datetime, minutes: int = 45):
    return models.CalendarEvent(
        uid=uid,
        title=title,
        start=start,
        end=start + timedelta(minutes=minutes),
        all_day=False,
        pending_delete=False,
    )


def test_webuntis_lessons_do_not_create_calendar_conflicts():
    db = SessionLocal()
    try:
        start = datetime.utcnow() + timedelta(days=1)
        db.add_all([
            _event("webuntis-101@kies", "Unterricht", start),
            _event("webuntis-102@kies", "Unterricht", start),
        ])
        db.commit()

        assert crud.detect_calendar_conflicts(db) == []
    finally:
        db.close()


def test_regular_overlapping_events_still_create_a_conflict():
    db = SessionLocal()
    try:
        start = datetime.utcnow() + timedelta(days=1)
        db.add_all([
            _event("private-1", "Arzt", start),
            _event("private-2", "Werkstatt", start + timedelta(minutes=15)),
        ])
        db.commit()

        conflicts = crud.detect_calendar_conflicts(db)
        assert len(conflicts) == 1
        assert {conflicts[0]["event_a_title"], conflicts[0]["event_b_title"]} == {"Arzt", "Werkstatt"}
    finally:
        db.close()
